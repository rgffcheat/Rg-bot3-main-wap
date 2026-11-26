"""
V20 - RGAPI: your resellers / users connect THEIR bot or website to YOUR shop with an API token.

API (header  X-API-Key: <token>) - exactly the contract that panel.py (the "Panel API" tab of every RG bot) already speaks:
  GET  /api/v1/connect        -> {"connected": true, "username": .., "balance": ..}
  GET  /api/v1/balance        -> {"balance": ..}
  GET  /api/v1/products       -> {"products": [{"product_id", "name", "plans": [{"plan_id", "name", "price"}]}]}   (?ids=1,2)
  POST /api/v1/purchase       -> {"success": true, "key": ".."}   body {"plan_id": N, "reference": "optional-unique-id"}
  GET  /api/v1/orders         -> last 50 API orders (with keys)
  GET  /api/v1/order/<id>     -> one API order

Portal (inside Telegram, no password):  /rgapi/login  ->  /rgapi/   (token, products + IDs, docs, orders)
Admin switches it on per user:  Website -> RGAPI  (or the "RGAPI System" card on a user's profile).
"""
import time, secrets, json, threading, traceback, html
from collections import deque
from flask import Blueprint, request, jsonify, session, redirect, Response
import db
import panel

bp = Blueprint("rgapi", __name__)

_hits = {}
_hl = threading.Lock()


def _bot():
    import bot
    return bot


def _secure():
    import secure
    return secure


# ------------------------------------------------------------------ tokens / switches
def new_token():
    return "rg_" + secrets.token_urlsafe(24)


def enable(uid):
    """turn RGAPI on for a user (creates the token the first time). Returns the token."""
    with db.conn() as c:
        r = c.execute("SELECT api_token FROM users WHERE id=?", (uid,)).fetchone()
        if not r:
            return None
        tok = r["api_token"] or new_token()
        c.execute("UPDATE users SET api_on=1, api_token=? WHERE id=?", (tok, uid))
    return tok


def disable(uid):
    with db.conn() as c:
        c.execute("UPDATE users SET api_on=0 WHERE id=?", (uid,))


def regen(uid):
    tok = new_token()
    with db.conn() as c:
        c.execute("UPDATE users SET api_token=? WHERE id=?", (tok, uid))
    return tok


def enabled_users():
    with db.conn() as c:
        return c.execute("""SELECT u.*, (SELECT COUNT(*) FROM orders o WHERE o.user_id=u.id AND o.src='api') api_orders,
                            (SELECT COALESCE(SUM(price),0) FROM orders o WHERE o.user_id=u.id AND o.src='api') api_spent
                            FROM users u WHERE u.api_on=1 ORDER BY u.api_last DESC, u.joined DESC""").fetchall()


def spendable(u):
    """wallet money that can really be spent (refund hold needs admin approval first)"""
    return round(max(float(u["balance"] or 0) - db.hold_of(u), 0.0), 2)


# ------------------------------------------------------------------ helpers
def _err(msg, code=400, **extra):
    d = {"success": False, "error": msg}
    d.update(extra)
    return jsonify(d), code


def _limited(key, limit, window=60):
    now = time.time()
    with _hl:
        q = _hits.setdefault(key, deque())
        while q and q[0] < now - window:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
        if len(_hits) > 5000:
            for k in [k for k, v in _hits.items() if not v or v[-1] < now - window]:
                _hits.pop(k, None)
    return False


def _ip():
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?")[:45]


def _auth():
    """-> (user row, None) or (None, error response)"""
    tok = (request.headers.get("X-API-Key") or "").strip()
    if not tok:
        a = request.headers.get("Authorization", "")
        if a.lower().startswith("bearer "):
            tok = a[7:].strip()
    if not tok:
        return None, _err("Missing API token. Send it in the X-API-Key header.", 401)
    with db.conn() as c:
        u = c.execute("SELECT * FROM users WHERE api_token=?", (tok,)).fetchone()
    if not u:
        return None, _err("Invalid API token.", 401)
    if not u["api_on"]:
        return None, _err("API access is turned off for this account. Contact the shop owner.", 403)
    if u["banned"]:
        return None, _err("This account is banned.", 403)
    if _limited("g" + tok, 180):
        return None, _err("Too many requests. Slow down (max 180 per minute).", 429)
    if time.time() - (u["api_last"] or 0) > 60:
        try:
            with db.conn() as c:
                c.execute("UPDATE users SET api_last=?, api_ip=? WHERE id=?", (int(time.time()), _ip(), u["id"]))
        except Exception:
            pass
    return u, None


