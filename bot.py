import os, io, re, json, time, threading, traceback, html
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
import requests
import db, gateway, panel, secure, bcast

try:
    import segno
except Exception:  # QR is optional
    segno = None

TOKEN = os.getenv("BOT_TOKEN", "")          # can be replaced any time from the website (Bot Token tab)
ADMIN_ID = int(os.getenv("ADMIN_ID", "6739795427") or 0)
API = f"https://api.telegram.org/bot{TOKEN}/"
S = requests.Session()
# V21: big connection pool (default is only 10 -> with many users connections were thrown away / rebuilt = slow)
from requests.adapters import HTTPAdapter
_ad = HTTPAdapter(pool_connections=50, pool_maxsize=200, max_retries=0, pool_block=False)
S.mount("https://", _ad)
S.mount("http://", _ad)
IST = timezone(timedelta(hours=5, minutes=30))
BOT_USERNAME = {"v": ""}
PUBLIC_URL = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")


# ------------------------------------------------------------------ API helpers
def _strip(markup):
    """remove premium-icon / colour fields (fallback if Telegram rejects them)"""
    if not markup:
        return markup
    for row in markup.get("inline_keyboard", []):
        for b in row:
            b.pop("icon_custom_emoji_id", None)
            b.pop("style", None)
    return markup


# V22: background pool for "fire and forget" Telegram calls (answer button, delete old messages ...)
_bg_pool = ThreadPoolExecutor(max_workers=32)


def bg(fn, *a, **k):
    """run fn in the background - the user's screen does not wait for it"""
    def _run():
        try:
            fn(*a, **k)
        except Exception:
            traceback.print_exc()
    try:
        _bg_pool.submit(_run)
    except Exception:
        _run()


def _post(method, p):
    """one Telegram call with smart retry (V22):
    - connection dropped / reset BEFORE Telegram answered -> retry at once (was: the action silently failed)
    - 429 Too Many Requests -> wait the time Telegram asks (max 5s) and retry
    - 5xx from Telegram -> one quick retry"""
    last = None
    for attempt in range(3):
        try:
            r = S.post(API + method, data=p, timeout=(10, 60)).json()
        except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
            last = {"ok": False, "description": str(e)}
            if isinstance(e, requests.exceptions.ReadTimeout):
                return last
            time.sleep(0.15 * (attempt + 1))
            continue
        except Exception as e:
            return {"ok": False, "description": str(e)}
        if not r.get("ok"):
            code = r.get("error_code") or 0
            if code == 429 and attempt < 2:
                wait = (r.get("parameters") or {}).get("retry_after", 1)
                if wait <= 5:
                    time.sleep(wait + 0.1)
                    continue
            if code >= 500 and attempt < 1:
                time.sleep(0.3)
                continue
        return r
    return last or {"ok": False, "description": "network error"}


def api(method, **p):
    if "reply_markup" in p and p["reply_markup"] is not None and not isinstance(p["reply_markup"], str):
        p["reply_markup"] = json.dumps(p["reply_markup"])
    p = {k: v for k, v in p.items() if v is not None}
    r = _post(method, p)
    if not r.get("ok") and "reply_markup" in p and "not modified" not in r.get("description", ""):
        d = r.get("description", "").lower()
        if any(x in d for x in ("emoji", "style", "button", "unsupported", "field")):
            m = _strip(json.loads(p["reply_markup"]))
            p["reply_markup"] = json.dumps(m)
            r = _post(method, p)
    return r


def raw(method, **p):
    """API call WITHOUT the automatic emoji fallback (used for diagnostics)"""
    if "reply_markup" in p and p["reply_markup"] is not None and not isinstance(p["reply_markup"], str):
        p["reply_markup"] = json.dumps(p["reply_markup"])
    p = {k: v for k, v in p.items() if v is not None}
    try:
        return S.post(API + method, data=p, timeout=60).json()
    except Exception as e:
        return {"ok": False, "description": str(e)}


def emoji_invalid(ids):
    """returns the IDs that Telegram says do not exist (empty list if it cannot check)"""
    ids = [i for i in ids if i]
    if not ids:
        return []
    r = raw("getCustomEmojiStickers", custom_emoji_ids=json.dumps(ids[:200]))
    if not r.get("ok"):
        return []
    good = {x.get("custom_emoji_id") for x in r.get("result", [])}
    return [i for i in ids if i not in good]


def emoji_test():
    """Sends ONE test message to the admin with a premium emoji in the text and on a button,
    then checks what Telegram really accepted. Returns (ok, report_text)."""
    with db.conn() as c:
        rows = [(r["k"], r["fallback"], r["eid"]) for r in c.execute("SELECT * FROM emojis WHERE eid<>''")]
    if not rows:
        return False, "No premium emoji ID is saved yet. Add at least one ID in Premium Emoji first."
    if not ADMIN_ID:
        return False, "ADMIN_ID is not set."
    bad = emoji_invalid([r[2] for r in rows])
    good = [r for r in rows if r[2] not in bad]
    out = []
    if bad:
        names = ", ".join(r[0] for r in rows if r[2] in bad)
        out.append(f"Invalid ID (Telegram does not know it): {names}. Send the emoji to the bot again and copy the new ID.")
    if not good:
        return False, "\n".join(out)
    fb, eid = good[0][1], good[0][2]
    kb = {"inline_keyboard": [[{"text": "Premium emoji test", "icon_custom_emoji_id": eid, "callback_data": "noop"}]]}
    r = raw("sendMessage", chat_id=ADMIN_ID, parse_mode="HTML", reply_markup=kb,
            text=f'Premium emoji test <tg-emoji emoji-id="{eid}">{fb}</tg-emoji> (this message deletes itself)')
    if not r.get("ok"):
        why = r.get("description", "")
        if "chat not found" in why.lower() or "blocked" in why.lower() or "forbidden" in why.lower():
            return False, "Could not message the admin. Open the bot with the ADMIN account and send /start first."
        d = why.lower()
        if "emoji" in d or "button" in d or "field" in d:
            db.put("emoji_mode", "blocked")
            db.emoji_clear()
            return False, ("Telegram REJECTED the premium emoji: " + why + "\n" + BLOCKED_HELP)
        return False, "Test failed: " + why
    msg = r["result"]
    text_ok = any(e.get("type") == "custom_emoji" for e in (msg.get("entities") or []))
    btn_ok = any(bt.get("icon_custom_emoji_id") for row in (msg.get("reply_markup") or {}).get("inline_keyboard", []) for bt in row)
    threading.Timer(20, lambda: api("deleteMessage", chat_id=ADMIN_ID, message_id=msg["message_id"])).start()
    if text_ok or btn_ok:
        db.put("emoji_mode", "ok")
        db.emoji_clear()
        out.insert(0, f"Premium emoji WORK. Text: {'yes' if text_ok else 'no'} · Buttons: {'yes' if btn_ok else 'no'}.")
        return True, "\n".join(out)
    db.put("emoji_mode", "blocked")
    db.emoji_clear()
    out.insert(0, "Telegram accepted the message but REMOVED the premium emoji.\n" + BLOCKED_HELP)
    return False, "\n".join(out)


BLOCKED_HELP = ("Reason: Telegram lets a bot show premium emoji only if the account that OWNS the bot "
                "(the account that created it in @BotFather) has Telegram Premium, or the bot has a username bought on Fragment. "
                "Premium on your admin account is not enough when the bot was created by a different account. "
                "Until that is fixed the bot shows normal emoji everywhere, so nothing breaks.")


def send(chat, text, kb=None):
    return api("sendMessage", chat_id=chat, text=text, parse_mode="HTML", reply_markup=kb,
               link_preview_options=json.dumps({"is_disabled": True}))


def show(chat, mid, text, kb=None, photo=False):
    if photo:
        bg(api, "deleteMessage", chat_id=chat, message_id=mid)     # V22: new screen does not wait for the delete
        send(chat, text, kb)
        return
    r = api("editMessageText", chat_id=chat, message_id=mid, text=text, parse_mode="HTML", reply_markup=kb,
            link_preview_options=json.dumps({"is_disabled": True}))
    if not r.get("ok") and "not modified" not in r.get("description", ""):
        send(chat, text, kb)


def esc(x):
    return html.escape(str(x if x is not None else ""))


def api_file(method, files, **p):
    if "reply_markup" in p and p["reply_markup"] is not None and not isinstance(p["reply_markup"], str):
        p["reply_markup"] = json.dumps(p["reply_markup"])
    p = {k: v for k, v in p.items() if v is not None}
    try:
        r = S.post(API + method, data=p, files=files, timeout=60).json()
        if not r.get("ok") and "reply_markup" in p and "emoji" in r.get("description", "").lower() + r.get("description", "").lower():
            p["reply_markup"] = json.dumps(_strip(json.loads(p["reply_markup"])))
            files = {k: (v[0], v[1]) for k, v in files.items()}
            r = S.post(API + method, data=p, files=files, timeout=60).json()
        return r
    except Exception as e:
        return {"ok": False, "description": str(e)}


def fetch_file(file_id):
    r = api("getFile", file_id=file_id)
    path = r.get("result", {}).get("file_path")
    if not path:
        return None
    try:
        return S.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}", timeout=60).content
    except Exception:
        return None


def ans(cq, text=None, alert=False):
    """answer a button tap. V22: only the FIRST answer counts (Telegram ignores the rest anyway),
    and it is sent in the background so the screen change never waits for it."""
    with _ans_lock:
        if cq.get("_answered"):
            return
        cq["_answered"] = True
    bg(api, "answerCallbackQuery", callback_query_id=cq["id"], text=text, show_alert="true" if alert else None)


_ans_lock = threading.Lock()


# ------------------------------------------------------------------ UI helpers
def E(key):
    fb, eid = db.emoji(key)
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>' if eid else fb


def EX(eid, key):
    """premium emoji from a raw ID (product / plan emoji); no ID -> the normal slot `key`"""
    if eid:
        fb, e = db.emoji_direct(eid, db.emoji(key)[0])
        return f'<tg-emoji emoji-id="{e}">{fb}</tg-emoji>' if e else fb
    return E(key)


BTN_STYLES = {"blue": "primary", "green": "success", "red": "danger", "plain": None}


def B(text, cb=None, url=None, style=None, ek=None, eid=None, fb=None):
    """button. eid = raw premium emoji ID (wins over the slot `ek`).
    fb = a normal emoji typed by the admin (e.g. category button): it turns premium by itself when that emoji has a premium ID."""
    if eid:
        f, eid = db.emoji_direct(eid, fb if fb is not None else (db.emoji(ek)[0] if ek else ""))
    elif fb is not None:
        f, eid = fb, db.emoji_map().get(fb.replace("\ufe0f", ""), "")
    else:
        f, eid = db.emoji(ek) if ek else ("", "")
    b = {}
    if eid:
        b["text"] = text
        b["icon_custom_emoji_id"] = eid
    else:
        b["text"] = (f + " " + text).strip()
    if cb:
        b["callback_data"] = cb
    if url:
        b["url"] = url
    mode = db.get_c("btn_color", "auto")
    if mode in BTN_STYLES:          # website Settings -> "Button colour": ONE colour for every button
        style = BTN_STYLES[mode]
    if style:
        b["style"] = style  # primary = blue, success = green, danger = red
    return b


def KB(*rows):
    return {"inline_keyboard": [list(r) for r in rows]}


def back_btn():
    return B("Back to Main", cb="menu", style="danger", ek="back")


def fmt(u, x):
    return f"{u['symbol']}{x:.2f} {u['currency']}"


def ist(ts, f="%b %d · %H:%M IST"):
    return datetime.fromtimestamp(ts, IST).strftime(f)


def link(v, kind):
    v = (v or "").strip()
    if not v:
        return None
    if kind == "tg":
        if v.startswith("http"):
            return v
        if v.lower().startswith(("t.me/", "telegram.me/")):
            return "https://" + v
        return "https://t.me/" + v.lstrip("@")
    if kind == "wa":
        if v.startswith("http"):
            return v
        return "https://wa.me/" + "".join(ch for ch in v if ch.isdigit())
    return v if v.startswith("http") else "https://" + v


# ------------------------------------------------------------------ V12: rich text helpers
_BOLD_UP, _BOLD_LO, _BOLD_DG = 0x1D5D4, 0x1D5EE, 0x1D7EC     # Mathematical Sans-Serif Bold letters
_EMO_RUN = "[\u2190-\u2BFF\u2600-\u27BF\U0001F000-\U0001FAFF\uFE0F\u200D]"
_TOK = re.compile("(" + _EMO_RUN + "{1,8})?\\{(\\d{6,25})\\}")


def deep(text):
    """extra-heavy bold title: normal <b> looks thin on capital letters, these letters are drawn much thicker.
    Website Settings -> 'Deep bold titles' can switch it off."""
    text = str(text if text is not None else "")
    if db.get_c("deep_bold", "1") == "0":
        return f"<b>{esc(text)}</b>"
    out = []
    for ch in text:
        o = ord(ch)
        if "A" <= ch <= "Z":
            out.append(chr(_BOLD_UP + o - 65))
        elif "a" <= ch <= "z":
            out.append(chr(_BOLD_LO + o - 97))
        elif "0" <= ch <= "9":
            out.append(chr(_BOLD_DG + o - 48))
        else:
            out.append(ch)
    return "<b>" + esc("".join(out)) + "</b>"


def _tg(fb, eid):
    f, e = db.emoji_direct(eid, fb)
    return f'<tg-emoji emoji-id="{e}">{f}</tg-emoji>' if e else f


def _auto_emoji(s):
    mp = db.emoji_map()
    if not mp:
        return esc(s)
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        eid = mp.get(ch)
        if eid:
            j = i + 1
            if j < len(s) and s[j] == "\ufe0f":
                j += 1
            out.append(_tg(s[i:j], eid))
            i = j
        else:
            out.append(esc(ch))
            i += 1
    return "".join(out)


def rich(text):
    """admin-written text -> Telegram HTML with premium emoji.
    1) a normal emoji that has a premium ID (main.py PREMIUM_EMOJI) becomes premium automatically
    2) 🔥{6141106778563158041}  (emoji + {premium ID}) shows exactly that premium emoji"""
    text = text or ""
    res, last = [], 0
    for m in _TOK.finditer(text):
        res.append(_auto_emoji(text[last:m.start()]))
        res.append(_tg(m.group(1) or "⭐", m.group(2)))
        last = m.end()
    res.append(_auto_emoji(text[last:]))
    return "".join(res)


# ------------------------------------------------------------------ screens
def menu_screen(u):
    name = db.get("shop_name", "RG CHEAT SHOP")
    text = (
        f"{E('top')} ━━ {deep(name)} ━━ {E('top')}\n\n"
        f"{E('party')} Welcome back, <b><i>{esc(u['name'])}</i></b>\n\n"
        f"{E('bars')} ━ <b>STORE HIGHLIGHTS</b> ━ {E('bars')}\n\n"
        f"┃ {E('key')} Premium Game Keys\n"
        f"┃ {E('fire')} Instant Delivery 24/7\n"
        f"┃ {E('shield')} 100% Secure Payments\n"
        f"┃ {E('gift')} VIP Rewards &amp; Discounts\n"
        f"┃ {E('h24')} 24/7 Support &amp; Instant Solution\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E('tap')} <b>Tap Product Store Now to Start!</b>"
    )
    upd = link(db.get("update_url"), "url")
    row_upd = B("All Update File", url=upd, style="success", ek="b_update") if upd else \
        B("All Update File", cb="noupd", style="success", ek="b_update")
    kb = KB(
        [B("Shop Now", cb="shop", style="primary", ek="b_shop")],
        [B("Add Balance", cb="addbal", style="success", ek="b_addbal"), B("All History", cb="hist", style="success", ek="b_history")],
        [B("My Profile", cb="profile", style="success", ek="b_profile"), B("Referral", cb="ref", style="success", ek="b_referral")],
        [B("Tutorial", cb="tut", style="success", ek="b_tutorial"), row_upd],
        [B("Support", cb="sup", style="success", ek="b_support")],
    )
    return text, kb


