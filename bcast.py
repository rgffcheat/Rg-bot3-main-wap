"""V16 - broadcast system run from the Telegram bot (history, edit, delete)."""
import time
import db

WAIT = {}          # admin uid -> what the bot is waiting for (target id / the message / new text / confirm)
LABEL = {"all": "All (users + resellers)", "usr": "Only users", "res": "Only resellers", "one": "One person"}
ICON = {"text": "💬", "photo": "🖼", "video": "🎬", "audio": "🎵", "voice": "🎤", "document": "📎",
        "animation": "🎞", "video_note": "⭕"}
EDITABLE = ("text", "photo", "video", "audio", "document", "animation")      # text / caption can be edited
_ready = {"v": False}


def ensure():
    if _ready["v"]:
        return
    with db.conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS bc(id INTEGER PRIMARY KEY AUTOINCREMENT, created INTEGER, by_uid INTEGER, target TEXT,
            kind TEXT, preview TEXT DEFAULT '', total INTEGER DEFAULT 0, ok INTEGER DEFAULT 0, fail INTEGER DEFAULT 0,
            deleted INTEGER DEFAULT 0, edited INTEGER DEFAULT 0, state TEXT DEFAULT 'sending');
        CREATE TABLE IF NOT EXISTS bc_msgs(bc_id INTEGER, chat_id INTEGER, msg_id INTEGER);
        CREATE INDEX IF NOT EXISTS bc_msgs_i ON bc_msgs(bc_id);""")
    _ready["v"] = True


def targets(kind):
    q = "SELECT id FROM users WHERE verified=1 AND banned=0"
    if kind == "res":
        q += " AND role='reseller'"
    elif kind == "usr":
        q += " AND (role IS NULL OR role!='reseller')"
    with db.conn() as c:
        return [r["id"] for r in c.execute(q)]


def create(by_uid, target, kind, preview, total):
    ensure()
    with db.conn() as c:
        cur = c.execute("INSERT INTO bc(created,by_uid,target,kind,preview,total) VALUES(?,?,?,?,?,?)",
                        (int(time.time()), by_uid, target, kind, preview[:200], total))
        return cur.lastrowid


def add_msgs(bid, rows):
    if rows:
        with db.conn() as c:
            c.executemany("INSERT INTO bc_msgs(bc_id,chat_id,msg_id) VALUES(?,?,?)", [(bid, a, b) for a, b in rows])


def finish(bid, ok, fail):
    with db.conn() as c:
        c.execute("UPDATE bc SET ok=?, fail=?, state='done' WHERE id=?", (ok, fail, bid))


def recent(n=10):
    ensure()
    with db.conn() as c:
        return c.execute("SELECT * FROM bc ORDER BY id DESC LIMIT ?", (n,)).fetchall()


def get(bid):
    ensure()
    with db.conn() as c:
        return c.execute("SELECT * FROM bc WHERE id=?", (bid,)).fetchone()


def msgs(bid):
    with db.conn() as c:
        return [(r["chat_id"], r["msg_id"]) for r in c.execute("SELECT chat_id,msg_id FROM bc_msgs WHERE bc_id=?", (bid,))]


def set_deleted(bid):
    with db.conn() as c:
        c.execute("UPDATE bc SET deleted=1 WHERE id=?", (bid,))
        c.execute("DELETE FROM bc_msgs WHERE bc_id=?", (bid,))


def set_edited(bid, preview):
    with db.conn() as c:
        c.execute("UPDATE bc SET edited=edited+1, preview=? WHERE id=?", (preview[:200], bid))