def catalog(u, ids=None):
    """every active product + plan with THIS account's price (custom price > reseller price > user price)"""
    out = []
    for p in db.products(True):
        if ids and p["id"] not in ids:
            continue
        plans = []
        for pl in db.plans_of(p["id"], True):
            price = db.price_for(u, pl)
            if price <= 0:
                continue
            plans.append({"plan_id": pl["id"], "name": pl["name"], "price": price, "in_stock": (pl["stock"] or 0) > 0})
        if plans:
            out.append({"product_id": p["id"], "name": p["name"], "plans": plans})
    return out


def _order_dict(o):
    return {"order_id": o["order_no"], "product": o["product"], "plan": o["plan"], "price": o["price"],
            "key": o["key"], "created": o["created"]}


# ------------------------------------------------------------------ API endpoints
@bp.route("/api/v1/connect")
def api_connect():
    u, e = _auth()
    if e:
        return e
    return jsonify(connected=True, username=u["username"] or u["name"], balance=spendable(u), currency="INR",
                   account=("reseller" if u["role"] == "reseller" else "user"))


@bp.route("/api/v1/balance")
def api_balance():
    u, e = _auth()
    if e:
        return e
    return jsonify(balance=spendable(u), currency="INR", refund_hold=db.hold_of(u))


@bp.route("/api/v1/products")
def api_products():
    u, e = _auth()
    if e:
        return e
    ids = {int(x) for x in request.args.get("ids", "").split(",") if x.strip().isdigit()}
    return jsonify(products=catalog(u, ids or None), currency="INR")


@bp.route("/api/v1/orders")
def api_orders():
    u, e = _auth()
    if e:
        return e
    with db.conn() as c:
        rows = c.execute("SELECT * FROM orders WHERE user_id=? AND src='api' ORDER BY id DESC LIMIT 50", (u["id"],)).fetchall()
    return jsonify(orders=[_order_dict(o) for o in rows])


@bp.route("/api/v1/order/<order_no>")
def api_order(order_no):
    u, e = _auth()
    if e:
        return e
    with db.conn() as c:
        o = c.execute("SELECT * FROM orders WHERE user_id=? AND src='api' AND order_no=?", (u["id"], order_no[:40])).fetchone()
    if not o:
        return _err("Order not found.", 404)
    return jsonify(success=True, **_order_dict(o))


def _idem_begin(uid, ref):
    """-> None (go on) | ('done', order row) | ('busy', state)"""
    if not ref:
        return None
    with db.conn() as c:
        cur = c.execute("INSERT OR IGNORE INTO api_orders(user_id, ref, created) VALUES(?,?,?)", (uid, ref, int(time.time())))
        if cur.rowcount:
            return None
        r = c.execute("SELECT * FROM api_orders WHERE user_id=? AND ref=?", (uid, ref)).fetchone()
        if r and r["state"] == "done" and r["order_no"]:
            o = c.execute("SELECT * FROM orders WHERE order_no=?", (r["order_no"],)).fetchone()
            if o:
                return ("done", o)
        return ("busy", r["state"] if r else "working")


def _idem_end(uid, ref, state, order_no=""):
    if not ref:
        return
    with db.conn() as c:
        if state == "failed":                       # nothing was bought -> the same reference may be used again
            c.execute("DELETE FROM api_orders WHERE user_id=? AND ref=?", (uid, ref))
        else:
            c.execute("UPDATE api_orders SET state=?, order_no=? WHERE user_id=? AND ref=?", (state, order_no, uid, ref))


def _alert(u, pl, price, reason, wallet_note, definite):
    b = _bot()
    try:
        b.notify_key_failed(u, pl["pname"] if pl else "-", pl["name"] if pl else "-", price, "RGAPI (reseller API)", "-",
                            reason, wallet_note, paid=False, force=not definite)
    except Exception:
        traceback.print_exc()


