"""Automatic backup / restore so data survives Render free-tier restarts.

Primary store : a PRIVATE GitHub repo (env GH_TOKEN, GH_REPO="user/repo", optional GH_BRANCH, GH_PATH)
Secondary     : the database file is also sent to the admin on Telegram (every 6h if changed).
Also          : download / upload-restore from the website Backup page.
"""
import os, io, re, gzip, time, base64, sqlite3, hashlib, threading, traceback
import requests
import db

GH_TOKEN = os.getenv("GH_TOKEN", "")
GH_REPO = os.getenv("GH_REPO", "")
GH_BRANCH = os.getenv("GH_BRANCH", "main")
GH_PATH = os.getenv("GH_PATH", "backup/data.db.gz")
STATUS = {"last_ok": 0, "last_err": "", "last_tg": 0, "size": 0, "auto_err": "", "auto_retry": 0}
_lock = threading.Lock()


def enabled():
    return bool(GH_TOKEN and GH_REPO)


def _h(raw=False):
    h = {"Authorization": f"Bearer {GH_TOKEN}", "X-GitHub-Api-Version": "2022-11-28"}
    h["Accept"] = "application/vnd.github.raw+json" if raw else "application/vnd.github+json"
    return h


def _url():
    return f"https://api.github.com/repos/{GH_REPO}/contents/{GH_PATH}"


def snapshot():
    """Consistent copy of the live DB -> gzip bytes."""
    tmp = db.DB_PATH + ".snap"
    src = sqlite3.connect(db.DB_PATH, timeout=30)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    with open(tmp, "rb") as f:
        raw = f.read()
    os.remove(tmp)
    return gzip.compress(raw, 6)


def push_github(blob):
    meta = requests.get(_url(), headers=_h(), params={"ref": GH_BRANCH}, timeout=30)
    body = {"message": "backup " + time.strftime("%Y-%m-%d %H:%M:%S"),
            "content": base64.b64encode(blob).decode(), "branch": GH_BRANCH}
    if meta.status_code == 200:
        body["sha"] = meta.json()["sha"]
    elif meta.status_code != 404:
        raise RuntimeError(f"GitHub {meta.status_code}: {meta.text[:150]}")
    r = requests.put(_url(), headers=_h(), json=body, timeout=60)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub {r.status_code}: {r.text[:150]}")


def restore_github():
    r = requests.get(_url(), headers=_h(raw=True), params={"ref": GH_BRANCH}, timeout=60)
    if r.status_code != 200:
        return False
    return restore_bytes(r.content, gz=True)


def restore_bytes(data, gz=False):
    """Validate then replace the DB file. Used at boot and by the website upload."""
    try:
        raw = gzip.decompress(data) if (gz or data[:2] == b"\x1f\x8b") else data
        if raw[:15] != b"SQLite format 3":
            return False
        tmp = db.DB_PATH + ".restore"
        with open(tmp, "wb") as f:
            f.write(raw)
        t = sqlite3.connect(tmp)
        ok = t.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        t.execute("SELECT COUNT(*) FROM users")
        t.close()
        if not ok:
            os.remove(tmp)
            return False
        for ext in ("-wal", "-shm"):
            if os.path.exists(db.DB_PATH + ext):
                os.remove(db.DB_PATH + ext)
        os.replace(tmp, db.DB_PATH)
        db._gc.clear()
        db.emoji_clear()
        return True
    except Exception:
        traceback.print_exc()
        return False


def restore_if_missing():
    """Call BEFORE db.init(). On a fresh Render disk, pull the last backup."""
    if os.path.exists(db.DB_PATH) and os.path.getsize(db.DB_PATH) > 0:
        return
    if enabled():
        try:
            print("Restore from GitHub:", "OK" if restore_github() else "no backup found")
        except Exception as e:
            print("Restore failed:", e)