def send_menu(chat, u):
    t, k = menu_screen(u)
    return send(chat, t, k)


def _msg_id(r):
    """message_id from a sendMessage answer (None if it failed)"""
    try:
        return r["result"]["message_id"] if r and r.get("ok") else None
    except Exception:
        return None


# ---------------------------------------------------------------- V19: product deep links
DEEP = {}      # user id -> product id waiting for phone verification (link opened by a not-yet-verified user)


def product_link(pid):
    """every product has its own link: https://t.me/<bot>?start=p_<product id>  (made automatically, old + new products)"""
    un = (BOT_USERNAME.get("v") or "").lstrip("@")
    return f"https://t.me/{un}?start=p_{int(pid)}" if un else ""


def open_product(chat, u, pid, start_mid=None):
    """product link tapped -> that product's screen opens directly (no searching in the shop)"""
    p = db.product(pid)
    if not p or not p["active"]:
        start_flow(chat, u, start_mid)               # product deleted / hidden -> normal main menu
        return
    t, k = prod_screen(u, pid)
    r = send(chat, t, k)
    if start_mid and _msg_id(r):
        bg(api, "deleteMessage", chat_id=chat, message_id=start_mid)


def start_flow(chat, u, start_mid=None):
    """/start: a small 'Welcome' appears first, the main menu follows at once,
    and as soon as the menu is on screen the Welcome message AND the user's own /start message are deleted."""
    wid = _msg_id(send(chat, f"<b>Welcome</b>{E('party')}"))
    r = send_menu(chat, u)
    if _msg_id(r):                                   # menu is visible -> clean up (in the background, V22)
        if wid:
            bg(api, "deleteMessage", chat_id=chat, message_id=wid)
        if start_mid:
            bg(api, "deleteMessage", chat_id=chat, message_id=start_mid)


def addbal_screen(u):
    amt = db.kp_get(u["id"])
    mn, mx = int(db.get("min_dep", "1")), int(db.get("max_dep", "10000"))
    sym, cur = u["symbol"], u["currency"]
    text = (
        f"{E('money')} ━━━ <b>ADD BALANCE TO WALLET</b> ━━━\n\n"
        f"{E('wallet')} Current balance : <b>{fmt(u, u['balance'])}</b>\n\n"
        f"{E('chart')} Minimum Deposit : <b>{sym}{mn:,} {cur}</b>\n\n"
        f"{E('bars')} Maximum Deposit : <b>{sym}{mx:,}</b>\n\n\n"
        f"{E('money')} Amount: <b>{sym}{amt or 0} {cur}</b>\n\n\n"
        f"{E('tap')} <i>Use the keypad below to enter amount</i>"
    )
    d = lambda n: B(str(n), cb=f"kp:{n}", style="primary")
    kb = KB(
        [d(1), d(2), d(3)], [d(4), d(5), d(6)], [d(7), d(8), d(9)],
        [B("Cancel", cb="kp:c", style="danger", ek="cancel"), d(0), B("Confirm", cb="kp:ok", style="success", ek="confirm")],
        [back_btn()],
    )
    return text, kb


def history_screen(u):
    n, spent, dep = db.stats(u["id"])
    since = int(time.time()) - 3 * 86400
    recent = db.orders(u["id"], since)
    text = (
        f"{E('tap')} <b>ALL HISTORY</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"├── {E('diamond')} Total spent: <b>{u['symbol']}{spent:.2f} {u['currency']}</b>\n"
        f"└── {E('shield')} Total deposited: <b>{u['symbol']}{dep:.2f} {u['currency']}</b>\n\n"
        f"{E('cart')} <b>Recent Orders</b>\n━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    for o in recent[:5]:
        text += (
            f"{E('check')} <code>{o['order_no']}</code>\n"
            f"├── {E('cart')} {esc(o['product'])} · {esc(o['plan'])}\n"
            f"├── {E('money')} {u['symbol']}{o['price']:.2f} {u['currency']}\n"
            f"├── {E('time')} {ist(o['created'])}\n"
            f"└── {E('key')} <code>{esc(o['key'])}</code>\n\n"
        )
    if not recent:
        text += "<i>No orders in the last 3 days.</i>\n\n"
    older = n - len(recent[:5])
    if n:
        text += f"{E('info')} <i>Showing your latest orders from the last 3 days. {max(older,0)} older order(s) are in the full file — tap</i> {E('download')} <b>Download All Keys</b>."
    kb = KB([B("Download All Keys", cb="dl", style="success", ek="download")], [back_btn()])
    return text, kb


def refund_line(u):
    h = db.hold_of(u)
    return f"├── {E('wait')} Refund (needs approval): {fmt(u, h)}\n\n" if h > 0 else ""


def profile_screen(u):
    n, spent, _ = db.stats(u["id"])
    role = "Reseller" if u["role"] == "reseller" else "Standard User"
    text = (
        f"{E('user')} <b>MY PROFILE</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"├── {E('check')} ID: <code>{u['id']}</code>\n\n"
        f"├── {E('fire2')} Name: <b><i>{esc(u['name'])}</i></b>\n\n"
        f"├── {E('phone')} Phone: {u['phone'] or '-'}\n\n"
        f"├── {E('globe')} Country: {u['country']}\n\n"
        f"├── {E('wallet')} Balance: {fmt(u, u['balance'])}\n\n"
        f"{refund_line(u)}"
        f"├── {E('gift2')} Ref Balance: {fmt(u, u['ref_balance'])}\n\n"
        f"├── {E('cart')} Orders: {n}\n\n"
        f"├── {E('diamond')} Lifetime spent: {fmt(u, spent)}\n\n"
        f"└── {E('calendar')} Joined: {ist(u['joined'], '%Y-%m-%d')} IST\n\n"
        f"{E('user')} {role}"
    )
    rows = []
    try:
        if u["api_on"] and PUBLIC_URL.startswith("https://"):          # V20: RGAPI System button (only when the owner switched it ON)
            rows.append([{"text": "🔑 RGAPI System", "web_app": {"url": PUBLIC_URL + "/rgapi/login"}, "style": "primary"}])
    except (KeyError, IndexError):
        pass
    rows.append([back_btn()])
    return text, KB(*rows)


def ref_screen(u):
    lk = f"https://t.me/{BOT_USERNAME['v']}?start=ref_{u['id']}"
    text = (
        f"{E('r_title')} <b>Referral Program</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        f"Status: Active 🟢\n\n"
        f"{E('r_money')} Earn exclusive commissions on referred purchases! ⭐\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{E('r_invite')} <b>Your Invite Link:</b>\n<code>{lk}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E('r_send')} <b>Share your link to grow your earnings!</b>"
    )
    share = f"https://t.me/share/url?url={quote(lk)}&text={quote('Best game keys store! Join here:')}"
    rows = [[B("Send Link", url=share, style="success", ek="r_send")]]
    if u["ref_balance"] > 0:
        rows.append([B(f"Claim {fmt(u, u['ref_balance'])} to wallet", cb="claim", style="primary", ek="gift2")])
    rows.append([back_btn()])
    return text, KB(*rows)


def tut_screen(u):
    text = (
        f"{E('t_title')} ━ <b>VIDEO TUTORIALS</b> ━ {E('t_title')}\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E('t_title')} <b>Learn How To Use Our Products</b>\n\n"
        f"├ {E('fire')} Step-By-Step Guides\n├ {E('key')} Game Setup Tutorials\n"
        f"├ {E('support')} Installation Help\n└ ⭐ Tips &amp; Tricks\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n{E('tap')} <b>Click Any Tutorial Below:</b>"
    )
    rows = []
    v = link(db.get("tutorial_url"), "url")
    if v:
        rows.append([B("Watch Guide Video", url=v, style="primary", ek="t_watch")])
    rows.append([back_btn()])
    return text, KB(*rows)


def sup_screen(u):
    text = (
        f"{E('h24')} <b>Support Team</b>\n{E('tap')} Our team is here to help you.\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{E('user')} <b>We can assist with:</b>\n\n"
        f"— {E('fire')} Orders &amp; key delivery\n— {E('money')} Payments &amp; balance\n"
        f"— {E('info')} Product questions\n— {E('fire')} Any other issue\n\n"
        f"If you face any issues or have questions regarding our services, feel free to contact our expert team.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n<b>Click the button below to start a chat</b> {E('tap')}"
    )
    rows = []
    if db.get("support_tg_on") == "1" and link(db.get("support_tg"), "tg"):
        rows.append([B("Chat on Telegram", url=link(db.get("support_tg"), "tg"), style="success", ek="telegram")])
    if db.get("support_wa_on") == "1" and link(db.get("support_wa"), "wa"):
        rows.append([B("Chat on WhatsApp", url=link(db.get("support_wa"), "wa"), style="success", ek="whatsapp")])
    if not rows:
        text += "\n\n<i>Support is currently unavailable.</i>"
    rows.append([back_btn()])
    return text, KB(*rows)



LINE = "━━━━━━━━━━━━━━━━━━━━"


def rs(x):
    """₹90.9 / ₹100 / ₹270.9"""
    return "₹" + f"{x:.2f}".rstrip("0").rstrip(".")


def role_name(u):
    return "Reseller" if u["role"] == "reseller" else "User"


def shop_entry(u):
    """Shop Now: category list when you made categories, else the product list (like before)"""
    return cats_screen(u) if db.cats() else shop_screen(u)


def cats_screen(u):
    """screen 'Choose Your Device Category' - one button per category (Website -> Categories)"""
    shop = db.get("shop_name", "SHOP")
    title = (db.get("cat_title") or "").strip() or shop
    text = f"{LINE}\n{E('cart')} {deep(title)} {E('cart')}\n{LINE}\n\n"
    lines = [rich(x.strip()) for x in db.get("cat_text").splitlines() if x.strip()]
    if lines:
        text += "\n\n".join(lines) + "\n"
    rows = []
    for c in db.cats():
        rows.append([B(c["name"], cb=f"cat:{c['id']}", style="primary", ek="cart", eid=(c["eid"] or "").strip() or None,
                       fb=(c["emoji"] or "").strip() if (c["emoji"] or (c["eid"] or "").strip()) else None)])
    if db.products(True, 0):
        rows.append([B(db.get("cat_other_name") or "OTHER PRODUCTS", cb="cat:0", style="primary", ek="cart")])
    rows.append([back_btn()])
    return text, KB(*rows)


def shop_screen(u, cid=None):
    """product list. cid=None -> all products; cid=N -> products of category N; cid=0 -> products without category"""
    cname = ""
    if cid:
        c = db.cat(cid)
        cname = c["name"] if c else ""
    elif cid == 0:
        cname = db.get("cat_other_name") or "OTHER PRODUCTS"
    text = f"{E('cart')} {deep(db.get('shop_name', 'SHOP'))}\n{LINE}\n\n{E('lineup')} <b>Product Lineup</b>"
    text += (f" · <b>{esc(cname)}</b>\n\n" if cname else "\n\n")
    bl = [f"➳ {rich(x.strip())}" for x in db.get("shop_bullets").splitlines() if x.strip()]
    if bl:
        text += "\n".join(bl) + "\n\n"
    rows = []
    prods = db.products(True, cid)
    for p in prods:
        tag = "" if p["stock"] else " · Out of Stock"
        rows.append([B(p["name"] + tag, cb=f"p:{p['id']}", style="primary", ek="cart", eid=db.product_eid(p))])
    text += (f"{E('shield')} <b>Pick what you want</b> {E('tap')}\nTap any product to see options." if prods
             else "<i>No products available yet.</i>")
    rows.append([B("BACK", cb="shop", style="danger", ek="back")] if cid is not None else [back_btn()])
    return text, KB(*rows)


def prod_screen(u, pid):
    p = db.product(pid)
    if not p or not p["active"]:
        return shop_entry(u)
    text = (f"<blockquote>{EX(db.product_eid(p), 'cart')} <b>{esc(p['name'])}</b></blockquote>\n\n"
            f"<blockquote>{E('crown')} Account Type: <b>{role_name(u)}</b></blockquote>\n\n"
            f"<blockquote>{E('chart')} <b>See Current Plans &amp; Pricing</b></blockquote>\n\n")
    if p["descr"]:
        text += f"{esc(p['descr'])}\n\n"
    plans = db.plans_of(pid)
    pe = db.plans_eid()      # ONE premium emoji for every plan (empty = normal emoji)
    rows = []
    for n, pl in enumerate(plans):
        price = db.price_for(u, pl)
        br = "└──" if n == len(plans) - 1 else "├──"
        text += f"{br} {EX(pe, 'time')} {esc(pl['name'])} ➝ {E('money')} {rs(price)}{'' if pl['stock'] > 0 else ' ❌ (Out of Stock)'}\n"
        if pl["stock"] > 0:
            rows.append([B(f"Buy {pl['name']} · {rs(price)}", cb=f"pl:{pl['id']}", style="success", ek="key", eid=pe)])
        else:
            rows.append([B(f"{pl['name']} · Out of Stock", cb="oos", style="danger")])
    if plans:
        text += f"\n{E('tap')} <b>CHOOSE A PLAN</b> {E('tap')}"
    else:
        text += "<i>No plans available yet.</i>"
    back = f"cat:{int(p['cat_id'] or 0)}" if db.cats() else "shop"
    rows.append([B("BACK", cb=back, style="danger", ek="back")])
    return text, KB(*rows)


def method_err(u, m):
    """None if the payment method can be used by this user, else a message"""
    if m == "upi":
        if u["currency"] != "INR" or db.get("pay_upi_on") != "1" or not db.get("upi_id").strip():
            return "UPI payment is not available right now."
    elif m == "binance":
        if db.get("pay_binance_on") != "1" or not db.get("binance_text").strip():
            return "Binance payment is not available right now."
    elif m == "other":
        if u["currency"] == "INR" or not db.get("pay_other_text").strip():
            return "This payment method is not available right now."
    return None


def methods_for(u):
    """[(label, key, emoji_key)] key: q=gateway QR, u=UPI/local manual, b=Binance manual"""
    out = []
    if u["currency"] == "INR" and gateway.configured():
        out.append(("Pay QR", "q", "qr"))
    if not method_err(u, "upi"):
        out.append(("Pay UPI", "u", "upi"))
    elif not method_err(u, "other"):
        out.append(("Pay Local", "u", "local"))
    if not method_err(u, "binance"):
        out.append(("Pay Binance", "b", "binance"))
    return out


def topup_methods_screen(u, amt):
    text = (f"<blockquote>{E('money')} <b>ADD BALANCE</b></blockquote>\n{LINE}\n\n"
            f"➛ {E('wallet')} Add to wallet: <b>{rs(float(amt))} INR</b>\n\n"
            f"{E('tap')} <b>Pick how you want to pay:</b>")
    rows = [[B(f"Pay via UPI — {rs(float(amt))} INR", cb=f"tq:{amt}", style="primary", ek="upi")],
            [B(f"Pay via Binance — ${usd_of(u, float(amt)):.2f} USDT", cb=f"tb:{amt}", style="primary", ek="binance")],
            [B("BACK", cb="addbal", style="danger", ek="back")]]
    return text, KB(*rows)


def phone_txt(u):
    return ("+" + u["phone"]) if u["phone"] else "-"


def plan_screen(u, plid):
    pl = db.plan(plid)
    if not pl or not pl["pactive"] or not pl["active"]:
        return shop_entry(u)
    code = db.cp_get(u["id"], plid)
    final, disc, err = db.coupon_calc(u, pl, code)
    if err:
        db.cp_set(u["id"], 0, "")
        code = ""
    base = db.price_for(u, pl)
    text = (f"<blockquote>{E('receipt')} <b>CHECKOUT SUMMARY</b></blockquote>\n{LINE}\n\n"
            f"➛ {E('user')} Name: <b>{esc(u['name'])}</b>\n"
            f"➛ {E('idcard')} User ID: <code>{u['id']}</code>\n")
    if u["phone"]:
        text += f"➛ {E('phone')} Phone: <code>{esc(phone_txt(u))}</code>\n"
    text += (f"➛ {E('key')} Product: {esc(pl['pname'])}\n"
             f"➛ {E('time')} Plan: {esc(pl['name'])}\n"
             f"➛ {E('cart')} Quantity: 1\n"
             f"➛ {E('money')} Price: {fmt(u, base)} each\n")
    if code:
        text += f"➛ {E('coupon')} Coupon: <code>{esc(code)}</code> (-{fmt(u, disc)})\n"
    text += (f"\n{E('money')} <b>Final Total: {fmt(u, final)}</b>\n"
             f"{E('wallet')} Wallet Balance: <b>{fmt(u, u['balance'])}</b>\n\n")
    rows = []
    if pl["stock"] <= 0:
        text += "<i>❌ This plan is Out of Stock right now.</i>"
    else:
        text += (f"{E('tap')} <b>Pick how you want to pay:</b>\n"
                 f"Pick any option below. If you have wallet balance, you can pay instantly.")
        rows.append([B("Pay via Wallet", cb=f"buy:{plid}", style="primary", ek="bag")])
        rows.append([B(f"Pay via UPI — {fmt(u, final)}", cb=f"pq:{plid}", style="primary", ek="upi")])
        rows.append([B(f"Pay via Binance — ${usd_of(u, final):.2f} USDT", cb=f"pb:{plid}", style="primary", ek="binance")])
        rows.append([B("Apply Coupon Code", cb=f"cp:{plid}", style="primary", ek="coupon")])
    rows.append([B("BACK", cb=f"p:{pl['product_id']}", style="danger", ek="back")])
    return text, KB(*rows)


def menu_btn():
    return B("Back to Main Menu", cb="menu", style="danger", ek="home")


def after_buy_rows(plan_id):
    """Join Telegram (the product's update group) + Main Panel"""
    rows = []
    url = link(db.plan_link(plan_id), "tg")
    if url:
        rows.append([B("Join Update Group", url=url, style="danger", ek="telegram")])
    rows.append([menu_btn()])
    return rows


def delivery_text(u, o, method, title):
    return (
        f"{E('money')} <b>{title}</b> ✨\n<i>Instant Key Delivery!</i>\n\n"
        f"{E('receipt')} <b>ORDER DETAILS</b>\n"
        f"├── {E('user')} <b>User ID:</b>{u['id']}\n\n"
        f"├── {E('shield')} <b>Order ID:</b><code>{o['order_no']}</code>\n\n"
        f"├── {E('cart')} <b>Product ID:</b>{esc(o['product'])}\n\n"
        f"├── {E('cart')} <b>Product:</b>{esc(o['product'])}\n\n"
        f"├── {E('time')} <b>Plan:</b>{esc(o['plan'])}\n\n"
        f"├── {E('paid')} <b>Method:</b>{method}\n\n"
        f"└── {E('money')} <b>Paid:</b>{fmt(u, o['price'])}\n\n"
        f"{E('key')} <b>YOUR KEY:</b><code>{esc(o['key'])}</code>\n\n"
        f"{E('info')} <i>Tap the key above to copy instantly.</i>"
    )


def order_screen(u, o):
    return confirm_purchase_text(u, o), KB(*after_buy_rows(o.get("plan_id", 0)))


def send_payment(chat, mid, u, dep_id, amt):
    api("deleteMessage", chat_id=chat, message_id=mid)
    kb = KB([B("I Have Paid", cb=f"dp:{dep_id}", style="success", ek="paid")],
            [B("Cancel", cb=f"dc:{dep_id}", style="danger", ek="cancel")])
    upi = db.get("upi_id").strip()
    amount_txt = fmt(u, amt)
    if u["currency"] == "INR" and upi:
        uri = (f"upi://pay?pa={quote(upi, safe='@.-_')}&pn={quote(db.get('upi_name') or 'Shop')}"
               f"&am={amt:.2f}&cu=INR&tn={quote('RG' + str(dep_id))}")
        cap = (f"{E('qr')} <b>PAY VIA UPI</b>\n━━━━━━━━━━━━━━━━━━━━\n"
               f"{E('money')} Amount: <b>{amount_txt}</b>\n"
               f"{E('check')} UPI ID: <code>{esc(upi)}</code>\n"
               f"{E('chart')} Deposit ID: <code>#{dep_id}</code>\n\n"
               f"1️⃣ Scan the QR or pay the <b>exact amount</b>.\n"
               f"2️⃣ Tap <b>I Have Paid</b>, then send your UTR / Transaction ID or a screenshot.")
        if segno:
            try:
                buf = io.BytesIO()
                segno.make(uri, error="m").save(buf, kind="png", scale=8, border=3)
                r = api_file("sendPhoto", {"photo": ("qr.png", buf.getvalue())}, chat_id=chat,
                             caption=cap, parse_mode="HTML", reply_markup=kb)
                if r.get("ok"):
                    return
            except Exception:
                traceback.print_exc()
        send(chat, cap, kb)
        return
    other = db.get("pay_other_text").strip()
    if not other:
        send(chat, "⚠️ Payment method is not set for your country yet. Please contact support.", KB([back_btn()]))
        return
    send(chat, f"{E('paid')} <b>PAYMENT DETAILS</b>\n━━━━━━━━━━━━━━━━━━━━\n"
               f"{E('money')} Amount: <b>{amount_txt}</b>\n{E('chart')} Deposit ID: <code>#{dep_id}</code>\n\n"
               f"{esc(other)}\n\nAfter paying tap <b>I Have Paid</b> and send your transaction ID or screenshot.", kb)


def page_url(pay):
    return f"{PUBLIC_URL}/pay/{pay['token']}" if PUBLIC_URL else ""


def own_upi_uri(amt, pay_no):
    upi = db.get("upi_id").strip()
    if not upi:
        return ""
    return (f"upi://pay?pa={quote(upi, safe='@.-_')}&pn={quote(db.get('upi_name') or 'Shop')}"
            f"&am={amt:.2f}&cu=INR&tn={quote(pay_no)}")


def qr_png(data):
    if not segno or not data:
        return None
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=8, border=3)
    return buf.getvalue()