@bp.route("/api/v1/purchase", methods=["POST"])
def api_purchase():
    u, e = _auth()
    if e:
        return e
    if _limited("p" + u["api_token"], 60):
        return _err("Too many purchases. Slow down (max 60 per minute).", 429)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        body = {}
    raw = body.get("plan_id", request.form.get("plan_id"))
    try:
        plid = int(raw)
    except (TypeError, ValueError):
        return _err("plan_id is required (a number).", 400)
    ref = str(body.get("reference") or request.headers.get("Idempotency-Key") or request.form.get("reference") or "").strip()[:64]
    uid = u["id"]
    pl = db.plan(plid)
    if not pl or not pl["active"] or not pl["pactive"]:
        return _err("Plan not found or not available.", 404)
    if (pl["stock"] or 0) <= 0:                     # V22: out of stock (no keys, or admin marked it Out of Stock)
        return _err("Out of stock.", 409)
    price = db.price_for(u, pl)
    if price <= 0:
        return _err("Plan not found or not available.", 404)
    dup = _idem_begin(uid, ref)                 # same reference again -> answer with the first result, never buy twice
    if dup:
        if dup[0] == "done":
            return jsonify(success=True, duplicate=True, key=dup[1]["key"], order_id=dup[1]["order_no"], product=dup[1]["product"],
                           plan=dup[1]["plan"], price=dup[1]["price"], balance=spendable(db.user(uid)))
        return _err("An order with this reference is already being processed. Do not retry; check /api/v1/orders later.", 409)
    free = spendable(u)
    if free < price:
        _idem_end(uid, ref, "failed")
        if u["balance"] >= price:
            return _err("Your balance contains a refund that is waiting for the owner's approval. Price %.2f, spendable %.2f." % (price, free), 402)
        return _err("Insufficient balance. Price %.2f, your balance %.2f." % (price, free), 402)

    res, unknown = None, False
    try:
        if pl["api_plan_id"]:                     # product bought from the main panel: reserve money -> buy key -> refund if refused
            r = db.api_reserve(uid, plid)
            if r[0] != "go":
                res = r
            else:
                _, price, plrow = r
                try:
                    key = panel.buy(plrow["api_plan_id"])
                except panel.PanelError as ex:
                    if ex.definite:
                        db.add_balance(uid, price)
                        _idem_end(uid, ref, "failed")
                        _alert(u, pl, price, ex.msg, "Nothing was charged (refunded automatically)", True)
                        return _err("Could not deliver the key right now (%s). Nothing was charged." % ex.msg, 503, refunded=True)
                    unknown = True
                    _idem_end(uid, ref, "unknown")
                    _alert(u, pl, price, ex.msg, "NOT refunded automatically - check the panel order history", False)
                    return _err("Your order is being processed. Do NOT buy again; check /api/v1/orders in a few minutes.", 500, refunded=False)
                res = db.api_finish_ok(uid, plrow, price, key)
        else:
            res = db.buy(uid, plid)
    except Exception as ex:
        traceback.print_exc()
        _idem_end(uid, ref, "unknown")
        _alert(u, pl, price, "Unexpected error: %s" % str(ex)[:120], "Check the wallet and the panel history", False)
        return _err("Your order is being processed. Do NOT buy again; check /api/v1/orders in a few minutes.", 500)

    if res[0] == "ok":
        o = res[1]
        try:
            with db.conn() as c:
                c.execute("UPDATE orders SET src='api' WHERE order_no=?", (o["order_no"],))
                c.execute("UPDATE users SET api_cnt=COALESCE(api_cnt,0)+1 WHERE id=?", (uid,))
        except Exception:
            traceback.print_exc()
        _idem_end(uid, ref, "done", o["order_no"])
        fresh = db.user(uid)
        threading.Thread(target=lambda: _bot().safe(_bot().notify_purchase, fresh, o, "RGAPI (reseller API)"), daemon=True).start()
        return jsonify(success=True, key=o["key"], order_id=o["order_no"], product=o["product"], plan=o["plan"],
                       price=o["price"], balance=spendable(fresh))
    _idem_end(uid, ref, "failed")
    if res[0] == "bal":
        return _err("Insufficient balance. Price %.2f." % res[1], 402)
    if res[0] == "stock":
        return _err("Out of stock.", 409)
    if res[0] == "refund":
        return _err("Plan is not available.", 404)
    return _err("Plan not found or not available.", 404)


# ------------------------------------------------------------------ portal (opened from the bot, signs in by Telegram)
def _portal_user():
    uid = session.get("rg_uid")
    if not uid:
        return None
    u = db.user(uid)
    if not u or not u["api_on"] or u["banned"]:
        session.pop("rg_uid", None)
        return None
    return u


def _csrf():
    if "rg_csrf" not in session:
        session["rg_csrf"] = secrets.token_hex(16)
    return session["rg_csrf"]


def base_url():
    b = _bot()
    return (b.PUBLIC_URL or request.host_url.rstrip("/")).rstrip("/")


@bp.route("/rgapi/login")
def rg_login():
    return Response(LOGIN, mimetype="text/html")


@bp.route("/rgapi/auth", methods=["POST"])
def rg_auth():
    d = (request.get_json(silent=True) or {}).get("d", "")
    uid = _secure().verify_init_data(d)
    if not uid:
        return jsonify(ok=False, err="Telegram could not verify you. Open this page from the bot.")
    u = db.user(uid)
    if not u or not u["api_on"] or u["banned"]:
        return jsonify(ok=False, err="RGAPI is not active on your account. Contact the shop owner.")
    session["rg_uid"] = uid
    session.permanent = True
    return jsonify(ok=True)


