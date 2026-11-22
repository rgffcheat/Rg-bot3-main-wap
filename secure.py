"""V15 - admin roles, Telegram -> website auto login, new-device approval, bans.
Everything is stored in the normal `settings` table (so the GitHub backup keeps it)."""
import json, time, secrets, hmac, hashlib, threading
from urllib.parse import parse_qsl
from datetime import datetime, timezone, timedelta
import db

IST = timezone(timedelta(hours=5, minutes=30))
_lk = threading.Lock()
PENDING = {}          # rid -> device-approval request (memory only, lives 3 minutes)
ADD_WAIT = {}         # owner uid -> time he pressed "Add admin" (waiting for the ID)
WAIT_SECONDS = 180


def _bot():
    import bot
    return bot


# ------------------------------------------------------------------ admins
def owner_id():
    return _bot().ADMIN_ID


def admin_ids():
    out = []
    for x in db.get("admins", "").split(","):
        x = x.strip()
        if x.isdigit():
            out.append(int(x))
    return out


def is_owner(uid):
    return bool(uid) and uid == owner_id()


def is_admin(uid):
    return bool(uid) and (uid == owner_id() or uid in admin_ids())


def add_admin(uid):
    uid = int(uid)
    if uid == owner_id():
        return False, "That is already the owner."
    ids = admin_ids()
    if uid in ids:
        return False, "Already an admin."
    ids.append(uid)
    db.put("admins", ",".join(str(i) for i in ids))
    return True, "ok"


def remove_admin(uid):
    uid = int(uid)
    ids = admin_ids()
    if uid not in ids:
        return False
    ids.remove(uid)
    db.put("admins", ",".join(str(i) for i in ids))
    return True


# ------------------------------------------------------------------ Telegram command menu
START_CMD = [{"command": "start", "description": "Open main menu ⚡"}]
ADMIN_CMDS = START_CMD + [{"command": "admin", "description": "Open admin panel 🔨"},
                          {"command": "website", "description": "Open admin website 🌐"},
                          {"command": "broadcast", "description": "Send broadcast 📣"},
                          {"command": "user", "description": "Find a user 🔎"}]


def sync_commands(only=None):
    """users/resellers: only /start.  owner + admins: /start /admin /website (per-chat menu)."""
    b = _bot()
    if not b.TOKEN:
        return
    if only is None:
        b.api("setMyCommands", commands=json.dumps(START_CMD), scope=json.dumps({"type": "default"}))
    targets = [only] if only else list({owner_id(), *admin_ids()})
    for uid in targets:
        if not uid:
            continue
        sc = json.dumps({"type": "chat", "chat_id": uid})
        if is_admin(uid):
            b.api("setMyCommands", commands=json.dumps(ADMIN_CMDS), scope=sc)
        else:
            b.api("deleteMyCommands", scope=sc)


def startup():
    time.sleep(6)
    try:
        sync_commands()
    except Exception as e:
        print("sync_commands:", e)


# ------------------------------------------------------------------ Telegram WebApp login (no password)
def verify_init_data(init, max_age=3600):
    """Telegram signs the WebApp data with the bot token. Returns the Telegram user id or None."""
    try:
        pairs = dict(parse_qsl(init or "", keep_blank_values=True))
        h = pairs.pop("hash", None)
        if not h:
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", _bot().TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, h):
            return None
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return int(json.loads(pairs["user"])["id"])
    except Exception:
        return None


# ------------------------------------------------------------------ trusted devices + bans
def _jget(k, default):
    try:
        return json.loads(db.get(k, "") or json.dumps(default))
    except Exception:
        return default


def trusted():
    return _jget("trusted_devs", [])


def device_trusted(dev):
    return bool(dev) and any(d.get("id") == dev for d in trusted())


def trust(dev, ip="", ua=""):
    with _lk:
        lst = [d for d in trusted() if d.get("id") != dev]
        lst.append({"id": dev, "ip": ip, "ua": ua[:120], "ts": int(time.time())})
        db.put("trusted_devs", json.dumps(lst[-30:]))


def revoke_all():
    db.put("trusted_devs", "[]")


def bans():
    d = _jget("web_banned", {})
    return {"dev": d.get("dev", []), "ip": d.get("ip", [])}


def ban(dev, ip):
    with _lk:
        d = bans()
        if dev and dev not in d["dev"]:
            d["dev"].append(dev)
        if ip and ip not in d["ip"]:
            d["ip"].append(ip)
        db.put("web_banned", json.dumps({"dev": d["dev"][-50:], "ip": d["ip"][-50:]}))


def unban_all():
    db.put("web_banned", "{}")


def is_blocked(dev, ip):
    d = bans()
    return (dev in d["dev"]) or (ip in d["ip"])


# ------------------------------------------------------------------ new-device approval
def short_ua(ua):
    ua = ua or ""
    os_ = next((n for k, n in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"), ("Windows", "Windows"),
                               ("Mac OS", "Mac"), ("Linux", "Linux")) if k in ua), "Unknown OS")
    br = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox", "Firefox"), ("Chrome", "Chrome"),
                              ("Safari", "Safari")) if k in ua), "Browser")
    return f"{br} · {os_}"


def new_request(dev, ip, ua):
    """password was correct but the device is new -> ask the owner in Telegram"""
    now = time.time()
    with _lk:
        for k in [k for k, v in PENDING.items() if now - v["t"] > 900]:
            PENDING.pop(k, None)
        rid = secrets.token_urlsafe(6)
        PENDING[rid] = {"dev": dev, "ip": ip, "ua": ua, "t": now, "st": "wait"}
    b = _bot()
    when = datetime.now(IST).strftime("%d %b %Y · %H:%M:%S IST")
    text = ("🚨 <b>ADMIN LOGIN — NEW DEVICE</b> 🚨\n━━━━━━━━━━━━━━━━━━\n\n"
            "Someone entered the <b>correct username & password</b> on the website.\n\n"
            f"📱 <b>Device:</b> {b.esc(short_ua(ua))}\n🌐 <b>IP:</b> <code>{b.esc(ip)}</code>\n🕐 <b>Time:</b> {when}\n\n"
            "Is this you? (No answer in 3 minutes = login refused)")
    kb = {"inline_keyboard": [[{"text": "✅ Yes, it's me", "callback_data": f"wl:y:{rid}", "style": "success"},
                               {"text": "🚫 No — Ban", "callback_data": f"wl:n:{rid}", "style": "danger"}]]}
    r = b.send(owner_id(), text, kb)
    if not r.get("ok"):
        PENDING[rid]["st"] = "expired"
    return rid


def get_request(rid):
    with _lk:
        p = PENDING.get(rid)
        if p and p["st"] == "wait" and time.time() - p["t"] > WAIT_SECONDS:
            p["st"] = "expired"
        return p


def decide(rid, yes):
    """owner pressed Yes / No. Returns 'ok' | 'no' | 'old'"""
    p = get_request(rid)
    if not p or p["st"] != "wait":
        return "old"
    if yes:
        p["st"] = "ok"
        trust(p["dev"], p["ip"], p["ua"])
        return "ok"
    p["st"] = "no"
    ban(p["dev"], p["ip"])
    return "no"