def run_now(send_tg=None):
    """Make a backup right now. Returns (ok, message)."""
    with _lock:
        try:
            blob = snapshot()
            STATUS["size"] = len(blob)
            if enabled():
                push_github(blob)
            STATUS["last_ok"], STATUS["last_err"] = int(time.time()), ""
            db.DIRTY["v"] = False
            if send_tg:
                send_tg(blob)
            return True, "Backup done" + ("" if enabled() else " (GitHub not configured - only local copy)")
        except Exception as e:
            STATUS["last_err"] = str(e)[:200]
            traceback.print_exc()
            return False, STATUS["last_err"]


# ------------------------------------------------------------------ V18: timer + send-to-any-chat
# Stored in the normal settings table:  bk_chat (Telegram chat ID), bk_hours, bk_auto (1/0), bk_last (unix time)
MIN_HOURS, MAX_HOURS = 0.25, 720


def auto_info():
    chat = (db.get("bk_chat", "") or "").strip()
    try:
        hours = float(db.get("bk_hours", "6") or 6)
    except ValueError:
        hours = 6.0
    try:
        last = int(float(db.get("bk_last", "0") or 0))
    except ValueError:
        last = 0
    return {"chat": chat, "hours": hours, "on": db.get("bk_auto", "0") == "1", "last": last,
            "next": (last + int(hours * 3600)) if last else 0}


def save_auto(chat, hours, on):
    """Validate + store the timer settings. Returns (ok, message)."""
    chat = (chat or "").strip()
    if not re.fullmatch(r"-?\d{5,20}", chat):
        return False, "Chat ID must be a number (groups/channels start with -100...)."
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        return False, "Hours must be a number, e.g. 1, 6, 12, 24 or 0.5."
    if not (MIN_HOURS <= hours <= MAX_HOURS):
        return False, f"Hours must be between {MIN_HOURS} and {MAX_HOURS}."
    db.put("bk_chat", chat)
    db.put("bk_hours", ("%g" % hours))
    db.put("bk_auto", "1" if on else "0")
    return True, ("Auto backup ON - every %g hour(s) to %s" % (hours, chat)) if on else "Saved. Auto backup is OFF."


def send_backup(send_to, chat=None):
    """Backup now (GitHub too) and send the file to the saved chat ID. send_to(chat, name, bytes) -> telegram reply dict."""
    chat = chat or auto_info()["chat"]
    if not chat:
        return False, "Set a Chat ID first (Auto Backup box) and press Save."

    def cb(blob):
        r = send_to(chat, "backup_" + time.strftime("%Y%m%d_%H%M") + ".db.gz", blob)
        if not r.get("ok"):
            raise RuntimeError("Telegram: " + str(r.get("description", "send failed"))[:150] +
                               " (open the bot / add it to the group or channel first)")
        STATUS["last_tg"] = int(time.time())

    ok, msg = run_now(cb)
    return (True, "Backup sent to chat " + str(chat)) if ok else (False, msg)


def loop(send_doc, send_to=None):
    """send_doc(filename, bytes) -> admin chat (old behaviour); send_to(chat, filename, bytes) -> any chat."""
    time.sleep(45)
    while True:
        try:
            if db.DIRTY["v"] and enabled() and time.time() - STATUS["last_ok"] >= 180:
                run_now()
            a = auto_info()
            if a["on"] and a["chat"] and send_to:
                if time.time() >= max(a["next"], STATUS["auto_retry"]):
                    old = db.get("bk_last", "0")
                    db.put("bk_last", str(int(time.time())))      # saved first so the backup itself contains it
                    ok, msg = send_backup(send_to, a["chat"])
                    if ok:
                        STATUS["auto_err"] = ""
                    else:
                        db.put("bk_last", old)
                        STATUS["auto_err"] = msg
                        STATUS["auto_retry"] = time.time() + 300     # try again in 5 minutes
            elif db.DIRTY["v"] or STATUS["last_tg"] == 0:             # timer OFF: old behaviour (admin, every 6h if changed)
                if time.time() - STATUS["last_tg"] >= 6 * 3600:
                    blob = snapshot()
                    send_doc("backup_" + time.strftime("%Y%m%d_%H%M") + ".db.gz", blob)
                    STATUS["last_tg"] = int(time.time())
        except Exception:
            traceback.print_exc()
        time.sleep(30)