@bp.route("/rgapi/regen", methods=["POST"])
def rg_regen():
    u = _portal_user()
    if not u:
        return redirect("/rgapi/login")
    if request.form.get("csrf", "") != session.get("rg_csrf", "x"):
        return "Bad request", 400
    regen(u["id"])
    return redirect("/rgapi/#connect")


@bp.route("/rgapi/")
@bp.route("/rgapi")
def rg_home():
    u = _portal_user()
    if not u:
        return redirect("/rgapi/login")
    with db.conn() as c:
        rows = c.execute("SELECT * FROM orders WHERE user_id=? AND src='api' ORDER BY id DESC LIMIT 25", (u["id"],)).fetchall()
        st = c.execute("SELECT COUNT(*) n, COALESCE(SUM(price),0) s FROM orders WHERE user_id=? AND src='api'", (u["id"],)).fetchone()
    data = {"url": base_url(), "token": u["api_token"], "name": u["name"], "role": u["role"], "balance": spendable(u),
            "hold": db.hold_of(u), "csrf": _csrf(), "n_orders": st["n"], "spent": st["s"],
            "products": catalog(u), "orders": [_order_dict(o) for o in rows]}
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return Response(DASH.replace("@@DATA@@", blob), mimetype="text/html")


# ================================================================== pages
LOGIN = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>RGAPI</title><script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>body{margin:0;background:radial-gradient(900px 500px at 50% -10%,#2b2f77 0,#070a12 60%);color:#e9edf8;font-family:Inter,system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center}
.c{padding:28px}.s{width:42px;height:42px;border:4px solid #222b41;border-top-color:#7c83ff;border-radius:50%;margin:0 auto 16px;animation:r .9s linear infinite}@keyframes r{to{transform:rotate(360deg)}}
.l{font-size:22px;font-weight:800;letter-spacing:.5px;margin-bottom:18px}.l b{background:linear-gradient(90deg,#8b9cff,#22d3ee);-webkit-background-clip:text;background-clip:text;color:transparent}</style></head>
<body><div class="c"><div class="l"><b>RG</b>API</div><div class="s" id="sp"></div><div id="m">Signing you in…</div></div>
<script>
(function(){var m=document.getElementById('m'),sp=document.getElementById('sp');
function fail(t){sp.style.display='none';m.innerHTML='🚫 '+t}
try{var w=window.Telegram&&Telegram.WebApp;if(!w||!w.initData){fail('Open this page from the bot: My Profile → RGAPI System.');return}
w.ready();w.expand&&w.expand();
fetch('/rgapi/auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({d:w.initData})})
.then(function(r){return r.json()}).then(function(j){if(j.ok){location.replace('/rgapi/')}else{fail(j.err||'Not allowed.')}})
.catch(function(){fail('Network error. Try again.')})}catch(e){fail('Error. Try again.')}})();
</script></body></html>"""


DASH = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#070a12">
<title>RGAPI</title><script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#070a12;--card:#111728;--card2:#171f35;--line:#242e4a;--tx:#eaeefb;--mu:#8e99b8;--ac:#7c83ff;--ac2:#22d3ee;--ok:#34d399;--no:#f87171;--wt:#fbbf24}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}html{scroll-behavior:smooth}
body{margin:0;background:radial-gradient(1000px 520px at 50% -140px,#2a2f7a55 0,transparent 70%),var(--bg);color:var(--tx);font-family:Inter,system-ui,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.5;padding-bottom:env(safe-area-inset-bottom)}
.wrap{max-width:860px;margin:0 auto;padding:18px 16px 70px}
.top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:16px}
.logo{font-size:22px;font-weight:800;letter-spacing:.5px}.logo b{background:linear-gradient(90deg,#8b9cff,#22d3ee);-webkit-background-clip:text;background-clip:text;color:transparent}
.pill{display:inline-flex;align-items:center;gap:6px;background:#34d39922;color:var(--ok);border:1px solid #34d39944;padding:4px 11px;border-radius:99px;font-size:12px;font-weight:600}
.pill i{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 0 #34d399aa;animation:pu 1.8s infinite}@keyframes pu{70%{box-shadow:0 0 0 7px #34d39900}}
.hero{background:linear-gradient(135deg,#3a40b8 0,#2563eb 55%,#0891b2 100%);border-radius:22px;padding:20px;position:relative;overflow:hidden;box-shadow:0 18px 40px #2b30a066}
.hero:after{content:"";position:absolute;right:-50px;top:-50px;width:190px;height:190px;border-radius:50%;background:#ffffff14}
.hero small{opacity:.8;font-size:12.5px}.hero h2{margin:2px 0 14px;font-size:20px;font-weight:800}
.bal{font-size:34px;font-weight:800;letter-spacing:.3px;line-height:1.1}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}
.st{background:#00000030;border-radius:14px;padding:10px 12px;backdrop-filter:blur(4px)}.st b{display:block;font-size:17px}.st span{font-size:11.5px;opacity:.8}
.tabs{display:flex;gap:6px;overflow-x:auto;margin:18px -4px 14px;padding:4px;position:sticky;top:0;z-index:20;background:linear-gradient(var(--bg) 70%,transparent);scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{flex:none;background:var(--card);border:1px solid var(--line);color:var(--mu);padding:9px 16px;border-radius:12px;font-weight:600;font-size:13.5px;cursor:pointer;font-family:inherit;transition:.15s}
.tab.on{background:linear-gradient(135deg,var(--ac),#5b6cff);color:#fff;border-color:transparent;box-shadow:0 8px 20px #6366f155}
.sec{display:none;animation:fi .25s ease}.sec.on{display:block}@keyframes fi{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin-bottom:14px}
.card h3{margin:0 0 4px;font-size:15.5px;font-weight:700}.mu{color:var(--mu);font-size:13px}
.fld{margin-top:12px}.fld label{display:block;color:var(--mu);font-size:12px;margin-bottom:5px;font-weight:600;text-transform:uppercase;letter-spacing:.6px}
.box{display:flex;gap:8px;align-items:stretch}
.val{flex:1;min-width:0;background:#0a0f1d;border:1px solid var(--line);border-radius:12px;padding:11px 12px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn{background:var(--card2);border:1px solid var(--line);color:var(--tx);border-radius:12px;padding:0 14px;font-weight:600;font-size:13px;cursor:pointer;font-family:inherit;flex:none;min-height:42px;transition:.12s}
.btn:active{transform:scale(.96)}.btn.pri{background:linear-gradient(135deg,var(--ac),#5b6cff);border-color:transparent;color:#fff}.btn.red{color:var(--no);border-color:#f8717155}
.steps{counter-reset:s;margin:10px 0 0;padding:0;list-style:none}
.steps li{counter-increment:s;position:relative;padding:4px 0 12px 40px;color:#c9d1ea}
.steps li:before{content:counter(s);position:absolute;left:0;top:2px;width:28px;height:28px;border-radius:9px;background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;font-weight:800;display:flex;align-items:center;justify-content:center;font-size:13px}
.steps b{color:#fff}.tip{background:#7c83ff14;border:1px solid #7c83ff40;border-radius:12px;padding:10px 12px;color:#c8cdf5;font-size:13px;margin-top:6px}
.srch{width:100%;background:var(--card);border:1px solid var(--line);color:var(--tx);border-radius:14px;padding:12px 14px;font-size:14px;outline:0;font-family:inherit;margin-bottom:12px}
.srch:focus{border-color:var(--ac);box-shadow:0 0 0 3px #7c83ff33}
.pr{background:var(--card);border:1px solid var(--line);border-radius:16px;margin-bottom:10px;overflow:hidden}
.ph{display:flex;align-items:center;gap:10px;padding:13px 14px;cursor:pointer}.ph b{flex:1;min-width:0;font-size:14.5px}
.id{background:#7c83ff22;color:#aab1ff;border:1px solid #7c83ff44;border-radius:8px;padding:2px 8px;font-size:12px;font-weight:700;font-family:ui-monospace,Menlo,monospace;cursor:pointer;white-space:nowrap}
.cv{color:var(--mu);transition:.2s}.pr.open .cv{transform:rotate(90deg)}
.pb{display:none;border-top:1px solid var(--line);padding:4px 14px 10px}.pr.open .pb{display:block}
.pl{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px dashed #242e4a}.pl:last-child{border:0}
.pl .n{flex:1;min-width:0}.pl .n small{display:block;color:var(--mu);font-size:11.5px}.pl .p{font-weight:800;color:#7ee8c3;white-space:nowrap}
.tag{font-size:10.5px;padding:1px 7px;border-radius:99px;font-weight:700}.tag.ok{background:#34d39922;color:var(--ok)}.tag.no{background:#f8717122;color:var(--no)}
.ep{border:1px solid var(--line);border-radius:14px;margin-bottom:10px;overflow:hidden;background:var(--card)}
.eh{display:flex;align-items:center;gap:10px;padding:12px 14px;flex-wrap:wrap}.eh code{font-size:13.5px;font-weight:700}.eh span.d{color:var(--mu);font-size:12.5px;flex-basis:100%}
.m{font-size:11px;font-weight:800;padding:3px 9px;border-radius:7px;letter-spacing:.5px}.m.get{background:#22d3ee22;color:#22d3ee}.m.post{background:#34d39922;color:#34d399}
pre{margin:0;background:#080c18;border-top:1px solid var(--line);padding:12px 14px;overflow-x:auto;font-size:12.3px;line-height:1.55;color:#cfe3ff;font-family:ui-monospace,Menlo,Consolas,monospace;position:relative}
.lang{display:flex;gap:6px;margin:6px 0 10px;flex-wrap:wrap}.lang .tab{padding:6px 13px;font-size:12.5px}
.cp{position:absolute;right:8px;top:8px;background:#ffffff14;border:0;color:#cbd5ff;border-radius:8px;padding:4px 9px;font-size:11.5px;cursor:pointer}
table{width:100%;border-collapse:collapse;font-size:13px}th{color:var(--mu);text-align:left;font-weight:600;padding:6px 8px;font-size:12px}td{padding:8px;border-top:1px solid var(--line);vertical-align:top}
.tw{overflow-x:auto}.ord{border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:10px;background:var(--card)}
.ord .r{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}.ord code{word-break:break-all;color:#bfe9ff}
.empty{text-align:center;color:var(--mu);padding:30px 10px}
#toast{position:fixed;left:50%;bottom:calc(24px + env(safe-area-inset-bottom));transform:translate(-50%,30px);background:#1c2640;border:1px solid var(--line);color:#fff;padding:10px 18px;border-radius:99px;opacity:0;pointer-events:none;transition:.25s;font-weight:600;z-index:99}
#toast.show{opacity:1;transform:translate(-50%,0)}
</style></head><body><div class="wrap">
<div class="top"><div class="logo"><b>RG</b>API</div><span class="pill"><i></i>Active</span></div>
<div class="hero"><small>Welcome back</small><h2 id="nm">-</h2><small>Available balance</small><div class="bal" id="bal">₹0.00</div>
<div class="stats"><div class="st"><b id="s1">0</b><span>API orders</span></div><div class="st"><b id="s2">₹0</b><span>Spent via API</span></div><div class="st"><b id="s3">0</b><span>Products</span></div></div></div>
<div class="tabs" id="tabs"><button class="tab on" data-t="connect">🔌 Connect</button><button class="tab" data-t="products">🛍️ Products</button><button class="tab" data-t="docs">📘 API Docs</button><button class="tab" data-t="orders">🧾 Orders</button></div>

<div class="sec on" id="connect">
<div class="card"><h3>Your API credentials</h3><div class="mu">Keep your token private. Anyone with it can buy from your balance.</div>
<div class="fld"><label>Server URL</label><div class="box"><div class="val" id="vu"></div><button class="btn pri" data-c="url">Copy</button></div></div>
<div class="fld"><label>API token</label><div class="box"><div class="val" id="vt"></div><button class="btn" id="eye">👁</button><button class="btn pri" data-c="token">Copy</button></div></div>
<form method="post" action="/rgapi/regen" onsubmit="return confirm('Create a NEW token? The old token stops working immediately - update it in your bot / website.')"><input type="hidden" name="csrf" id="cs"><button class="btn red" style="margin-top:12px;width:100%">🔄 Regenerate token</button></form></div>
<div class="card"><h3>Connect your RG bot in 1 minute</h3>
<ol class="steps"><li>Open your bot's admin website → <b>Panel API</b>.</li>
<li>Paste the <b>Server URL</b> and the <b>API token</b> above, then press <b>Save &amp; Connect</b>. You will see <b>Connect successful</b>.</li>
<li>Press <b>Check Balance</b> to see your balance here, then <b>Show Products</b>.</li>
<li>Tick the products you want and press <b>Add selected</b> (or <b>Add all</b>).</li>
<li>Set your <b>Reseller %</b> and <b>User %</b> and press <b>Save &amp; apply</b>. Your selling price = your price here + your %.</li></ol>
<div class="tip">💡 Example: your price ₹100 and 25% → your customers pay ₹125. New plans and price changes sync automatically.</div></div>
<div class="card"><h3>Own website or custom bot?</h3><div class="mu">Use the <b>API Docs</b> tab: three simple calls (balance, products, purchase) with copy-ready code in cURL, Python, PHP and Node.js.</div></div>
</div>

<div class="sec" id="products"><input class="srch" id="q" placeholder="🔎 Search product name or ID"><div id="plist"></div></div>

<div class="sec" id="docs">
<div class="card"><h3>Authentication</h3><div class="mu">Send your token in every request header:</div><div style="margin-top:8px"><pre style="border:1px solid var(--line);border-radius:12px">X-API-Key: YOUR_API_TOKEN</pre></div>
<div class="mu" style="margin-top:8px">Base URL: <code id="bu"></code> · Prices and balance are in <b>INR (₹)</b> · Responses are JSON.</div></div>
<div id="eps"></div>
<div class="card"><h3>Code examples</h3><div class="lang" id="lang"></div><div id="code"></div></div>
<div class="card"><h3>Errors</h3><div class="tw"><table><tr><th>HTTP</th><th>Meaning</th></tr>
<tr><td>401</td><td>Missing or invalid token</td></tr><tr><td>402</td><td>Insufficient balance</td></tr><tr><td>403</td><td>API turned off / account banned</td></tr>
<tr><td>404</td><td>Plan not found or not available</td></tr><tr><td>409</td><td>Out of stock, or the same <code>reference</code> is already processing</td></tr>
<tr><td>429</td><td>Too many requests</td></tr><tr><td>503</td><td>Key could not be delivered right now. <b>Nothing was charged.</b> Safe to try again.</td></tr>
<tr><td>500</td><td>Order is being processed. <b>Do not buy again</b>; check <code>/api/v1/orders</code> later.</td></tr></table></div>
<div class="tip">✅ Always send a unique <code>reference</code> with every purchase (for example your own order number). If your request times out you can send it again: the same reference can never buy twice.</div></div>
</div>

<div class="sec" id="orders"><div id="olist"></div></div>
</div><div id="toast"></div>
<script id="d" type="application/json">@@DATA@@</script>
<script>
(function(){
var D=JSON.parse(document.getElementById('d').textContent);
try{var w=Telegram.WebApp;w.ready();w.expand&&w.expand();w.setHeaderColor&&w.setHeaderColor('#070a12');w.setBackgroundColor&&w.setBackgroundColor('#070a12')}catch(e){}
var $=function(i){return document.getElementById(i)};
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function money(x){return '₹'+Number(x||0).toFixed(2)}
function toast(t){var e=$('toast');e.textContent=t;e.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(function(){e.classList.remove('show')},1500)}
function copy(t){function ok(){toast('Copied ✓')}if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(ok,fb)}else fb();function fb(){var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();try{document.execCommand('copy');ok()}catch(e){toast('Copy failed')}a.remove()}}
$('nm').textContent=D.name+(D.role==='reseller'?' · Reseller':'');$('bal').textContent=money(D.balance);
$('s1').textContent=D.n_orders;$('s2').textContent=money(D.spent);$('s3').textContent=D.products.length;
$('vu').textContent=D.url;$('bu').textContent=D.url;$('cs').value=D.csrf;
var shown=false;function tok(){$('vt').textContent=shown?D.token:'•'.repeat(18)+D.token.slice(-4)}tok();
$('eye').onclick=function(){shown=!shown;tok()};
document.querySelectorAll('[data-c]').forEach(function(b){b.onclick=function(){copy(D[b.dataset.c])}});
document.querySelectorAll('.tab[data-t]').forEach(function(b){b.onclick=function(){show(b.dataset.t)}});
function show(t){document.querySelectorAll('.tab[data-t]').forEach(function(x){x.classList.toggle('on',x.dataset.t===t)});document.querySelectorAll('.sec').forEach(function(x){x.classList.toggle('on',x.id===t)});window.scrollTo({top:0})}
if(location.hash&&$(location.hash.slice(1)))show(location.hash.slice(1));
/* products */
function drawP(f){var h='';f=(f||'').toLowerCase();D.products.forEach(function(p){
 if(f&&p.name.toLowerCase().indexOf(f)<0&&String(p.product_id)!==f)return;
 h+='<div class="pr'+(f?' open':'')+'"><div class="ph"><b>'+esc(p.name)+'</b><span class="id" data-id="'+p.product_id+'">ID '+p.product_id+'</span><span class="cv">›</span></div><div class="pb">';
 p.plans.forEach(function(l){h+='<div class="pl"><div class="n">'+esc(l.name)+'<small>Plan ID <span class="id" data-id="'+l.plan_id+'">'+l.plan_id+'</span></small></div><span class="tag '+(l.in_stock?'ok':'no')+'">'+(l.in_stock?'In stock':'Out')+'</span><div class="p">'+money(l.price)+'</div></div>'});
 h+='</div></div>'});
 $('plist').innerHTML=h||'<div class="empty">No products found.</div>'}
drawP('');$('q').oninput=function(){drawP(this.value.trim())};
$('plist').onclick=function(e){var i=e.target.closest('.id');if(i){e.stopPropagation();copy(i.dataset.id);return}var h=e.target.closest('.ph');if(h)h.parentNode.classList.toggle('open')};
/* orders */
(function(){var h='';D.orders.forEach(function(o){h+='<div class="ord"><div class="r"><b>'+esc(o.product)+'</b><span style="color:#7ee8c3;font-weight:800">'+money(o.price)+'</span></div><div class="mu">'+esc(o.plan)+' · '+new Date(o.created*1000).toLocaleString()+'</div><div class="mu">Order <code>'+esc(o.order_id)+'</code></div><div style="margin-top:6px"><code>'+esc(o.key)+'</code></div><button class="btn" style="margin-top:8px;min-height:34px" data-k="'+esc(o.key)+'">Copy key</button></div>'});
 $('olist').innerHTML=h||'<div class="empty">No API orders yet.<br>Orders made through the API appear here.</div>'})();
$('olist').onclick=function(e){var b=e.target.closest('[data-k]');if(b)copy(b.dataset.k)};
/* docs */
var U=D.url,T=D.token,P=D.products.length&&D.products[0].plans.length?D.products[0].plans[0].plan_id:1;
var EP=[['get','/api/v1/connect','Check the connection','{"connected": true, "username": "myshop", "balance": 1250.5}'],
['get','/api/v1/balance','Your spendable balance (INR)','{"balance": 1250.5, "currency": "INR"}'],
['get','/api/v1/products','All products and plans with YOUR price. Optional: ?ids=1,2','{"products": [{"product_id": 3, "name": "Product name", "plans": [{"plan_id": 12, "name": "1 Day", "price": 90.0, "in_stock": true}]}]}'],
['post','/api/v1/purchase','Buy one key. Body: plan_id (required), reference (recommended, unique per order)','{"success": true, "key": "ABCD-1234-XXXX", "order_id": "WAL2026...", "price": 90.0, "balance": 1160.5}'],
['get','/api/v1/orders','Your last 50 API orders (with keys)','{"orders": [{"order_id": "WAL2026...", "product": "...", "plan": "...", "price": 90.0, "key": "..."}]}'],
['get','/api/v1/order/{order_id}','One order by its order_id','{"success": true, "order_id": "WAL2026...", "key": "..."}']];
$('eps').innerHTML=EP.map(function(x){return '<div class="ep"><div class="eh"><span class="m '+x[0]+'">'+x[0].toUpperCase()+'</span><code>'+x[1]+'</code><span class="d">'+x[2]+'</span></div><pre>'+esc(x[3])+'</pre></div>'}).join('');
var S={
'cURL':'# balance\ncurl -H "X-API-Key: '+T+'" '+U+'/api/v1/balance\n\n# buy a key\ncurl -X POST '+U+'/api/v1/purchase \\\n  -H "X-API-Key: '+T+'" \\\n  -H "Content-Type: application/json" \\\n  -d \'{"plan_id": '+P+', "reference": "my-order-1001"}\'',
'Python':'import requests\n\nBASE = "'+U+'"\nH = {"X-API-Key": "'+T+'"}\n\nprint(requests.get(BASE + "/api/v1/balance", headers=H, timeout=60).json())\n\nr = requests.post(BASE + "/api/v1/purchase", headers=H, timeout=90,\n                  json={"plan_id": '+P+', "reference": "my-order-1001"})\nj = r.json()\nif j.get("success"):\n    print("KEY:", j["key"])\nelse:\n    print("Error:", j.get("error"))',
'PHP':'<?php\n$base = "'+U+'";\n$ch = curl_init($base . "/api/v1/purchase");\ncurl_setopt_array($ch, [\n  CURLOPT_RETURNTRANSFER => true,\n  CURLOPT_POST => true,\n  CURLOPT_TIMEOUT => 90,\n  CURLOPT_HTTPHEADER => ["X-API-Key: '+T+'", "Content-Type: application/json"],\n  CURLOPT_POSTFIELDS => json_encode(["plan_id" => '+P+', "reference" => "my-order-1001"]),\n]);\n$j = json_decode(curl_exec($ch), true);\necho $j["success"] ? $j["key"] : $j["error"];',
'Node.js':'const BASE = "'+U+'";\nconst H = { "X-API-Key": "'+T+'", "Content-Type": "application/json" };\n\nconst r = await fetch(BASE + "/api/v1/purchase", {\n  method: "POST", headers: H,\n  body: JSON.stringify({ plan_id: '+P+', reference: "my-order-1001" }),\n});\nconst j = await r.json();\nconsole.log(j.success ? j.key : j.error);'};
var names=Object.keys(S),cur=names[0];
function drawC(){$('lang').innerHTML=names.map(function(n){return '<button class="tab'+(n===cur?' on':'')+'" data-l="'+n+'">'+n+'</button>'}).join('');
 $('code').innerHTML='<pre style="border:1px solid var(--line);border-radius:12px"><button class="cp">Copy</button>'+esc(S[cur])+'</pre>'}
drawC();$('lang').onclick=function(e){var b=e.target.closest('[data-l]');if(b){cur=b.dataset.l;drawC()}};
$('code').onclick=function(e){if(e.target.closest('.cp'))copy(S[cur])};
})();
</script></body></html>"""