def pay_caption(pay, u):
    exp = int(db.get("pay_expire", "10") or 10)
    topay = pay["pay_amount"] or pay["amount"]
    return (f"{LINE}\n{E('money')} <b>UPI PAYMENT GATEWAY</b>\n{LINE}\n\n"
            f"➛ {E('money')} Amount: <b>{fmt(u, topay)}</b>\n"
            f"➛ {E('ban')} Order: <code>{pay['pay_no']}</code>\n\n"
            f"➛ {E('time')} Expires in {exp} minutes\n"
            f"➛ {E('fire2')} Instant Verification\n\n"
            f"<b>How to pay</b>\n"
            f"➛ Scan the QR code below to pay.\n"
            f"➛ Your payment will be verified automatically!")


def send_pay_msg(chat, mid, u, pay):
    if mid:
        api("deleteMessage", chat_id=chat, message_id=mid)
    kb = KB([B("Back to Store", cb="menu", style="danger", ek="home")])
    cap = pay_caption(pay, u)
    png = None
    try:
        png = qr_png(pay["upi_uri"] or pay["pay_url"])
    except Exception:
        traceback.print_exc()
    r = None
    if png:
        r = api_file("sendPhoto", {"photo": ("qr.png", png)}, chat_id=chat, caption=cap, parse_mode="HTML", reply_markup=kb)
    if not r or not r.get("ok"):
        r = send(chat, cap + (f"\n\n{esc(pay['pay_url'])}" if pay["pay_url"] else ""), kb)
    try:
        db.pay_update(pay["pay_no"], chat_id=chat, msg_id=r["result"]["message_id"])
    except Exception:
        pass


def start_qr(chat, mid, u, kind, amount, plid, code, title):
    """create the order on the gateway and show the QR"""
    pay = db.pay_create(u["id"], kind, amount, plid, code, title)
    hook = f"{PUBLIC_URL}/webhook/gateway" if PUBLIC_URL else ""
    res = gateway.create(pay["pay_no"], amount, u, page_url(pay), hook)
    if not res["ok"]:
        db.pay_update(pay["pay_no"], status="cancelled")
        send(chat, f"⚠️ <b>Could not start payment.</b>\n<i>{esc(res['err'])}</i>\nPlease try again or contact support.",
             KB([back_btn()]))
        return
    uri = res["upi_uri"]
    db.pay_update(pay["pay_no"], upi_uri=uri, pay_url=res["pay_url"], gw_ref=res["ref"], pay_amount=res["pay_amount"])
    send_pay_msg(chat, mid, u, db.pay_get(pay["pay_no"]))


def usd_of(u, amount):
    return max(round(amount / db.rate(u["currency"]) * db.rate("USD"), 2), 0.01)


def start_manual(chat, mid, u, method, kind, amount, plid, code, title):
    """manual payment (UPI / Binance / local): user pays, then sends the transaction ID to the admin"""
    pay = db.pay_create(u["id"], kind, amount, plid, code, title, method)
    no = pay["pay_no"]
    if mid:
        api("deleteMessage", chat_id=chat, message_id=mid)
    head = {"upi": "PAY VIA UPI", "binance": "PAY VIA BINANCE", "other": "PAYMENT DETAILS"}[method]
    text = (f"{E('qr') if method == 'upi' else E('paid')} <b>{head}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"├── {E('receipt')} Order ID: <code>{no}</code>\n├── {E('key')} {esc(title)}\n")
    png = None
    if method == "upi":
        uri = own_upi_uri(amount, no)
        db.pay_update(no, upi_uri=uri)
        text += (f"├── {E('money')} Amount: <b>{fmt(u, amount)}</b>\n└── {E('check')} UPI ID: <code>{esc(db.get('upi_id').strip())}</code>\n\n"
                 f"1️⃣ Scan the QR or pay the <b>exact amount</b> to the UPI ID.\n"
                 f"2️⃣ Tap <b>I Have Paid</b>, then send your <b>UTR / Transaction ID</b> (or a screenshot).")
        try:
            png = qr_png(uri)
        except Exception:
            traceback.print_exc()
    elif method == "binance":
        text += (f"└── {E('money')} Amount: <b>{fmt(u, amount)}</b> ≈ <b>${usd_of(u, amount):.2f} USDT</b>\n\n"
                 f"{esc(db.get('binance_text'))}\n\n"
                 f"1️⃣ Pay on Binance.\n2️⃣ Tap <b>I Have Paid</b> and send the Binance <b>Order ID / Transaction ID</b> you get after paying.")
    else:
        text += (f"└── {E('money')} Amount: <b>{fmt(u, amount)}</b>\n\n{esc(db.get('pay_other_text'))}\n\n"
                 f"After paying tap <b>I Have Paid</b> and send your transaction ID or screenshot.")
    kb = KB([B("I Have Paid", cb=f"pm:{no}", style="success", ek="paid")],
            [B("Cancel", cb=f"pc:{no}", style="danger", ek="cancel")])
    r = None
    if png:
        r = api_file("sendPhoto", {"photo": ("qr.png", png)}, chat_id=chat, caption=text, parse_mode="HTML", reply_markup=kb)
    if not r or not r.get("ok"):
        r = send(chat, text, kb)
    try:
        db.pay_update(no, chat_id=chat, msg_id=r["result"]["message_id"])
    except Exception:
        pass


def notify_admin_pay(p, u):
    if not ADMIN_ID:
        return
    what = "Wallet top-up" if p["kind"] == "topup" else p["title"]
    extra = f"\nBinance amount: <b>${usd_of(u, p['amount']):.2f}</b>" if p["method"] == "binance" else ""
    text = (f"{E('wait')} <b>New {esc(p['method'].upper())} payment</b>\n"
            f"Order: <code>{p['pay_no']}</code>\nUser: <code>{u['id']}</code> {esc(u['name'])}\n"
            f"For: <b>{esc(what)}</b>\nAmount: <b>{fmt(u, p['amount'])}</b>{extra}\n"
            f"Transaction ID: <code>{esc(p['txn'] or '-')}</code>")
    kb = KB([B("Approve", cb=f"ma:{p['pay_no']}", style="success", ek="confirm"),
             B("Reject", cb=f"mr:{p['pay_no']}", style="danger", ek="cancel")])
    if p["proof"]:
        r = api("sendPhoto", chat_id=ADMIN_ID, photo=p["proof"], caption=text, parse_mode="HTML", reply_markup=kb)
        if r.get("ok"):
            return
    send(ADMIN_ID, text, kb)


def reject_pay(no):
    p = db.pay_reject(no)
    if not p:
        return None
    u = db.user(p["user_id"])
    if p["chat_id"] and p["msg_id"]:
        api("deleteMessage", chat_id=p["chat_id"], message_id=p["msg_id"])
    if u:
        send(u["id"], f"❌ <b>Payment {p['pay_no']} was rejected.</b>\nIf you really paid, contact support with your payment proof.")
    return p


# ------------------------------------------------------------------ V9: user confirmations + admin notifications
def g(r, k, d=""):
    """safe field read for sqlite rows AND plain dicts"""
    try:
        v = r[k]
    except (KeyError, IndexError):
        return d
    return d if v is None else v


def safe(fn, *a, **k):
    """a notification must NEVER break a purchase"""
    try:
        return fn(*a, **k)
    except Exception:
        traceback.print_exc()


def divider():
    _fb, eid = db.emoji("c_line")
    if eid:
        return "".join(f'<tg-emoji emoji-id="{eid}">➖</tg-emoji>' for _ in range(10))
    return "━" * 18


def now_ist():
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")


def money_sym(u, x):
    return f"{g(u, 'symbol', '₹')}{float(x):.2f}"


def method_label(m):
    return {"qr": "UPI (Auto QR)", "upi": "UPI (Manual)", "binance": "Binance", "other": "Local Payment"}.get(m, "UPI")


def kv(key, label, val):
    return f"{E(key)} <b>{label}:</b> {val}"


def tree(lines):
    return "\n".join(("└── " if i == len(lines) - 1 else "├── ") + ln for i, ln in enumerate(lines))


def code(x):
    return f"<code>{esc(x)}</code>"


def uname_txt(u):
    un = g(u, "username")
    return ("@" + esc(un)) if un else "-"


def admin_send(text, kb=None):
    """admin notification -> Settings 'notify chat' (a group / channel) or the admin"""
    chat = ADMIN_ID
    v = db.get("notify_chat").strip()
    if v.lstrip("-").isdigit():
        chat = int(v)
    if not chat:
        return
    r = send(chat, text, kb)
    if not r.get("ok") and kb:
        r = send(chat, text)
    if not r.get("ok") and ADMIN_ID and chat != ADMIN_ID:
        send(ADMIN_ID, text)


def contact_kb(u):
    un, uid = g(u, "username"), g(u, "id")
    url = f"https://t.me/{un}" if un else f"tg://user?id={uid}"
    return KB([B("Contact User", url=url, style="primary", ek="n_user")])


def confirm_purchase_text(u, o):
    """what the USER gets after buying a key (wallet / UPI / Binance)"""
    ts = o["created"]
    return (
        f"{E('c_title')} <b>Purchase Confirmed</b> ✨\n{divider()}\n"
        f"{E('c_details')} <b>Order Details</b> {E('c_point')}\n\n"
        f"┣ {E('c_order')} Order ID: <code>{esc(o['order_no'])}</code>\n"
        f"┣ {E('c_product')} Product: <b>{esc(o['product'])}</b>\n"
        f"┣ {E('c_plan')} Plan: <b>{esc(o['plan'])}</b>\n"
        f"┣ {E('c_date')} Date: {ist(ts, '%Y-%m-%d')}\n"
        f"┣ {E('c_time')} Time: {ist(ts, '%I:%M %p')}\n"
        f"┣ {E('c_amount')} Amount: <b>{money_sym(u, o['price'])}</b>\n"
        f"┗ {E('c_status')} Payment Status: {E('c_ok')} <b>Successful</b>\n\n"
        f"{E('c_key')} <b>Your License Key</b> {E('c_point')}\n\n"
        f"{E('c_arrow')} <code>{esc(o['key'])}</code>\n\n"
        f"{divider()}\n"
        f"{E('c_shield')} <i>We appreciate your trust. Enjoy your purchase!</i> {E('c_rocket')}"
    )


def confirm_topup_text(u, amount, order_id, new_bal):
    """what the USER gets after adding wallet balance"""
    ts = int(time.time())
    return (
        f"{E('c_title')} <b>Payment Confirmed</b> ✨\n{divider()}\n"
        f"{E('c_details')} <b>Order Details</b> {E('c_point')}\n\n"
        f"┣ {E('c_order')} Order ID: <code>{esc(order_id)}</code>\n"
        f"┣ {E('c_date')} Date: {ist(ts, '%Y-%m-%d')}\n"
        f"┣ {E('c_time')} Time: {ist(ts, '%I:%M %p')}\n"
        f"┣ {E('c_amount')} Amount: <b>{money_sym(u, amount)}</b>\n"
        f"┗ {E('c_status')} Payment Status: {E('c_ok')} <b>Successful</b>\n\n"
        f"{E('c_addbal')} <b>Add Wallet Balance:</b> {money_sym(u, amount)}\n\n"
        f"{E('c_curbal')} <b>Current Balance:</b> {money_sym(u, new_bal)}\n"
        f"{divider()}\n"
        f"{E('c_ok')} <b>Balance added successfully!</b>\n"
        f"{E('c_shield')} <i>We appreciate your trust. Enjoy your purchase!</i> {E('c_rocket')}"
    )


def notify_purchase(u, o, method, force=False):
    """admin: a user / reseller bought a key"""
    if not force and db.get("notify_purchase") == "0":
        return
    cust = tree([
        kv("n_user", "User", f"<b>{esc(g(u, 'name'))}</b>"),
        kv("n_link", "Username", uname_txt(u)),
        kv("n_id", "Telegram ID", code(g(u, "id"))),
        kv("n_phone", "Phone", code(phone_txt(u))),
        kv("n_globe", "Country", esc(g(u, "country") or "-")),
        kv("n_type", "Account Type", f"<b>{role_name(u)}</b>"),
    ])
    order = tree([
        kv("n_game", "Hack Purchased", f"<b>{esc(o['product'])}</b>"),
        kv("n_plan", "Plan", esc(o["plan"])),
        kv("n_money", "Price Paid", f"<b>{money_sym(u, o['price'])}</b>"),
        kv("n_method", "Payment Method", esc(method)),
        kv("n_key", "Delivered Key", code(o["key"])),
        kv("n_id", "Order ID", code(o["order_no"])),
        kv("n_date", "Date/Time", now_ist() + " IST"),
    ])
    admin_send(f"{E('n_alert')} <b>NEW HACK PURCHASE NOTIFICATION!</b> {E('n_alert')}\n{LINE}\n\n"
               f"<b>CUSTOMER</b>\n{cust}\n\n<b>ORDER</b>\n{order}", contact_kb(u))


def notify_topup(u, amount, prev, cur, order_id, utr, method, force=False):
    """admin: wallet balance was added"""
    if not force and db.get("notify_topup") == "0":
        return
    n, spent, dep = db.stats(g(u, "id"))
    cust = tree([
        kv("n_user", "Name", f"<b>{esc(g(u, 'name'))}</b>"),
        kv("n_link", "Username", uname_txt(u)),
        kv("n_type", "Account Type", f"<b>{role_name(u)}</b>"),
        kv("n_id", "Telegram / Chat ID", code(g(u, "id"))),
        kv("n_phone", "Phone Number", code(phone_txt(u))),
    ])
    pay = tree([
        kv("n_cash", "Amount Added", f"<b>{money_sym(u, amount)}</b>"),
        kv("n_wallet", "Previous Balance", money_sym(u, prev)),
        kv("n_money", "Current Balance", f"<b>{money_sym(u, cur)}</b>"),
        kv("n_method", "Payment Method", esc(method)),
    ])
    stat = tree([
        kv("n_game", "Hacks Purchased", str(n)),
        kv("n_diamond", "Total Hack Purchase Value", money_sym(u, spent)),
        kv("n_inbox", "Total Deposited", money_sym(u, dep)),
    ])
    ids = tree([
        kv("n_id", "Order ID", code(order_id)),
        kv("n_tag", "UTR", code(utr or "-")),
        kv("n_date", "Date/Time", now_ist() + " IST"),
    ])
    admin_send(f"{E('n_alert')} <b>NEW WALLET BALANCE ADDED</b> {E('n_alert')}\n{LINE}\n\n"
               f"<b>CUSTOMER</b>\n{cust}\n\n<b>PAYMENT</b>\n{pay}\n\n<b>STATS</b>\n{stat}\n\n<b>DETAILS</b>\n{ids}", contact_kb(u))


def notify_key_failed(u, product, plan, amount, method, order_id, reason, wallet_note, paid=True, force=False):
    """admin: the key could not be delivered - with everything needed to contact the user"""
    if not force and db.get("notify_fail") == "0":
        return
    title = "PAYMENT SUCCESS — KEY DELIVERY FAILED" if paid else "PURCHASE FAILED — KEY NOT DELIVERED"
    cust = tree([
        kv("n_user", "Name", f"<b>{esc(g(u, 'name'))}</b>"),
        kv("n_link", "Username", uname_txt(u)),
        kv("n_id", "Telegram User ID", code(g(u, "id"))),
        kv("n_chat", "Chat ID", code(g(u, "id"))),
        kv("n_type", "Type", f"<b>{role_name(u)}</b>"),
        kv("n_phone", "Phone", code(phone_txt(u))),
    ])
    order = tree([
        kv("n_money", "Paid Amount" if paid else "Price", f"<b>{money_sym(u, amount)}</b>"),
        kv("n_box", "Product", esc(product)),
        kv("n_plan", "Plan", esc(plan)),
        kv("n_method", "Payment Method", esc(method)),
        kv("n_id", "Order ID", code(order_id)),
        kv("n_fail", "Status", "<b>Key Not Delivered</b>"),
        kv("n_note", "Reason", esc(reason)),
        kv("n_wallet", "Wallet", esc(wallet_note)),
        kv("n_date", "Time", now_ist() + " IST"),
    ])
    admin_send(f"{E('n_alert')} <b>{title}</b> {E('n_alert')}\n{LINE}\n\n<b>CUSTOMER</b>\n{cust}\n\n<b>ORDER</b>\n{order}", contact_kb(u))


def notify_wallet_fail(u, plid, reason):
    """wallet purchase that could not be completed (nothing was charged)"""
    pl = db.plan(plid)
    notify_key_failed(u, pl["pname"] if pl else "-", pl["name"] if pl else "-", db.price_for(u, pl) if pl else 0,
                      "Wallet Balance", "-", reason, "Nothing was charged", paid=False)


def notify_new_user(u, force=False):
    """admin: a new user verified / joined"""
    if not force and db.get("notify_newuser") == "0":
        return
    body = tree([
        kv("n_user", "Name", f"<b>{esc(g(u, 'name'))}</b>"),
        kv("n_link", "Username", uname_txt(u)),
        kv("n_id", "User ID", code(g(u, "id"))),
        kv("n_phone", "Phone Number", code(phone_txt(u))),
        kv("n_globe", "Country", esc(g(u, "country") or "-")),
        kv("n_date", "Date/Time", now_ist() + " IST"),
    ])
    admin_send(f"{E('n_alert')} <b>NEW USER VERIFIED!</b> {E('n_alert')}\n{LINE}\n\n{body}", contact_kb(u))


def sample_data():
    u = {"id": 123456789, "name": "Sample User", "username": "sample_user", "phone": "919999999999", "country": "IN",
         "role": "user", "symbol": "₹", "currency": "INR", "balance": 126.0, "ref_balance": 0, "joined": int(time.time())}
    o = {"order_no": "WAL" + time.strftime("%Y%m%d%H%M%S") + "123456789", "product": "SAMPLE PRODUCT", "plan": "1 days",
         "price": 25.75, "key": "ABCD-1234-EFGH-5678", "created": int(time.time()), "plan_id": 0}
    return u, o


def send_samples():
    """website button: sends every new message once to the admin, so you can check text + premium emoji"""
    if not ADMIN_ID:
        return False
    u, o = sample_data()
    send(ADMIN_ID, "🧪 <b>SAMPLE MESSAGES</b> (fake data) — the 2 messages a USER gets, then the 4 alerts YOU get.")
    send(ADMIN_ID, confirm_purchase_text(u, o), KB(*after_buy_rows(0)))
    send(ADMIN_ID, confirm_topup_text(u, 100, "ORD2026111414220951360A", 126.0), KB([menu_btn()]))
    notify_purchase(u, o, "Wallet Balance", force=True)
    notify_topup(u, 100, 26.0, 126.0, "ORD2026111414220951360A", "FMPIB6991180428", "UPI (Auto QR)", force=True)
    notify_key_failed(u, o["product"], o["plan"], o["price"], "Wallet Balance", o["order_no"],
                      "Wallet payment was processed, but the key could not be issued.", "refunded to the user's wallet automatically", force=True)
    notify_new_user(u, force=True)
    return True


def send_menu_preview():
    """website button: sends the real main menu, shop, referral and tutorial screens to the admin"""
    if not ADMIN_ID:
        return False
    u = db.user(ADMIN_ID) or sample_data()[0]
    for scr in (menu_screen, shop_entry, ref_screen, tut_screen):
        t, k = scr(u)
        send(ADMIN_ID, t, k)
    return True


def send_cat_preview():
    """website button: sends the category screen (and the first category's product list) to the admin"""
    if not ADMIN_ID:
        return False
    u = db.user(ADMIN_ID) or sample_data()[0]
    t, k = shop_entry(u)
    send(ADMIN_ID, t, k)
    cs = db.cats()
    if cs:
        t, k = shop_screen(u, cs[0]["id"])
        send(ADMIN_ID, t, k)
    return True


def success_block(u, pay, txn, extra=""):
    return (f"{E('success')} <b>PAYMENT SUCCESSFUL</b>\n━━━━━━━━━━━━━━━━━━━━\n"
            f"├── {E('receipt')} Order ID: <code>{pay['pay_no']}</code>\n"
            f"├── {E('txn')} Transaction ID: <code>{esc(txn or '-')}</code>\n"
            f"├── {E('money')} Amount: <b>{fmt(u, pay['pay_amount'] or pay['amount'])}</b>\n"
            f"├── {E('time')} {ist(int(time.time()))}\n{extra}")


_busy = set()
_busy_lock = threading.Lock()


def do_buy(uid, plid, coupon="", ext_price=None, on_go=None):
    """ONE entry point for buying a key.
    - plan with keys in the database  -> db.buy (as before)
    - plan connected to the panel API -> money is reserved, the key is bought from the panel API,
      and the money is returned if the panel says no.
    Returns what db.buy returns, plus  ('apifail', reason, price, refunded)  and  ('busy',)."""
    pl = db.plan(plid)
    if not pl or not pl["api_plan_id"]:
        return db.buy(uid, plid, coupon, ext_price)
    if ext_price is None:                       # wallet purchase: one at a time per user (no double tap)
        with _busy_lock:
            if uid in _busy:
                return ("busy",)
            _busy.add(uid)
    try:
        r = db.api_reserve(uid, plid, coupon, ext_price)
        if r[0] != "go":
            return r
        _, price, plrow = r
        if on_go:
            safe(on_go)
        try:
            key = panel.buy(plrow["api_plan_id"])
        except panel.PanelError as e:
            if e.definite:
                if ext_price is None:
                    db.add_balance(uid, price)  # wallet purchase: the reserved money simply goes back (no approval needed)
                else:
                    db.add_refund(uid, price)   # UPI / QR / Binance payment: refund to wallet, locked until admin approves its use
            return ("apifail", e.msg, price, e.definite)
        except Exception as e:
            traceback.print_exc()
            return ("apifail", "Unexpected error: %s" % str(e)[:120], price, False)
        return db.api_finish_ok(uid, plrow, price, key, coupon, ext_price)
    finally:
        if ext_price is None:
            with _busy_lock:
                _busy.discard(uid)


def fail_reason(reason):
    """short customer-friendly reason"""
    r = (reason or "").lower()
    if "stock" in r:
        return "Out of stock"
    return "Server issue"


def refund_text(u, amount, reason, ref, pl=None):
    """customer message when a PAID order (QR / UPI / Binance) could not be delivered: money returned to the bot wallet"""
    lines = []
    if pl:
        lines.append(f"{E('c_product')} Product: <b>{esc(pl['pname'])}</b>")
        lines.append(f"{E('c_plan')} Plan: <b>{esc(pl['name'])}</b>")
    lines += [f"{E('n_note')} Reason: <b>{esc(fail_reason(reason))}</b>",
              f"{E('n_money')} Refunded: <b>{fmt(u, amount)}</b>",
              f"{E('n_wallet')} Wallet balance: <b>{fmt(u, u['balance'])}</b>",
              f"{E('n_id')} Order Ref: <code>{esc(ref)}</code>"]
    return (f"{E('cancel')} <b>ORDER FAILED — REFUND ISSUED</b>\n{LINE}\n\n"
            f"We are sorry! We could not deliver your order this time.\n\n"
            f"{tree(lines)}\n\n"
            f"{E('money')} Your payment of <b>{fmt(u, amount)}</b> has been returned to your <b>bot wallet</b>. "
            f"You can use it to buy any other product from our store.\n\n"
            f"{E('info')} <i>Refunded balance is verified by our team: when you use it, our team approves your order first "
            f"(usually within a few minutes).</i>")


def wallet_fail_text(u, price, reason, ref, pl=None):
    """customer message when a WALLET purchase failed: nothing was charged"""
    lines = []
    if pl:
        lines.append(f"{E('c_product')} Product: <b>{esc(pl['pname'])}</b>")
        lines.append(f"{E('c_plan')} Plan: <b>{esc(pl['name'])}</b>")
    lines += [f"{E('n_note')} Reason: <b>{esc(fail_reason(reason))}</b>",
              f"{E('n_wallet')} Wallet balance: <b>{fmt(u, u['balance'])}</b> (unchanged)",
              f"{E('n_id')} Order Ref: <code>{esc(ref)}</code>"]
    return (f"{E('cancel')} <b>ORDER FAILED — NOTHING CHARGED</b>\n{LINE}\n\n"
            f"We are sorry! We could not deliver your order this time.\n\n"
            f"{tree(lines)}\n\n"
            f"{E('money')} <b>{fmt(u, price)}</b> was <b>not deducted</b> from your wallet. "
            f"You can try again in a few minutes or buy another product.")


def api_fail_texts(u, refunded, price, ref, paid_by_gateway=False, reason="", pl=None):
    """(text shown to the customer, wallet note for the admin alert)"""
    if refunded and paid_by_gateway:
        return (refund_text(u, price, reason, ref, pl),
                f"{fmt(u, price)} returned to the user's wallet as REFUND (locked: you must approve before the user can spend it)")
    if refunded:
        return (wallet_fail_text(u, price, reason, ref, pl), "Wallet refunded automatically - nothing was charged")
    return (f"{E('wait')} <b>Your order is being processed</b>\nThe key is taking longer than usual. Our team has been told and will send "
            f"your key (or refund you) very soon. Please do not buy again.\n{E('receipt')} Ref: <code>{ref}</code>",
            "NOT refunded automatically (unknown if the panel made the key) - check the panel order history, then send the key "
            "or add the balance back (Website -> Users, tick 'refund hold' so you approve its use)")


# ---------------- refund approval (V13)
def notify_refund_request(u, pl, price, hold, rid):
    """admin: a user wants to spend refunded money - Approve / Reject"""
    free = max(0.0, u["balance"] - hold)
    cust = tree([
        kv("n_user", "Name", f"<b>{esc(g(u, 'name'))}</b>"),
        kv("n_link", "Username", uname_txt(u)),
        kv("n_id", "Telegram User ID", code(g(u, "id"))),
        kv("n_phone", "Phone", code(phone_txt(u))),
    ])
    order = tree([
        kv("n_box", "Product", esc(pl["pname"])),
        kv("n_plan", "Plan", esc(pl["name"])),
        kv("n_money", "Price", f"<b>{money_sym(u, price)}</b>"),
        kv("n_wallet", "Wallet balance", f"<b>{money_sym(u, u['balance'])}</b>"),
        kv("n_cash", "Refunded money (locked)", f"<b>{money_sym(u, hold)}</b>"),
        kv("n_diamond", "Free money", f"<b>{money_sym(u, free)}</b>"),
        kv("n_date", "Time", now_ist() + " IST"),
    ])
    kb = KB([B("Approve", cb=f"ra:{rid}", style="success", ek="confirm"), B("Reject", cb=f"rr:{rid}", style="danger", ek="cancel")],
            *contact_kb(u)["inline_keyboard"])
    admin_send(f"{E('n_alert')} <b>REFUND BALANCE — APPROVAL NEEDED</b> {E('n_alert')}\n{LINE}\n\n"
               f"This user got a refund earlier and now wants to buy with it. "
               f"<b>Check that you did not already send the key by hand.</b>\n\n"
               f"<b>CUSTOMER</b>\n{cust}\n\n<b>ORDER</b>\n{order}\n\n"
               f"{E('confirm')} <b>Approve</b> = the user can buy.\n{E('cancel')} <b>Reject</b> = the refunded {money_sym(u, hold)} is taken back from the wallet.", kb)


def refund_gate(cq, uid, plid, chat):
    """wallet purchase that would spend refunded money -> ask the admin. True = stop here (request sent / already waiting)"""
    u = db.user(uid)
    hold = db.hold_of(u)
    pl = db.plan(plid)
    if hold <= 0 or not pl:
        return False
    final, _d, err = db.coupon_calc(u, pl, db.cp_get(uid, plid))
    if err or u["balance"] < final or u["balance"] - hold >= final:
        return False            # free money is enough (or not enough money at all: normal flow answers that)
    rid = db.rq_create(uid, plid, final, hold)
    if rid is None:
        ans(cq, "Your request is already waiting for approval. Please wait a moment.", True)
        return True
    ans(cq)
    info = tree([f"{E('c_product')} Product: <b>{esc(pl['pname'])}</b>", f"{E('c_plan')} Plan: <b>{esc(pl['name'])}</b>"])
    send(chat, f"{E('wait')} <b>WAITING FOR APPROVAL</b>\n{LINE}\n\n"
               f"Your wallet contains a <b>refund of {fmt(u, hold)}</b>. For your safety our team confirms the order before refunded money is used.\n\n"
               f"{info}\n\n"
               f"You will get a message here as soon as it is approved. No need to do anything.",
         KB([menu_btn()]))
    safe(notify_refund_request, u, pl, final, hold, rid)
    return True


def refund_user_msg(uid, ok, hold, plan_id=0):
    """tell the user what the admin decided"""
    u = db.user(uid)
    if not u:
        return
    if ok:
        rows = []
        if plan_id:
            rows.append([B("Continue to checkout", cb=f"pl:{plan_id}", style="success", ek="bag")])
        rows.append([menu_btn()])
        send(uid, f"{E('confirm')} <b>REFUND BALANCE APPROVED</b>\n{LINE}\n\n"
                  f"Your refunded balance of <b>{fmt(u, hold)}</b> is now unlocked and ready to use.\n"
                  f"Wallet balance: <b>{fmt(u, u['balance'])}</b>\n\nTap the button below to complete your purchase.", KB(*rows))
    else:
        send(uid, f"{E('cancel')} <b>REFUND BALANCE REMOVED</b>\n{LINE}\n\n"
                  f"Our team could not approve the use of your refunded balance, so <b>{fmt(u, hold)}</b> was removed from your wallet.\n"
                  f"Wallet balance: <b>{fmt(u, u['balance'])}</b>\n\nIf you think this is a mistake, please contact support.",
             KB([B("Support", cb="sup", style="primary", ek="b_support")], [menu_btn()]))


def complete_pay(pay_no, txn=""):
    """Called by the watcher / webhook / admin. Safe to call many times - runs once."""
    pay = db.pay_resolve(pay_no, txn)
    if not pay:
        return None
    uid = pay["user_id"]
    u = db.user(uid)
    if not u:
        return pay
    if pay["chat_id"] and pay["msg_id"]:
        api("deleteMessage", chat_id=pay["chat_id"], message_id=pay["msg_id"])
    chat = pay["chat_id"] or uid
    mlabel = method_label(pay["method"])
    if pay["kind"] == "topup":
        prev = u["balance"]
        db.add_balance(uid, pay["amount"])
        db.dep_record_paid(uid, pay["amount"], txn or pay_no)
        u = db.user(uid)
        send(chat, confirm_topup_text(u, pay["amount"], pay_no, u["balance"]), KB([menu_btn()]))
        safe(notify_topup, u, pay["amount"], prev, u["balance"], pay_no, txn, mlabel)
    else:
        res = do_buy(uid, pay["plan_id"], ext_price=pay["amount"])
        if res[0] == "ok":
            db.coupon_consume(uid, pay["coupon"])
            o = res[1]
            db.pay_update(pay_no, order_no=o["order_no"])
            u = db.user(uid)
            send(chat, confirm_purchase_text(u, o), KB(*after_buy_rows(pay["plan_id"])))
            safe(notify_purchase, u, o, mlabel)
            comm = db.pay_commission(uid, o["price"])
            if comm:
                ru = db.user(comm[0])
                if ru:
                    send(ru["id"], f"{E('gift2')} Referral commission: you earned <b>{fmt(ru, comm[1])}</b> from a friend's purchase!")
            if res[2] <= int(db.get("low_stock", "3") or 3) and ADMIN_ID:
                send(ADMIN_ID, f"{E('box')} Low stock: <b>{esc(o['product'])} · {esc(o['plan'])}</b> has {res[2]} key(s) left.")
        elif res[0] == "apifail":
            _t, reason, amt_, refunded = res
            u = db.user(uid)
            pl = db.plan(pay["plan_id"])
            utext, wnote = api_fail_texts(u, refunded, amt_, pay_no, paid_by_gateway=True, reason=reason, pl=pl)
            send(chat, utext, KB([B("Shop Now", cb="shop", style="primary", ek="b_shop")], [back_btn()]))
            safe(notify_key_failed, u, pl["pname"] if pl else pay["title"], pl["name"] if pl else "-", pay["amount"], mlabel,
                 pay_no, "Panel API: " + reason, wnote)
        else:
            u = db.user(uid)
            pl = db.plan(pay["plan_id"])
            send(chat, refund_text(u, pay["amount"], "Out of stock", pay_no, pl),
                 KB([B("Shop Now", cb="shop", style="primary", ek="b_shop")], [back_btn()]))
            safe(notify_key_failed, u, pl["pname"] if pl else pay["title"], pl["name"] if pl else "-", pay["amount"], mlabel,
                 pay_no, "Payment received but the key could not be issued (out of stock).",
                 f"{fmt(u, pay['amount'])} returned to the user's wallet as REFUND (locked: you must approve before the user can spend it)")
    return pay


def find_text(h):
    """admin: which user made this order"""
    t = (f"{E('receipt')} <b>{esc(h['kind'])}</b>\n━━━━━━━━━━━━━━━━━━━━\n"
         f"├── {E('ban')} Order ID: <code>{esc(h['ref'])}</code>\n")
    for k, v in h["info"]:
        t += f"├── {esc(k)}: <b>{esc(str(v))}</b>\n"
    t += (f"├── {E('user')} User: <b>{esc(h['uname'] or '-')}</b>\n"
          f"├── {E('idcard')} User ID: <code>{h['uid']}</code>\n"
          f"├── {E('telegram')} Username: {('@' + esc(h['username'])) if h['username'] else '-'}\n"
          f"├── {E('phone')} Phone: <code>{esc(h['phone'] or '-')}</code>\n"
          f"└── {E('wallet')} Wallet: <b>₹{h['balance']:.2f}</b>")
    return t


_polled = {}


def expired_text(pay, minutes):
    return (f"{E('tap')} <b>PAYMENT EXPIRED</b>\n{LINE}\n\n"
            f"— {E('fire2')} Order Id : <code>{pay['pay_no']}</code>\n"
            f"— {E('cancel')} Not paid within {minutes} minutes\n"
            f"— {E('ban')} QR / payment details are no longer valid\n\n"
            f"Tap /start to begin a new order.")


_pw_pool = ThreadPoolExecutor(max_workers=8)


def _pay_one(p, minutes, exp):
    try:
        if time.time() - p["created"] > exp:
            # one last check, then expire (a late payment is still honoured by webhook / admin)
            if gateway.configured():
                st0, tx0, _a = gateway.check(p["pay_no"])
                if st0 == "paid":
                    complete_pay(p["pay_no"], tx0)
                    return
            db.pay_update(p["pay_no"], status="expired")
            _polled.pop(p["pay_no"], None)
            if p["chat_id"]:
                if p["msg_id"]:
                    api("deleteMessage", chat_id=p["chat_id"], message_id=p["msg_id"])
                send(p["chat_id"], expired_text(p, minutes))
            return
        if gateway.configured() and time.time() - _polled.get(p["pay_no"], 0) >= 6:
            _polled[p["pay_no"]] = time.time()
            st, txn, _a = gateway.check(p["pay_no"])
            if st == "paid":
                complete_pay(p["pay_no"], txn)
            elif st == "failed":
                db.pay_update(p["pay_no"], status="cancelled")
    except Exception:
        traceback.print_exc()
    finally:
        _pw_busy.discard(p["pay_no"])


_pw_busy = set()


def pay_watch():
    """background: check pending QR payments (in parallel, one slow gateway call no longer blocks the others),
    and send 'PAYMENT EXPIRED' when the time is over"""
    while True:
        time.sleep(3)
        try:
            minutes = int(db.get("pay_expire", "5") or 5)
            exp = minutes * 60
            for p in db.pay_pending()[:30]:
                if p["pay_no"] in _pw_busy:
                    continue
                _pw_busy.add(p["pay_no"])
                _pw_pool.submit(_pay_one, p, minutes, exp)
        except Exception:
            traceback.print_exc()


def approve_deposit(did, ok=True):
    """Used by Telegram buttons and the website. Returns deposit row or None if already handled."""
    d = db.dep_resolve(did, ok)
    if not d:
        return None
    u = db.user(d["user_id"])
    if u:
        if ok:
            prev = round(u["balance"] - d["amount"], 2)
            send(u["id"], confirm_topup_text(u, d["amount"], f"DEP{did}", u["balance"]), KB([menu_btn()]))
            safe(notify_topup, u, d["amount"], prev, u["balance"], f"DEP{did}", d["utr"], "UPI (Manual)")
        else:
            send(u["id"], f"❌ <b>Deposit #{did} was rejected.</b>\nIf you really paid, contact support with your payment proof.")
    return d


def notify_admin_deposit(d, u, utr, proof):
    if not ADMIN_ID:
        return
    text = (f"{E('wait')} <b>New deposit request</b>\n"
            f"Deposit: <code>#{d['id']}</code>\nUser: <code>{u['id']}</code> {esc(u['name'])}\n"
            f"Amount: <b>{fmt(u, d['amount'])}</b>\nUTR: <code>{esc(utr or '-')}</code>")
    kb = KB([B("Approve", cb=f"da:{d['id']}", style="success", ek="confirm"),
             B("Reject", cb=f"dr:{d['id']}", style="danger", ek="cancel")])
    if proof:
        r = api("sendPhoto", chat_id=ADMIN_ID, photo=proof, caption=text, parse_mode="HTML", reply_markup=kb)
        if r.get("ok"):
            return
    send(ADMIN_ID, text, kb)


_last = {}


def rate_ok(uid, gap=0.2):
    """ignore button taps faster than ~3 per second per user"""
    now = time.time()
    if now - _last.get(uid, 0) < gap:
        return False
    _last[uid] = now
    if len(_last) > 5000:
        _last.clear()
    return True


def send_doc_admin(name, blob, caption="Database backup"):
    if ADMIN_ID:
        api_file("sendDocument", {"document": (name, blob)}, chat_id=ADMIN_ID, caption=caption)


def send_doc_to(chat, name, blob, caption="Database backup"):
    """V18: send a file to ANY chat id (user / group / channel). Returns the Telegram reply."""
    return api_file("sendDocument", {"document": (name, blob)}, chat_id=chat, caption=caption)


def broadcast(text, only_ids=None, done=None):
    """background broadcast, ~20 msgs/sec"""
    def job():
        ok = fail = 0
        for uid in (only_ids or db.broadcast_targets()):
            r = send(uid, text)
            if r.get("ok"):
                ok += 1
            else:
                fail += 1
            time.sleep(0.05)
        if done:
            done(ok, fail)
    threading.Thread(target=job, daemon=True).start()


# ------------------------------------------------------------------ V15: admin access screens
def web_url():
    return (PUBLIC_URL + "/tg-login") if PUBLIC_URL.startswith("https://") else ""


def website_msg():
    url = web_url()
    if not url:
        return ("⚠️ The website address is not set. Add the env variable <b>PUBLIC_URL</b> (https://...) and redeploy.", None)
    return ("🌐 <b>Admin Website</b>\nTap the button — you enter directly, no login needed.",
            {"inline_keyboard": [[{"text": "🌐 Open Admin Website", "web_app": {"url": url}}]]})


def admin_home(uid):
    t, k = website_msg()
    rows = (k or {"inline_keyboard": []})["inline_keyboard"]
    rows.append([{"text": "📣 Broadcast", "callback_data": "bc:home"}])
    if secure.is_owner(uid):
        rows.append([{"text": "👥 Manage Admins", "callback_data": "ad:list"},
                     {"text": "🔐 Security", "callback_data": "ad:sec"}])
    text = "🔨 <b>ADMIN PANEL</b>\n━━━━━━━━━━━━━━\n" + ("Owner access" if secure.is_owner(uid) else "Admin access") + \
           ("\n\n" + t if not k else "")
    return text, {"inline_keyboard": rows}


def _name(i):
    u = db.user(i)
    return (esc(u["name"]) if u and u["name"] else "—") + (f" @{esc(u['username'])}" if u and u["username"] else "")


def admins_screen():
    ids = secure.admin_ids()
    lines = [f"👑 Owner: <code>{secure.owner_id()}</code>"]
    rows = []
    for i in ids:
        lines.append(f"🛡 Admin: <code>{i}</code> · {_name(i)}")
        rows.append([B(f"Remove {i}", cb=f"ad:rm:{i}", style="danger")])
    if not ids:
        lines.append("\nNo extra admins yet.")
    rows.append([B("➕ Add Admin", cb="ad:add", style="success")])
    rows.append([B("Back", cb="ad:home")])
    return "👥 <b>ADMINS</b>\n━━━━━━━━━━━━━━\n" + "\n".join(lines), KB(*rows)


def security_screen(note=""):
    tr, bn = secure.trusted(), secure.bans()
    lines = [f"🔐 <b>SECURITY</b>\n━━━━━━━━━━━━━━", f"✅ Trusted devices: <b>{len(tr)}</b>"]
    for d in tr[-5:]:
        lines.append(f"   • {esc(secure.short_ua(d.get('ua', '')))} · <code>{esc(d.get('ip', ''))}</code>")
    lines.append(f"🚫 Banned devices: <b>{len(bn['dev'])}</b> · banned IPs: <b>{len(bn['ip'])}</b>")
    lines.append("\nNew device + correct password = you get an alert here (Yes = allow, No = ban).")
    if note:
        lines.append("\n" + note)
    return "\n".join(lines), KB([B("🧹 Remove trusted devices", cb="ad:rev")], [B("✅ Unban all", cb="ad:unban")], [B("Back", cb="ad:home")])


def do_add_admin(chat, raw_id):
    raw_id = (raw_id or "").strip()
    if not raw_id.isdigit():
        send(chat, "❌ Send the Telegram ID as numbers only (or forward a message from him).")
        return
    ok, msg = secure.add_admin(int(raw_id))
    if not ok:
        send(chat, "⚠️ " + esc(msg))
        return
    r = send(int(raw_id), "✅ <b>You are now an admin.</b>\nPress /start — then use /admin or /website.")
    safe(secure.sync_commands, int(raw_id))
    send(chat, f"✅ Admin added: <code>{raw_id}</code>" + ("" if r.get("ok") else
         "\n⚠️ Telegram could not message him — he must press /start in this bot once, then press /start again."), admins_screen()[1])


def do_remove_admin(chat, raw_id, quiet=False):
    raw_id = (raw_id or "").strip()
    if not raw_id.isdigit() or not secure.remove_admin(int(raw_id)):
        if not quiet:
            send(chat, "⚠️ That ID is not an admin.")
        return
    safe(secure.sync_commands, int(raw_id))
    safe(send, int(raw_id), "⛔ Your admin access was removed.")
    if not quiet:
        send(chat, f"✅ Admin removed: <code>{raw_id}</code>")


def user_card(p):
    u = p["u"]
    return (f"👤 <b>{esc(u['name'])}</b>" + (f" · @{esc(u['username'])}" if u["username"] else "") + "\n━━━━━━━━━━━━━━\n"
            f"🆔 <code>{u['id']}</code>\n📱 {esc(u['phone'] or '-')} · {esc(u['country'])}\n"
            f"👑 {u['role']}" + (" · 🚫 BANNED" if u["banned"] else "") + (" · not verified" if not u["verified"] else "") + "\n"
            f"📅 Joined {ist(u['joined'], '%d %b %Y')}\n\n"
            f"🛒 Hacks bought: <b>{p['hacks']}</b>\n💸 Spent: <b>{u['symbol']}{p['spent']:.2f}</b>\n"
            f"👛 Balance: <b>{u['symbol']}{u['balance']:.2f}</b>\n📥 Deposited: <b>{u['symbol']}{p['deposited']:.2f}</b>\n"
            f"🎁 Referral balance: {u['symbol']}{(u['ref_balance'] or 0):.2f} · referred {p['nrefs']}\n"
            + ("\n<b>Top products</b>\n" + "\n".join(f"• {esc(r['product'])} × {r['n']}" for r in p["by_product"][:5]) if p["by_product"] else ""))


def user_kb(uid):
    url = PUBLIC_URL + f"/tg-login?next=/users/{uid}" if PUBLIC_URL.startswith("https://") else ""
    rows = [[{"text": "📂 Full profile (website)", "web_app": {"url": url}}]] if url else []
    rows.append([{"text": "✉️ Contact", "url": f"tg://user?id={uid}"}])
    return {"inline_keyboard": rows}


# ------------------------------------------------------------------ V16: broadcast (from the bot)
def bc_kind(m):
    for k in ("animation", "photo", "video", "audio", "voice", "video_note", "document"):
        if k in m:
            return k
    return "text" if m.get("text") else None


def bc_home():
    n = {k: len(bcast.targets(k)) for k in ("all", "usr", "res")}
    t = ("📣 <b>BROADCAST</b>\n━━━━━━━━━━━━━━\nSend text, photo, video, audio, voice or file to your customers.\n\n"
         f"👥 All: <b>{n['all']}</b> · 🛒 Users: <b>{n['usr']}</b> · 💼 Resellers: <b>{n['res']}</b>\n\nWho should get it?")
    return t, KB([B("👥 All (users + resellers)", cb="bc:t:all")],
                 [B("🛒 Only users", cb="bc:t:usr"), B("💼 Only resellers", cb="bc:t:res")],
                 [B("🎯 One person (Telegram ID)", cb="bc:t:one")],
                 [B("📜 Broadcast history", cb="bc:hist")],
                 [B("Back", cb="bc:back")])


def bc_cancel_kb():
    return KB([B("Cancel", cb="bc:home", style="danger")])


def bc_detail(bid):
    r = bcast.get(bid)
    if not r:
        return "Not found.", KB([B("Back", cb="bc:hist")])
    state = "🗑 <b>Deleted from users</b>" if r["deleted"] else ("⏳ Sending…" if r["state"] != "done" else "✅ Sent")
    t = (f"{bcast.ICON.get(r['kind'], '')} <b>BROADCAST #{r['id']}</b>\n━━━━━━━━━━━━━━\n"
         f"🕐 {ist(r['created'])}\n🎯 {bcast.LABEL.get(r['target'], r['target'])}\n📦 Type: {r['kind']}\n"
         f"✅ Delivered: <b>{r['ok']}</b> · ❌ Failed: <b>{r['fail']}</b> · Total: {r['total']}\n"
         f"✏️ Edited: {r['edited']} time(s)\n{state}\n\n📝 {esc(r['preview']) or '—'}")
    rows = []
    if not r["deleted"] and r["state"] == "done":
        row = []
        if r["kind"] in bcast.EDITABLE:
            row.append(B("✏️ Edit", cb=f"bc:e:{bid}"))
        row.append(B("🗑 Delete from all", cb=f"bc:d:{bid}", style="danger"))
        rows.append(row)
    rows.append([B("Back", cb="bc:hist")])
    return t, KB(*rows)


def bc_history():
    rows = []
    for r in bcast.recent(10):
        lab = f"#{r['id']} {bcast.ICON.get(r['kind'], '')} {bcast.LABEL.get(r['target'], '')[:14]} · {r['ok']}/{r['total']}" + (" 🗑" if r["deleted"] else "")
        rows.append([B(lab, cb=f"bc:v:{r['id']}")])
    rows.append([B("Back", cb="bc:home")])
    return ("📜 <b>BROADCAST HISTORY</b> (last 10)\nTap one to edit or delete it." if len(rows) > 1 else "📜 No broadcasts yet."), KB(*rows)


def _bc_put(chat, mid, t, k):
    api("editMessageText", chat_id=chat, message_id=mid, text=t, parse_mode="HTML", reply_markup=k,
        link_preview_options=json.dumps({"is_disabled": True}))


def bc_cb(cq, uid, chat, mid, act):
    ans(cq)
    st = bcast.WAIT.get(uid) or {}
    if act in ("home", "back"):
        bcast.WAIT.pop(uid, None)
        _bc_put(chat, mid, *(bc_home() if act == "home" else admin_home(uid)))
    elif act.startswith("t:"):
        kind = act[2:]
        if kind == "one":
            bcast.WAIT[uid] = {"step": "id"}
            _bc_put(chat, mid, "🎯 <b>One person</b>\n\nSend his <b>Telegram ID</b> (numbers) or forward any message from him.", bc_cancel_kb())
        else:
            n = len(bcast.targets(kind))
            bcast.WAIT[uid] = {"step": "msg", "target": kind}
            _bc_put(chat, mid, f"📣 <b>{bcast.LABEL[kind]}</b> — {n} people\n\nNow send the message: <b>text, photo, video, audio, voice, GIF or file</b> "
                               "(caption allowed). It is sent exactly as you write it.", bc_cancel_kb())
    elif act == "ok":
        if st.get("step") != "confirm":
            _bc_put(chat, mid, "⌛ Expired. Start again.", KB([B("Back", cb="bc:home")]))
            return
        bcast.WAIT.pop(uid, None)
        ids = st["ids"]
        bid = bcast.create(uid, st["target"], st["kind"], st["preview"], len(ids))
        _bc_put(chat, mid, f"⏳ <b>Broadcast #{bid}</b> started — {len(ids)} people.\nYou get a message here when it is finished.", KB([B("📜 History", cb="bc:hist")]))
        threading.Thread(target=bc_run, args=(bid, ids, st["src_chat"], st["src_mid"], chat), daemon=True).start()
    elif act == "hist":
        _bc_put(chat, mid, *bc_history())
    elif act.startswith("v:"):
        _bc_put(chat, mid, *bc_detail(int(act[2:])))
    elif act.startswith("e:"):
        bid = int(act[2:])
        r = bcast.get(bid)
        if not r or r["deleted"] or r["kind"] not in bcast.EDITABLE:
            ans(cq, "This broadcast cannot be edited.", True)
            return
        bcast.WAIT[uid] = {"step": "edit", "bc": bid}
        what = "text" if r["kind"] == "text" else "caption"
        _bc_put(chat, mid, f"✏️ <b>Edit #{bid}</b>\n\nSend the new <b>{what}</b> as a text message. It replaces the old {what} for everyone who got it.",
                KB([B("Cancel", cb=f"bc:v:{bid}", style="danger")]))
    elif act.startswith("d:"):
        bid = int(act[2:])
        _bc_put(chat, mid, f"🗑 <b>Delete #{bid} from every user's chat?</b>\nThe message disappears for all who received it.",
                KB([B("Yes, delete", cb=f"bc:dd:{bid}", style="danger")], [B("No", cb=f"bc:v:{bid}")]))
    elif act.startswith("dd:"):
        bid = int(act[3:])
        _bc_put(chat, mid, f"⏳ Deleting broadcast #{bid}…", KB([B("📜 History", cb="bc:hist")]))
        threading.Thread(target=bc_delete, args=(bid, chat), daemon=True).start()


def bc_input(chat, uid, m):
    st = bcast.WAIT.get(uid) or {}
    step = st.get("step")
    if step == "id":
        fid = ((m.get("forward_origin") or {}).get("sender_user") or {}).get("id") or (m.get("forward_from") or {}).get("id")
        s = str(fid) if fid else (m.get("text") or "").strip()
        if not s.isdigit():
            send(chat, "❌ Send the Telegram ID as numbers only, or forward a message from him.", bc_cancel_kb())
            return
        bcast.WAIT[uid] = {"step": "msg", "target": "one", "one": int(s)}
        send(chat, f"🎯 Person <code>{s}</code>.\nNow send the message (text, photo, video, audio, voice, GIF or file).", bc_cancel_kb())
    elif step == "msg":
        kind = bc_kind(m)
        if not kind:
            send(chat, "❌ This type is not supported. Send text, photo, video, audio, voice, GIF or a file.", bc_cancel_kb())
            return
        tgt = st["target"]
        ids = [st["one"]] if tgt == "one" else bcast.targets(tgt)
        if not ids:
            send(chat, "⚠️ Nobody is in this group yet.", KB([B("Back", cb="bc:home")]))
            bcast.WAIT.pop(uid, None)
            return
        st.update(step="confirm", ids=ids, kind=kind, src_chat=chat, src_mid=m["message_id"],
                  preview=(m.get("text") or m.get("caption") or "")[:200])
        send(chat, f"📣 <b>Ready to send</b>\n{bcast.ICON.get(kind, '')} {kind} → <b>{bcast.LABEL[tgt]}</b> ({len(ids)} people)\n\nThe message above is exactly what they get.",
             KB([B("✅ Send now", cb="bc:ok", style="success")], [B("❌ Cancel", cb="bc:home", style="danger")]))
    elif step == "edit":
        txt = m.get("text")
        if not txt:
            send(chat, "❌ Send the new text as a normal text message.", bc_cancel_kb())
            return
        bcast.WAIT.pop(uid, None)
        r = bcast.get(st["bc"])
        if not r or r["deleted"]:
            send(chat, "⚠️ This broadcast was deleted.")
            return
        send(chat, f"⏳ Editing broadcast #{r['id']}…")
        threading.Thread(target=bc_edit, args=(r["id"], txt, m.get("entities") or [], chat), daemon=True).start()


def _retry(method, **p):
    r = api(method, **p)
    if r.get("error_code") == 429:
        time.sleep(min((r.get("parameters") or {}).get("retry_after", 3), 30) + 1)
        r = api(method, **p)
    return r


def bc_run(bid, ids, src_chat, src_mid, report_chat):
    ok = fail = 0
    batch = []
    for i in ids:
        r = _retry("copyMessage", chat_id=i, from_chat_id=src_chat, message_id=src_mid)
        if r.get("ok"):
            ok += 1
            batch.append((i, r["result"]["message_id"]))
        else:
            fail += 1
        if len(batch) >= 100:
            bcast.add_msgs(bid, batch)
            batch = []
        time.sleep(0.05)
    bcast.add_msgs(bid, batch)
    bcast.finish(bid, ok, fail)
    send(report_chat, f"✅ <b>Broadcast #{bid} finished</b>\nDelivered: <b>{ok}</b> · Failed: <b>{fail}</b> (blocked the bot / never started it)",
         KB([B("Open", cb=f"bc:v:{bid}")]))


def bc_delete(bid, report_chat):
    ok = fail = 0
    for c, mid in bcast.msgs(bid):
        r = _retry("deleteMessage", chat_id=c, message_id=mid)
        if r.get("ok") or "not found" in str(r.get("description", "")):
            ok += 1
        else:
            fail += 1
        time.sleep(0.05)
    bcast.set_deleted(bid)
    send(report_chat, f"🗑 <b>Broadcast #{bid} deleted</b>\nRemoved: <b>{ok}</b> · Could not remove: <b>{fail}</b>", KB([B("📜 History", cb="bc:hist")]))


def bc_edit(bid, text, ents, report_chat):
    r0 = bcast.get(bid)
    ok = fail = 0
    for c, mid in bcast.msgs(bid):
        if r0["kind"] == "text":
            r = _retry("editMessageText", chat_id=c, message_id=mid, text=text, entities=json.dumps(ents),
                       link_preview_options=json.dumps({"is_disabled": True}))
        else:
            r = _retry("editMessageCaption", chat_id=c, message_id=mid, caption=text, caption_entities=json.dumps(ents))
        if r.get("ok") or "not modified" in str(r.get("description", "")):
            ok += 1
        else:
            fail += 1
        time.sleep(0.05)
    bcast.set_edited(bid, text)
    send(report_chat, f"✏️ <b>Broadcast #{bid} edited</b>\nUpdated: <b>{ok}</b> · Failed: <b>{fail}</b>", KB([B("Open", cb=f"bc:v:{bid}")]))


# ------------------------------------------------------------------ handlers
def ask_phone(chat):
    kb = {"keyboard": [[{"text": "📱 Share Phone Number", "request_contact": True}]],
          "resize_keyboard": True, "one_time_keyboard": True}
    send(chat, "👋 <b>Welcome!</b>\n\nTo continue, please verify your phone number using the button below.", kb)


def on_message(m):
    if m["chat"]["type"] != "private":
        return
    chat, fr = m["chat"]["id"], m["from"]
    uid = fr["id"]
    text = m.get("text", "") or ""

    # admin helper: send a premium emoji -> get its ID
    ents = [e for e in (m.get("entities") or []) if e["type"] == "custom_emoji"]
    if secure.is_admin(uid) and ents and uid not in bcast.WAIT:
        t16 = text.encode("utf-16-le")
        lines = []
        for e in ents:
            ch = t16[e["offset"] * 2:(e["offset"] + e["length"]) * 2].decode("utf-16-le")
            lines.append(f"{ch}  <code>{e['custom_emoji_id']}</code>")
        send(chat, "<b>Premium emoji IDs:</b>\n" + "\n".join(lines) +
             "\n\nPaste the ID in the website admin panel → Premium Emoji.")
        return

    if secure.is_admin(uid) and text.startswith("/find"):
        q = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        if not q:
            send(chat, "Send: <code>/find ORD2026...</code> (order ID, WAL… order, or transaction ID)")
            return
        hits = db.find_order(q)
        if not hits:
            send(chat, f"❌ Nothing found for <code>{esc(q)}</code>.")
            return
        for h in hits[:5]:
            send(chat, find_text(h))
        return

    if secure.is_admin(uid) and text.startswith("/emojitest"):
        ok, rep = emoji_test()
        send(chat, ("✅ " if ok else "⚠️ ") + esc(rep))
        return

    # ---- V15: admin commands (only owner / admins ever see or can use them)
    if secure.is_admin(uid):
        if uid in bcast.WAIT:
            if text.startswith("/"):
                bcast.WAIT.pop(uid, None)             # a command cancels the broadcast step
            else:
                bc_input(chat, uid, m)
                return
        cmd = text.split("@")[0].split()[0].lower() if text.startswith("/") else ""
        if cmd == "/user":
            q = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
            if not q:
                send(chat, "Send: <code>/user 6739795427</code> or <code>/user @username</code> or <code>/user 9199...</code> (phone)")
                return
            rows, total = db.search_users(q, "all", "new", 5, 0)
            if not rows:
                send(chat, f"❌ Nobody found for <code>{esc(q)}</code>.")
                return
            for r in rows:
                p = db.user_profile(r["id"])
                send(chat, user_card(p), user_kb(r["id"]))
            if total > len(rows):
                send(chat, f"…and {total - len(rows)} more. Use the website Users page.")
            return
        if cmd == "/broadcast":
            send(chat, *bc_home())
            return
        if cmd == "/admin":
            send(chat, *admin_home(uid))
            return
        if cmd == "/website":
            send(chat, *website_msg())
            return
        if secure.is_owner(uid):
            parts = text.split()
            if cmd == "/addadmin" and len(parts) > 1:
                do_add_admin(chat, parts[1])
                return
            if cmd == "/removeadmin" and len(parts) > 1:
                do_remove_admin(chat, parts[1])
                return
            if uid in secure.ADD_WAIT and not text.startswith("/"):
                fid = ((m.get("forward_origin") or {}).get("sender_user") or {}).get("id") or (m.get("forward_from") or {}).get("id")
                cand = str(fid) if fid else text.strip()
                secure.ADD_WAIT.pop(uid, None)
                do_add_admin(chat, cand)
                return

    if db.get("maint") == "1" and not secure.is_admin(uid):
        send(chat, "🛠 " + esc(db.get("maint_text")))
        return

    if text.startswith("/start"):
        if secure.is_admin(uid):
            threading.Thread(target=safe, args=(secure.sync_commands, uid), daemon=True).start()
        parts = text.split(maxsplit=1)
        ref = None
        deep_pid = None
        if len(parts) > 1 and parts[1].startswith("ref_"):
            try:
                ref = int(parts[1][4:])
            except ValueError:
                pass
        elif len(parts) > 1 and parts[1].startswith("p_"):         # V19: product link
            try:
                deep_pid = int(parts[1][2:])
            except ValueError:
                pass
        u0 = db.ensure_user(fr, ref)
        u = db.autoverify(u0)
        if u["banned"]:
            return
        if u["verified"] and not u0["verified"]:        # phone check is OFF -> the user counts as verified now
            safe(notify_new_user, u)
        if u["verified"]:
            if deep_pid:
                open_product(chat, u, deep_pid, m.get("message_id"))
            else:
                start_flow(chat, u, m.get("message_id"))
        else:
            if deep_pid:
                DEEP[uid] = deep_pid                  # open it right after the phone is verified
            ask_phone(chat)
        return

    c = m.get("contact")
    if c:
        if c.get("user_id") != uid:
            send(chat, "❌ Please share <b>your own</b> number using the button.")
            return
        u = db.ensure_user(fr)
        was_verified = bool(u["verified"])
        phone = "".join(ch for ch in c["phone_number"] if ch.isdigit())
        refby = db.verify(uid, phone)
        if not was_verified:
            safe(notify_new_user, db.user(uid))
        if refby:
            reward = float(db.get("ref_reward", "2"))
            db.add_ref_balance(refby, reward)
            ru = db.user(refby)
            if ru:
                send(refby, f"🎁 Your friend joined and verified! You earned <b>{ru['symbol']}{reward:g}</b> referral balance.")
        api("sendMessage", chat_id=chat, text="✅ <b>Phone verified!</b>", parse_mode="HTML",
            reply_markup=json.dumps({"remove_keyboard": True}))
        dp = DEEP.pop(uid, None)
        if dp:
            open_product(chat, db.user(uid), dp)
        else:
            send_menu(chat, db.user(uid))
        return

    u = db.autoverify(db.user(uid))
    if not u or not u["verified"]:
        ask_phone(chat)
        return
    if u["banned"]:
        return
    st = db.st_get(uid)
    if st.startswith("coupon:"):
        plid = int(st[7:])
        pl = db.plan(plid)
        code = text.strip().upper()[:32] if text and not text.startswith("/") else ""
        if not pl or not code:
            send(chat, "Please send the <b>coupon code</b> as text.")
            return
        final, disc, err = db.coupon_calc(u, pl, code)
        if err:
            send(chat, f"❌ {esc(err)}\nSend another code or tap Cancel.",
                 KB([B("Cancel", cb=f"pl:{plid}", style="danger", ek="cancel")]))
            return
        db.cp_set(uid, plid, code)
        db.st_set(uid, "")
        send(chat, f"{E('success')} <b>Coupon applied!</b> You save <b>{fmt(u, disc)}</b>.")
        t, k = plan_screen(u, plid)
        send(chat, t, k)
        return
    if st.startswith("mp:"):
        no = st[3:]
        p = db.pay_get(no)
        photo = (m.get("photo") or [{}])[-1].get("file_id", "")
        txn = text.strip()[:80] if text and not text.startswith("/") else ""
        if not p or p["user_id"] != uid or p["status"] != "pending":
            db.st_set(uid, "")
        elif not txn and not photo:
            send(chat, "Please send your <b>Transaction ID</b> as text, or a payment screenshot.")
            return
        elif txn and len(txn) < 6:
            send(chat, "❌ That ID looks too short. Send the full Transaction ID / Order ID or a screenshot.")
            return
        elif txn and db.pay_txn_used(txn):
            send(chat, "❌ This transaction ID was already used. Contact support if this is a mistake.")
            return
        else:
            db.pay_submit(no, txn, photo)
            db.st_set(uid, "")
            if p["chat_id"] and p["msg_id"]:
                api("deleteMessage", chat_id=p["chat_id"], message_id=p["msg_id"])
            send(chat, f"{E('wait')} <b>Request sent to admin!</b>\nOrder <code>{no}</code> is being checked. "
                       f"You will get your {'balance' if p['kind'] == 'topup' else 'key'} as soon as it is approved.", KB([back_btn()]))
            notify_admin_pay(db.pay_get(no), u)
            return
    if st.startswith("utr:"):
        did = int(st[4:])
        d = db.dep_get(did)
        photo = (m.get("photo") or [{}])[-1].get("file_id", "")
        utr = text.strip()[:64] if text and not text.startswith("/") else ""
        if not d or d["user_id"] != uid or d["status"] != "pending":
            db.st_set(uid, "")
        elif not utr and not photo:
            send(chat, "Please send your <b>UTR / Transaction ID</b> as text, or a payment screenshot.")
            return
        elif utr and len(utr) < 6:
            send(chat, "❌ That ID looks too short. Send the full UTR / Transaction ID or a screenshot.")
            return
        elif utr and db.dep_utr_used(utr):
            send(chat, "❌ This transaction ID was already used. Contact support if this is a mistake.")
            return
        else:
            db.dep_submit(did, utr, photo)
            db.st_set(uid, "")
            send(chat, f"{E('wait')} <b>Request submitted!</b>\nDeposit <code>#{did}</code> is under review. "
                       f"Your balance will be updated as soon as it is approved.", KB([back_btn()]))
            notify_admin_deposit(db.dep_get(did), u, utr, photo)
            return
    send_menu(chat, u)


_NAV = {"menu", "shop", "profile", "ref", "tut", "sup", "hist", "addbal"}


def on_cb(cq):
    uid = cq["from"]["id"]
    chat, mid = cq["message"]["chat"]["id"], cq["message"]["message_id"]
    data = cq["data"]
    photo = "photo" in cq["message"]

    # ---- V15: new-device login approval (owner only)
    if data.startswith("wl:"):
        if not secure.is_owner(uid):
            ans(cq, "Not allowed.", True)
            return
        try:
            _, yn, rid = data.split(":", 2)
        except ValueError:
            return
        res = secure.decide(rid, yn == "y")
        msg = {"ok": "✅ <b>Login allowed.</b> This device is trusted now.",
               "no": "🚫 <b>Login denied.</b> The device and its IP are banned. The red alert is shown to them.",
               "old": "⌛ This request is already handled or expired."}[res]
        api("editMessageText", chat_id=chat, message_id=mid, text=msg, parse_mode="HTML",
            reply_markup=json.dumps({"inline_keyboard": []}))
        ans(cq)
        return
    # ---- V16: broadcast screens (owner + admins)
    if data.startswith("bc:"):
        if not secure.is_admin(uid):
            ans(cq, "Not allowed.", True)
            return
        bc_cb(cq, uid, chat, mid, data[3:])
        return
    # ---- V15: admin panel screens
    if data.startswith("ad:"):
        if not secure.is_owner(uid):
            ans(cq, "Only the owner can do this.", True)
            return
        ans(cq)
        act = data[3:]
        if act == "home":
            t, k = admin_home(uid)
        elif act == "list":
            t, k = admins_screen()
        elif act == "add":
            secure.ADD_WAIT[uid] = time.time()
            t, k = ("➕ <b>Add admin</b>\n\nSend the new admin's <b>Telegram ID</b> (numbers), or <b>forward</b> any message from him here.\n"
                    "He must have pressed /start in this bot once.", KB([B("Cancel", cb="ad:list")]))
        elif act.startswith("rm:"):
            do_remove_admin(chat, act[3:], quiet=True)
            t, k = admins_screen()
        elif act == "sec":
            t, k = security_screen()
        elif act == "rev":
            secure.revoke_all()
            t, k = security_screen("🧹 All trusted devices removed. The next login will ask for approval... (the very first login is trusted again).")
        elif act == "unban":
            secure.unban_all()
            t, k = security_screen("✅ All bans cleared.")
        else:
            return
        api("editMessageText", chat_id=chat, message_id=mid, text=t, parse_mode="HTML", reply_markup=k,
            link_preview_options=json.dumps({"is_disabled": True}))
        return

    # admin deposit buttons (work even if admin has not verified a phone)
    if data[:3] in ("ma:", "mr:"):
        if not secure.is_admin(uid):
            ans(cq, "Not allowed.", True)
            return
        no, ok = data[3:], data.startswith("ma:")
        if ok:
            pp = db.pay_get(no)
            res = complete_pay(no, (pp["txn"] if pp else "") or "ADMIN")
        else:
            res = reject_pay(no)
        api("editMessageReplyMarkup", chat_id=chat, message_id=mid, reply_markup=json.dumps({"inline_keyboard": []}))
        ans(cq, (("Approved" if ok else "Rejected") if res else "Already handled"), True)
        if res:
            send(chat, f"{'✅ Approved' if ok else '❌ Rejected'} payment <code>{no}</code>.")
        return
    if data[:3] in ("ra:", "rr:"):
        if not secure.is_admin(uid):
            ans(cq, "Not allowed.", True)
            return
        ok = data.startswith("ra:")
        res = db.rq_decide(int(data[3:]), ok)
        api("editMessageReplyMarkup", chat_id=chat, message_id=mid, reply_markup=json.dumps({"inline_keyboard": []}))
        ans(cq, ("Approved" if ok else "Rejected - refunded money removed") if res else "Already handled", True)
        if res:
            r, hold = res
            send(chat, f"{'✅ Approved' if ok else '❌ Rejected'} refund request <code>#{r['id']}</code> · user <code>{r['user_id']}</code> · {hold:.2f}"
                       + ("" if ok else " removed from wallet"))
            safe(refund_user_msg, r["user_id"], ok, hold, r["plan_id"])
        return
    if data[:3] in ("da:", "dr:"):
        if not secure.is_admin(uid):
            ans(cq, "Not allowed.", True)
            return
        did = int(data[3:])
        ok = data.startswith("da:")
        d = approve_deposit(did, ok)
        api("editMessageReplyMarkup", chat_id=chat, message_id=mid, reply_markup=json.dumps({"inline_keyboard": []}))
        ans(cq, ("Approved" if ok else "Rejected") if d else "Already handled", True)
        if d:
            send(chat, f"{'✅ Approved' if ok else '❌ Rejected'} deposit <code>#{did}</code>.")
        return

    u = db.autoverify(db.user(uid))
    if not u or not u["verified"] or u["banned"]:
        ans(cq, "Please /start the bot first.", True)
        return
    if db.get("maint") == "1" and not secure.is_admin(uid):
        ans(cq, db.get("maint_text"), True)
        return
    if not rate_ok(uid):
        ans(cq)
        return

    def sh(t, k):
        show(chat, mid, t, k, photo)

    # V22: plain screen changes -> stop the button's loading clock at once (screen is edited right after)
    if data in _NAV or data.startswith(("cat:", "p:", "pl:")):
        ans(cq)

    if data == "menu":
        db.kp_set(uid, "")
        db.st_set(uid, "")
        sh(*menu_screen(u))
    elif data == "shop":
        sh(*shop_entry(u))
    elif data.startswith("cat:"):
        sh(*shop_screen(u, int(data[4:] or 0)))
    elif data.startswith("p:"):
        sh(*prod_screen(u, int(data[2:])))
    elif data.startswith("pl:"):
        db.st_set(uid, "")
        sh(*plan_screen(u, int(data[3:])))
    elif data.startswith("cp:"):
        plid = int(data[3:])
        db.st_set(uid, f"coupon:{plid}")
        ans(cq)
        sh(f"{E('coupon')} <b>COUPON</b>\n━━━━━━━━━━━━━━━━━━━━\nSend your <b>coupon code</b> now.",
           KB([B("Cancel", cb=f"pl:{plid}", style="danger", ek="cancel")]))
        return
    elif data.startswith("pq:"):
        plid = int(data[3:])
        pl = db.plan(plid)
        if not pl or not pl["pactive"] or not pl["active"]:
            ans(cq, "This item is no longer available.", True)
            return
        if pl["stock"] <= 0:
            ans(cq, "❌ This plan is Out of Stock right now.", True)
            return
        final, disc, err = db.coupon_calc(u, pl, db.cp_get(uid, plid))
        if err:
            ans(cq, err, True)
            return
        if final <= 0:
            ans(cq, "Price is 0 after coupon - use Pay via Wallet.", True)
            return
        code = db.cp_get(uid, plid)
        title = f"{pl['pname']} · {pl['name']}"
        if gateway.configured():
            ans(cq, "Creating payment...")
            start_qr(chat, mid, u, "buy", final, plid, code, title)
        elif not method_err(u, "upi"):
            ans(cq)
            start_manual(chat, mid, u, "upi", "buy", final, plid, code, title)
        else:
            ans(cq, "UPI payment is not available right now.", True)
        return
    elif data[:3] in ("pu:", "pb:"):
        plid = int(data[3:])
        pl = db.plan(plid)
        if not pl or not pl["pactive"] or not pl["active"]:
            ans(cq, "This item is no longer available.", True)
            return
        if pl["stock"] <= 0:
            ans(cq, "❌ This plan is Out of Stock right now.", True)
            return
        method = "binance" if data[:3] == "pb:" else ("upi" if u["currency"] == "INR" else "other")
        e = method_err(u, method)
        if e:
            ans(cq, e, True)
            return
        final, disc, err = db.coupon_calc(u, pl, db.cp_get(uid, plid))
        if err:
            ans(cq, err, True)
            return
        if final <= 0:
            ans(cq, "Price is 0 after coupon - use Pay Wallet.", True)
            return
        ans(cq)
        start_manual(chat, mid, u, method, "buy", final, plid, db.cp_get(uid, plid), f"{pl['pname']} · {pl['name']}")
        return
    elif data[:3] in ("tq:", "tu:", "tb:"):
        amt = int(data[3:])
        mn, mx = int(db.get("min_dep", "1")), int(db.get("max_dep", "10000"))
        if amt < mn or amt > mx:
            ans(cq, f"Amount must be between {u['symbol']}{mn} and {u['symbol']}{mx:,}", True)
            return
        k = data[1]
        if k in ("q", "u"):
            if gateway.configured():
                ans(cq, "Creating payment...")
                start_qr(chat, mid, u, "topup", float(amt), 0, "", "Wallet Recharge")
            elif not method_err(u, "upi"):
                ans(cq)
                start_manual(chat, mid, u, "upi", "topup", float(amt), 0, "", "Wallet Recharge")
            else:
                ans(cq, "UPI payment is not available right now.", True)
            return
        method = "binance"
        e = method_err(u, method)
        if e:
            ans(cq, e, True)
            return
        ans(cq)
        start_manual(chat, mid, u, method, "topup", float(amt), 0, "", "Wallet Recharge")
        return
    elif data.startswith("pm:"):
        p = db.pay_get(data[3:])
        if not p or p["user_id"] != uid or p["status"] != "pending":
            ans(cq, "This payment request is no longer active.", True)
            return
        db.st_set(uid, f"mp:{p['pay_no']}")
        ans(cq)
        send(chat, f"{E('paid')} Send your <b>Transaction ID</b> (UTR / Binance Order ID) as text, or a <b>payment screenshot</b> now.",
             KB([B("Cancel", cb=f"pc:{p['pay_no']}", style="danger", ek="cancel")]))
        return
    elif data == "noop":
        ans(cq)
        return
    elif data.startswith("pc:"):
        p = db.pay_get(data[3:])
        if p and p["user_id"] == uid and p["status"] == "pending":
            db.pay_update(p["pay_no"], status="cancelled")
        ans(cq, "Payment cancelled.")
        sh(*menu_screen(u))
        return
    elif data == "oos":
        ans(cq, "❌ This plan is Out of Stock right now.", True)
        return
    elif data.startswith("buy:"):
        plid_b = int(data[4:])
        if refund_gate(cq, uid, plid_b, chat):
            return
        res = do_buy(uid, plid_b, db.cp_get(uid, plid_b), on_go=lambda: ans(cq, "⏳ Processing your order..."))
        if res[0] == "busy":
            ans(cq, "Your previous order is still processing. Please wait a moment.", True)
            return
        if res[0] == "apifail":
            _t, reason, price_, refunded = res
            u3, pl3, ref = db.user(uid), db.plan(plid_b), db.new_order_no()
            utext, wnote = api_fail_texts(u3, refunded, price_, ref, reason=reason, pl=pl3)
            safe(notify_key_failed, u3, pl3["pname"] if pl3 else "-", pl3["name"] if pl3 else "-", price_, "Wallet Balance", ref,
                 "Panel API: " + reason, wnote, paid=not refunded)
            send(chat, utext, KB([menu_btn()]))
            return
        if res[0] == "coupon":
            ans(cq, res[1], True)
            return
        if res[0] == "ok":
            db.cp_set(uid, 0, "")
            u2 = db.user(uid)
            sh(*order_screen(u2, res[1]))
            safe(notify_purchase, u2, res[1], "Wallet Balance")
            comm = db.pay_commission(uid, res[1]["price"])
            if comm:
                ru = db.user(comm[0])
                if ru:
                    send(ru["id"], f"{E('gift2')} Referral commission: you earned <b>{fmt(ru, comm[1])}</b> from a friend's purchase!")
            if res[2] <= int(db.get("low_stock", "3") or 3) and ADMIN_ID:
                send(ADMIN_ID, f"{E('box')} Low stock: <b>{esc(res[1]['product'])} · {esc(res[1]['plan'])}</b> has {res[2]} key(s) left.")
        elif res[0] == "bal":
            ans(cq, "Insufficient wallet balance. Add balance, or pay via UPI / Binance.", True)
            return
        elif res[0] == "stock":
            safe(notify_wallet_fail, u, plid_b, "Out of stock - the key could not be issued.")
            ans(cq, "❌ Sorry, this plan is Out of Stock now.", True)
            return
        else:
            ans(cq, "This item is no longer available.", True)
            return
    elif data == "noupd":
        ans(cq, "Update file link is not added yet.", True)
        return
    elif data == "addbal":
        db.kp_set(uid, "")
        sh(*addbal_screen(u))
    elif data.startswith("kp:"):
        k = data[3:]
        cur = db.kp_get(uid)
        mn, mx = int(db.get("min_dep", "1")), int(db.get("max_dep", "10000"))
        if k == "c":
            if not cur:
                ans(cq)
                return
            db.kp_set(uid, cur[:-1])
        elif k == "ok":
            amt = int(cur or 0)
            if amt < mn:
                ans(cq, f"Minimum deposit is {u['symbol']}{mn}", True)
                return
            db.kp_set(uid, "")
            ans(cq)
            sh(*topup_methods_screen(u, amt))
            return
        else:
            new = (cur + k).lstrip("0")
            if not new:
                ans(cq)
                return
            if int(new) > mx:
                ans(cq, f"Maximum deposit is {u['symbol']}{mx:,}", True)
                return
            db.kp_set(uid, new)
        sh(*addbal_screen(u))
    elif data.startswith("dp:"):
        d = db.dep_get(int(data[3:]))
        if not d or d["user_id"] != uid or d["status"] != "pending":
            ans(cq, "This deposit request is no longer active.", True)
            return
        db.st_set(uid, f"utr:{d['id']}")
        send(chat, f"{E('paid')} Send your <b>UTR / Transaction ID</b> (text) or a <b>payment screenshot</b> now.",
             KB([B("Cancel", cb=f"dc:{d['id']}", style="danger", ek="cancel")]))
    elif data.startswith("dc:"):
        db.dep_cancel(int(data[3:]), uid)
        db.st_set(uid, "")
        sh(*menu_screen(u))
    elif data == "hist":
        sh(*history_screen(u))
    elif data == "dl":
        rows = db.orders(uid)
        if not rows:
            ans(cq, "You have no keys yet.", True)
            return
        body = "\n".join(f"{o['order_no']} | {o['product']} | {o['plan']} | {o['price']} | {ist(o['created'])} | {o['key']}" for o in rows)
        S.post(API + "sendDocument", data={"chat_id": chat},
               files={"document": (f"keys_{uid}.txt", body.encode())}, timeout=60)
    elif data == "profile":
        sh(*profile_screen(u))
    elif data == "ref":
        sh(*ref_screen(u))
    elif data == "claim":
        amt = db.claim_ref(uid)
        if not amt:
            ans(cq, "No referral balance to claim.", True)
            return
        ans(cq, f"{u['symbol']}{amt:g} added to your wallet!", True)
        sh(*ref_screen(db.user(uid)))
        return
    elif data == "tut":
        sh(*tut_screen(u))
    elif data == "sup":
        sh(*sup_screen(u))
    ans(cq)


# ------------------------------------------------------------------ polling
_locks = {}


def process(u):
    try:
        src = u.get("message") or u.get("callback_query") or {}
        uid = (src.get("from") or {}).get("id", 0)
        cq = u.get("callback_query")
        tm = None
        if cq:
            # V22: if the action takes longer than 0.6s (or the user is waiting behind his previous tap),
            # the button's loading clock is stopped anyway, so Telegram never looks frozen
            tm = threading.Timer(0.6, ans, args=(cq,))
            tm.daemon = True
            tm.start()
        lock = _locks.setdefault(uid, threading.Lock())
        try:
            with lock:
                _dispatch(u)
        finally:
            if tm:
                tm.cancel()
            if cq:
                ans(cq)
    except Exception:
        traceback.print_exc()


def _dispatch(u):
    try:
        if "message" in u:
            on_message(u["message"])
        elif "callback_query" in u:
            on_cb(u["callback_query"])
    except Exception:
        traceback.print_exc()


# ------------------------------------------------------------------ runtime config (website: Bot Token tab)
_gen = {"n": 0}
STATUS = {"v": "starting"}


def load_config():
    """startup: a token / admin ID saved from the website wins over the environment values"""
    global TOKEN, API, ADMIN_ID
    t = db.get("bot_token").strip()
    if t:
        TOKEN = t
        API = f"https://api.telegram.org/bot{TOKEN}/"
    a = db.get("bot_admin_id").strip()
    if a.lstrip("-").isdigit():
        ADMIN_ID = int(a)


def check_token(token):
    """asks Telegram who this token is. Returns (ok, username, message)"""
    token = (token or "").strip()
    if ":" not in token:
        return False, "", "This does not look like a bot token (it must look like 123456789:AA...)."
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/getMe", timeout=20).json()
    except Exception as e:
        return False, "", f"Could not reach Telegram: {e}"
    if not r.get("ok"):
        return False, "", "Telegram rejected this token: " + str(r.get("description", "invalid token"))
    return True, r["result"].get("username", ""), "ok"


def set_token(token):
    """switch the running bot to a new token immediately (no redeploy). Returns (ok, message)"""
    global TOKEN, API
    ok, uname, msg = check_token(token)
    if not ok:
        return False, msg
    token = token.strip()
    db.put("bot_token", token)
    TOKEN = token
    API = f"https://api.telegram.org/bot{TOKEN}/"
    BOT_USERNAME["v"] = uname
    start_polling()
    return True, f"Connected: @{uname}. The bot is running with the new token now."


def set_admin(new_id):
    """change the admin Telegram ID immediately. Returns (ok, message)"""
    global ADMIN_ID
    s = str(new_id).strip()
    if not s.isdigit() or int(s) <= 0:
        return False, "Admin ID must be a number (your Telegram user ID)."
    ADMIN_ID = int(s)
    db.put("bot_admin_id", s)
    r = api("sendMessage", chat_id=ADMIN_ID, text="✅ You are now the admin of this bot.")
    if r.get("ok"):
        return True, "Admin ID changed. A confirmation was sent to the new admin."
    return True, ("Admin ID saved, but Telegram could not message that ID (" + str(r.get("description", "")) +
                  "). Open the bot with that account and press /start once.")


def set_bot_display_name(name):
    """changes the name people see on the bot's Telegram profile (best effort)"""
    r = api("setMyName", name=name[:64])
    return bool(r.get("ok")), str(r.get("description", ""))


def start_polling():
    _gen["n"] += 1
    threading.Thread(target=poll_loop, args=(_gen["n"],), daemon=True).start()


def poll_loop(gen):
    pool = ThreadPoolExecutor(max_workers=64)
    offset = 0
    announced = False
    while gen == _gen["n"]:
        if not TOKEN:
            STATUS["v"] = "no token - add it on the website (Bot Token tab)"
            time.sleep(3)
            continue
        url = API
        try:
            r = S.post(url + "getUpdates", data={"offset": offset, "timeout": 50,
                       "allowed_updates": json.dumps(["message", "callback_query"])}, timeout=70).json()
        except Exception as e:
            print("poll error:", e)
            time.sleep(3)
            continue
        if gen != _gen["n"]:
            return                      # token was changed while waiting: drop old updates, this loop ends
        if not r.get("ok"):
            STATUS["v"] = "Telegram error: " + str(r.get("description", ""))
            time.sleep(5)               # e.g. 401 invalid / revoked token: wait for a new one from the website
            continue
        if not announced:
            me = api("getMe").get("result", {})
            BOT_USERNAME["v"] = me.get("username", BOT_USERNAME["v"])
            STATUS["v"] = "running as @" + BOT_USERNAME["v"]
            print("Bot started:", BOT_USERNAME["v"])
            api("deleteWebhook")
            announced = True
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            pool.submit(process, u)


def run():
    load_config()
    start_polling()
    while True:                         # keep the main thread alive (web server + workers run in threads)
        time.sleep(3600)
