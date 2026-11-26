import os, time, secrets, hmac
from flask import Flask, request, session, redirect, url_for, render_template_string, flash, Response, g, jsonify
from datetime import datetime, timezone, timedelta
from jinja2 import DictLoader
import io, csv, threading
import json
import db, bot, backup, gateway, panel, secure, rgapi
try:
    import segno
except Exception:
    segno = None

app = Flask(__name__)
app.register_blueprint(rgapi.bp)          # V20: RGAPI (/api/v1/* and /rgapi/*) has its own token / Telegram sign-in
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
ADMIN_USER = os.getenv("ADMIN_USER") or "RGCHEAT"
ADMIN_PASS = os.getenv("ADMIN_PASS") or "909090"
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.getenv("RENDER_EXTERNAL_URL", "").startswith("https"),
                  PERMANENT_SESSION_LIFETIME=12 * 3600, MAX_CONTENT_LENGTH=60 * 1024 * 1024)
FAILS = {}  # ip -> [count, locked_until]


def client_ip():
    return (request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "?")


@app.after_request
def secure_headers(r):
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "no-referrer"
    r.headers["Cache-Control"] = "no-store"
    if getattr(g, "newdev", None):
        r.set_cookie("rg_dev", g.newdev, max_age=365 * 86400, httponly=True, samesite="Lax",
                     secure=os.getenv("RENDER_EXTERNAL_URL", "").startswith("https"))
    return r

BASE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0a0c12">
<title>{{ title or 'RG Admin' }}</title><style>
:root{--bg:#090b11;--side:#0e1220;--card:#131826;--card2:#182036;--line:#222b41;--tx:#e9edf8;--mu:#8a94ae;--ac:#6366f1;--ac2:#8b5cf6;--ok:#34d399;--no:#f87171;--wt:#fbbf24}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--tx);font-family:Inter,system-ui,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.45;-webkit-text-size-adjust:100%}
a{color:inherit}.app{display:flex;min-height:100vh}
.side{width:244px;flex:none;background:var(--side);border-right:1px solid var(--line);position:sticky;top:0;height:100vh;overflow-y:auto;padding:16px 12px;z-index:30}
.brand{display:flex;align-items:center;gap:10px;padding:6px 8px 16px;font-weight:800;font-size:16px;letter-spacing:.3px}
.brand i{font-style:normal;width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--ac),var(--ac2));display:flex;align-items:center;justify-content:center;font-size:17px}
.grp{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:var(--mu);padding:14px 10px 6px;opacity:.8}
.side a.nl{display:flex;align-items:center;gap:10px;color:#b7bfd6;text-decoration:none;padding:9px 10px;border-radius:10px;font-size:14px;margin-bottom:2px}
.side a.nl:hover{background:var(--card2);color:#fff}.side a.nl.on{background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;font-weight:600;box-shadow:0 6px 18px #6366f144}
.side a.nl span{width:22px;text-align:center}.side .out{margin-top:16px;border-top:1px solid var(--line);padding-top:10px}
.content{flex:1;min-width:0}.top{display:none}
main{max-width:1020px;margin:0 auto;padding:22px 20px 90px}
h1{font-size:22px;margin:2px 0 16px;font-weight:800;letter-spacing:.2px}h3{margin:0 0 10px;font-size:15px;font-weight:700}
.ph{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:14px}.ph h1{margin:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;margin-bottom:16px;box-shadow:0 1px 0 #ffffff08 inset}
label{display:block;color:var(--mu);font-size:12.5px;margin:12px 0 5px;font-weight:500}
textarea,input,select{width:100%;padding:10px 12px;background:#0c101c;border:1px solid var(--line);border-radius:10px;color:var(--tx);font-size:14px;font-family:inherit;outline:0;transition:border .15s,box-shadow .15s}
textarea{font-family:ui-monospace,Menlo,Consolas,monospace}
textarea:focus,input:focus,select:focus{border-color:var(--ac);box-shadow:0 0 0 3px #6366f133}
input[type=checkbox]{width:18px!important;height:18px;padding:0;accent-color:var(--ac);vertical-align:middle;flex:none}
button{background:linear-gradient(135deg,var(--ac),var(--ac2));color:#fff;border:0;padding:10px 18px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;margin-top:12px;font-family:inherit;transition:transform .08s,opacity .15s,filter .15s}
button:hover{filter:brightness(1.1)}button:active{transform:scale(.97)}button[disabled]{opacity:.55;cursor:wait}
button.red{background:linear-gradient(135deg,#ef4444,#dc2626)}button.sec{background:var(--card2);border:1px solid var(--line);color:var(--tx)}button.grn{background:linear-gradient(135deg,#10b981,#059669)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}.grid .card{margin:0}
.stat{position:relative;overflow:hidden}.stat b{font-size:28px;display:block;font-weight:800;margin-top:2px}.stat span{color:var(--mu);font-size:12.5px}
.stat i{font-style:normal;position:absolute;right:14px;top:12px;font-size:24px;opacity:.9}
table{width:100%;border-collapse:collapse;font-size:13px}th{color:var(--mu);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.6px}
td,th{padding:10px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}tr:last-child td{border-bottom:0}tbody tr:hover td,table tr:hover td{background:#ffffff05}.tw{overflow-x:auto}
.mu{color:var(--mu);font-size:13px}.bd{padding:3px 10px;border-radius:99px;background:var(--card2);font-size:12px;display:inline-block}
.ok{color:var(--ok)}.no{color:var(--no)}.wt{color:var(--wt)}a.lk{color:#8b9dff;text-decoration:none}a.lk:hover{text-decoration:underline}
.bd.ok{background:#10b9811f}.bd.no{background:#ef44441f}.bd.wt{background:#fbbf2420}
.row{display:flex;gap:8px;align-items:center}.row input{flex:1}
.flash{display:none}
#toasts{position:fixed;left:50%;transform:translateX(-50%);bottom:22px;z-index:99;display:flex;flex-direction:column;gap:8px;align-items:center;width:min(94vw,520px);pointer-events:none}
.toast{pointer-events:auto;background:#0f2a1f;border:1px solid #1f6b47;color:#d9ffe9;padding:12px 16px;border-radius:12px;box-shadow:0 10px 30px #000a;white-space:pre-line;width:100%;animation:up .25s;cursor:pointer;font-size:14px}
.toast.bad{background:#321416;border-color:#7a2a2f;color:#ffdede}.toast.out{opacity:0;transform:translateY(8px);transition:.3s}@keyframes up{from{opacity:0;transform:translateY(12px)}}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}.chip{padding:7px 13px;border-radius:99px;background:var(--card);border:1px solid var(--line);color:#b7bfd6;text-decoration:none;font-size:13px;white-space:nowrap}
.chip b{color:var(--mu);font-weight:600;margin-left:4px}.chip:hover{border-color:var(--ac);color:#fff}.chip.on{background:linear-gradient(135deg,var(--ac),var(--ac2));border-color:transparent;color:#fff}.chip.on b{color:#e5e7ff}
.bar{position:sticky;top:0;z-index:20;background:#101628ee;backdrop-filter:blur(8px);border:1px solid var(--line);border-radius:14px;padding:10px 12px;margin-bottom:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.bar select,.bar input[type=search]{width:auto;min-width:150px;flex:1}.bar button{margin:0;padding:9px 14px}.chk{display:flex;align-items:center;gap:8px;margin:0;color:var(--tx);font-size:14px;cursor:pointer;white-space:nowrap}
.pick{display:flex;align-items:center;gap:12px;padding:12px 14px;background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:8px;cursor:pointer;margin-top:0;color:var(--tx);font-size:15px}
.pick:hover{border-color:var(--ac)}.pick.sel{background:#1a2142;border-color:var(--ac)}.pick .mu{margin-left:auto;font-size:12px;white-space:nowrap}
.savebar{position:sticky;bottom:0;z-index:20;padding:12px 0 2px;background:linear-gradient(transparent,var(--bg) 40%)}.savebar button{margin:0;width:100%;padding:13px;font-size:15px}
.jump{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}.jump a{padding:6px 12px;border-radius:99px;background:var(--card);border:1px solid var(--line);color:#b7bfd6;text-decoration:none;font-size:12.5px}.jump a:hover{border-color:var(--ac);color:#fff}
.card[id]{scroll-margin-top:12px}details.card>summary{cursor:pointer;font-weight:600}
code{background:#0c101c;border:1px solid var(--line);padding:1px 6px;border-radius:6px;font-size:12.5px;word-break:break-all}
.qa{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.qa a{display:flex;align-items:center;gap:10px;padding:12px 14px;background:var(--card2);border:1px solid var(--line);border-radius:12px;text-decoration:none;color:var(--tx);font-weight:600}.qa a:hover{border-color:var(--ac)}
@media(max-width:900px){
.side{position:fixed;left:0;top:0;transform:translateX(-102%);transition:transform .22s;box-shadow:0 0 60px #000}
body.nav .side{transform:none}body.nav:after{content:"";position:fixed;inset:0;background:#000a;z-index:25}
.top{display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:20;background:#0e1220f2;backdrop-filter:blur(8px);border-bottom:1px solid var(--line);padding:10px 14px;font-weight:700}
.top button{margin:0;padding:7px 12px;font-size:18px;background:var(--card2);border:1px solid var(--line)}
main{padding:16px 14px 90px}h1{font-size:19px}.bar{top:54px}}
</style></head><body>
{% if session.get('ok') %}{% set nav = [('Overview',[('home','/','📊','Dashboard')]),('Store',[('products','/products','🛍️','Products'),('categories','/categories','🗂️','Categories'),('panel','/panel','🔌','Panel API'),('coupons','/coupons','🎟️','Coupons')]),('Sales',[('orders','/orders','🧾','Orders'),('payments','/payments','💳','QR Payments'),('deposits','/deposits','💰','Deposits'),('find','/find','🔎','Find Order')]),('Customers',[('users','/users','👥','Users'),('rgapi','/rgapi-admin','🔑','RGAPI'),('broadcast','/broadcast','📣','Broadcast')]),('System',[('settings','/settings','⚙️','Settings'),('botcfg','/botcfg','🤖','Bot Token'),('backup','/backup','💾','Backup')])] %}
<div class="app"><aside class="side"><div class="brand"><i>🎮</i><span>RG Admin</span></div>
{% for g, items in nav %}<div class="grp">{{ g }}</div>{% for k, u, ic, nm in items %}<a class="nl {{ 'on' if tab==k }}" href="{{ u }}"><span>{{ ic }}</span>{{ nm }}</a>{% endfor %}{% endfor %}
<div class="out"><a class="nl" href="/logout"><span>🚪</span>Logout</a></div></aside>
<div class="content"><header class="top"><button type="button" onclick="document.body.classList.toggle('nav')">☰</button><span>RG Admin</span></header>{% endif %}
<main>{% for m in get_flashed_messages() %}<div class="flash">{{ m }}</div>{% endfor %}{% block body %}{% endblock %}</main>
{% if session.get('ok') %}</div></div>{% endif %}
<div id="toasts"></div>
<script>
(function(){
var T=document.getElementById('toasts');
function toast(t){if(!t)return;var d=document.createElement('div');var bad=t.indexOf('❌')===0||t.indexOf('⚠')===0;d.className='toast'+(bad?' bad':'');d.textContent=t;T.appendChild(d);
 var k=function(){d.classList.add('out');setTimeout(function(){d.remove()},300)};setTimeout(k,bad?7000:4500);d.onclick=k}
function eat(root){var out=[];root.querySelectorAll('.flash').forEach(function(e){out.push(e.textContent.trim());e.remove()});return out}
function jump(){var h=document.querySelector('[data-jump]');if(!h)return;var cs=document.querySelectorAll('main form .card>h3, main form details.card>summary');if(cs.length<3)return;
 var box=document.createElement('div');box.className='jump';cs.forEach(function(x,i){var c=x.parentNode;if(!c.id)c.id='sec'+i;var a=document.createElement('a');a.href='#'+c.id;a.textContent=x.textContent.replace(/[(][0-9]+[)]/,'').trim();box.appendChild(a)});h.replaceWith(box)}
try{var s=sessionStorage.getItem('rg_toast');if(s){sessionStorage.removeItem('rg_toast');JSON.parse(s).forEach(toast)}}catch(e){}
eat(document).forEach(toast);jump();
function same(a,b){try{var x=new URL(a,location.href),y=new URL(b,location.href);return x.pathname===y.pathname&&x.search===y.search}catch(e){return false}}
function swap(doc){var nm=doc.querySelector('main'),cm=document.querySelector('main');if(!nm||!cm){location.reload();return}
 var y=window.scrollY;eat(nm);cm.innerHTML=nm.innerHTML;
 cm.querySelectorAll('script').forEach(function(o){var n=document.createElement('script');n.text=o.textContent;o.replaceWith(n)});jump();window.scrollTo(0,y)}
function busy(b,on){if(!b)return;if(on){b.dataset.t=b.textContent;b.disabled=true;if(b.textContent.length<40)b.textContent='⏳ '+b.textContent}else{b.disabled=false;if(b.dataset.t)b.textContent=b.dataset.t}}
document.addEventListener('submit',function(e){
 var f=e.target;if(!f||f.tagName!=='FORM'||e.defaultPrevented)return;
 if((f.method||'').toLowerCase()!=='post'||f.hasAttribute('data-full')||(f.enctype||'').indexOf('multipart')>=0)return;
 e.preventDefault();if(f.dataset.busy)return;
 var sb=e.submitter,fd;try{fd=new FormData(f,sb)}catch(x){fd=new FormData(f);if(sb&&sb.name)fd.append(sb.name,sb.value)}
 var url=(sb&&sb.getAttribute('formaction'))?sb.formAction:(f.getAttribute('action')?f.action:location.href);
 f.dataset.busy='1';busy(sb,true);
 fetch(url,{method:'POST',body:fd,credentials:'same-origin',headers:{'X-Requested-With':'fetch'}})
 .then(function(r){return r.text().then(function(h){return{u:r.url,h:h,ok:r.ok}})})
 .then(function(x){var doc=new DOMParser().parseFromString(x.h,'text/html');
  if(!x.ok&&!doc.querySelector('main')){toast('❌ Session expired or bad request - reload the page and try again.');return}
  if(same(x.u,location.href)){var m=eat(doc);swap(doc);m.forEach(toast)}
  else{try{sessionStorage.setItem('rg_toast',JSON.stringify(eat(doc)))}catch(_){}location.href=x.u}})
 .catch(function(){toast('❌ Network problem - nothing was lost, try again.')})
 .then(function(){delete f.dataset.busy;busy(sb,false)});
});
document.addEventListener('click',function(e){if(document.body.classList.contains('nav')&&!e.target.closest('.side,.top'))document.body.classList.remove('nav')});
})();
</script></body></html>"""


LOGIN = """{% extends 'base.html' %}{% block body %}<div class="card" style="max-width:360px;margin:60px auto">
<h1>Admin Login</h1><form method="post" data-full="1"><input type="hidden" name="csrf" value="{{ csrf() }}">
<label>Username</label><input name="u" autocomplete="username"><label>Password</label><input name="p" type="password" autocomplete="current-password">
<button style="width:100%">Login</button></form></div>{% endblock %}"""

HOME = """{% extends 'base.html' %}{% block body %}<div class="ph"><h1>Dashboard</h1></div><div class="grid">
<div class="card stat"><i>👥</i><b>{{ s.users }}</b><span>Total users</span></div><div class="card stat"><i>✅</i><b>{{ s.ver }}</b><span>Verified</span></div>
<div class="card stat"><i>🧾</i><b>{{ s.orders }}</b><span>Orders</span></div><div class="card stat"><i>👛</i><b>₹{{ '%.2f'|format(s.bal) }}</b><span>Total wallet balance</span></div>
<div class="card stat"><i>⏳</i><b><a class="lk" href="/payments">{{ s.pend }}</a></b><span>Deposits to review</span></div>
<div class="card stat"><i>🔑</i><b>{{ s.stock }}</b><span>Keys in stock</span></div>
<div class="card stat"><i>📈</i><b>{{ s.o_today }}</b><span>Orders today</span></div><div class="card stat"><i>🆕</i><b>{{ s.u_today }}</b><span>New users today</span></div></div>
<div class="card" style="margin-top:16px"><h3>Quick actions</h3><div class="qa">
<a href="/products/new">➕ Add product</a><a href="/products">🛍️ Products</a><a href="/categories">🗂️ Categories</a><a href="/panel/products">🔌 Panel products</a>
<a href="/orders">🧾 Orders</a><a href="/users">👥 Users</a><a href="/broadcast">📣 Broadcast</a><a href="/settings">⚙️ Settings</a></div></div>
<div class="card"><h3>Connections</h3><p style="margin:0">Panel API: <span class="bd {{ 'ok' if gs('panel_connected')=='1' else 'no' }}">{{ 'Connected' if gs('panel_connected')=='1' else 'Not connected' }}</span>
&nbsp; Payment gateway: <span class="bd {{ 'ok' if gs('gw_connected')=='1' else 'no' }}">{{ 'Connected' if gs('gw_connected')=='1' else 'Not connected' }}</span>
&nbsp; Maintenance: <span class="bd {{ 'wt' if gs('maint')=='1' else 'ok' }}">{{ 'ON' if gs('maint')=='1' else 'OFF' }}</span></p></div>{% endblock %}"""

EMOJIS = """{% extends 'base.html' %}{% block body %}<h1>Premium Emoji</h1>
<div class="card"><p class="mu"><b>How to get an emoji ID:</b> open the bot with your admin Telegram account (Premium) and send any premium emoji as a message.
The bot replies with the ID. Paste it in the slot you want. Leave blank to use the normal emoji. <b>Every button / line has its own slot</b> - changing one never changes another.
Emoji for products and plans are set in the <a class="lk" href="/products">Products</a> page.</p></div>
<div class="card"><h3>Premium emoji check</h3><p>Status: <b class="{{ 'no' if gs('emoji_mode')=='blocked' else 'ok' }}">{{ 'BLOCKED by Telegram (normal emoji shown)' if gs('emoji_mode')=='blocked' else 'enabled' }}</b></p>
<p class="mu">Sends one test message to your admin Telegram and tells you exactly why premium emoji do or do not show. You can also send /emojitest to the bot.</p>
<form method="post" action="/emojis/test" style="display:inline"><input type="hidden" name="csrf" value="{{ csrf() }}"><button>Test premium emoji now</button></form>
<form method="post" action="/emojis/preview" style="display:inline"><input type="hidden" name="csrf" value="{{ csrf() }}"><button>Send main menu / shop / referral / tutorial to my Telegram</button></form></div>
<form method="post" action="/emojis"><input type="hidden" name="csrf" value="{{ csrf() }}">
{% for title, rows in groups %}<details class="card" {{ 'open' if loop.index == 1 }}><summary style="cursor:pointer;font-weight:600">{{ title }} <span class="mu">({{ rows|length }})</span></summary><div class="tw" style="margin-top:10px"><table>
<tr><th>Used in</th><th>Normal emoji</th><th>Premium emoji ID</th><th></th></tr>
{% for e in rows %}<tr><td>{{ e.note }}</td>
<td><input name="fb_{{ e.k }}" value="{{ e.fallback }}" style="width:70px"></td>
<td><input name="id_{{ e.k }}" value="{{ e.eid }}" placeholder="e.g. 5368324170671202286" inputmode="numeric" autocomplete="off"></td>
<td><a class="mu" href="/emojis/clear/{{ e.k }}" onclick="return confirm('Remove premium ID?')">clear</a></td></tr>{% endfor %}
</table></div></details>{% endfor %}
<button>Save all</button></form>{% endblock %}"""

SETTINGS = """{% extends 'base.html' %}{% block body %}<div class="ph"><h1>Settings</h1></div><div data-jump></div><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">
<div class="card"><h3>Store</h3><label>Shop name (main menu title)</label><input name="shop_name" value="{{ gs('shop_name') }}">
<label>Minimum deposit</label><input name="min_dep" value="{{ gs('min_dep') }}"><label>Maximum deposit</label><input name="max_dep" value="{{ gs('max_dep') }}">
<label>Referral reward (when friend verifies phone)</label><input name="ref_reward" value="{{ gs('ref_reward') }}"></div>
<div class="card"><h3>Look &amp; feel (bot buttons and titles)</h3>
<label>Button colour - ONE colour for ALL buttons in the bot</label><select name="btn_color">
<option value="auto" {{ 'selected' if gs('btn_color') not in ('blue','green','red','plain') }}>Auto (each button as designed: blue / green / red)</option>
<option value="blue" {{ 'selected' if gs('btn_color')=='blue' }}>All BLUE</option><option value="green" {{ 'selected' if gs('btn_color')=='green' }}>All GREEN</option>
<option value="red" {{ 'selected' if gs('btn_color')=='red' }}>All RED</option><option value="plain" {{ 'selected' if gs('btn_color')=='plain' }}>All WHITE / normal (no colour)</option></select>
<label>Deep bold titles (shop name in the main menu, shop and category screens)</label><select name="deep_bold"><option value="1" {{ 'selected' if gs('deep_bold')!='0' }}>ON (extra thick letters)</option><option value="0" {{ 'selected' if gs('deep_bold')=='0' }}>OFF (normal bold)</option></select>
<p class="mu">Changes show in the bot within a few seconds. Use Categories &rarr; "Send to my Telegram" to preview.</p></div>
<div class="card"><h3>Payment (deposits)</h3><label>UPI ID (India users get a QR for this)</label><input name="upi_id" value="{{ gs('upi_id') }}" placeholder="name@bank">
<label>UPI payee name</label><input name="upi_name" value="{{ gs('upi_name') }}">
<label>Payment instructions for other countries (bKash / bank / crypto etc.)</label><textarea name="pay_other_text" rows="4">{{ gs('pay_other_text') }}</textarea></div>
<div class="card"><h3>Currency rates (1 INR = ?)</h3><p class="mu">Product prices are set in INR. Users in other countries see price × rate.</p>
<div class="grid">{% for c in rate_keys %}<div><label>{{ c }}</label><input name="rate_{{ c }}" value="{{ gs('rate_' ~ c) }}"></div>{% endfor %}</div></div>
<div class="card"><h3>Extras</h3><label>Referral commission % on friend's purchases (0 = off)</label><input name="ref_percent" value="{{ gs('ref_percent') }}">
<label>Low-stock alert at (keys left)</label><input name="low_stock" value="{{ gs('low_stock') }}">
<label>Maintenance mode (users cannot use the bot)</label><select name="maint"><option value="0" {{ 'selected' if gs('maint')!='1' }}>OFF</option><option value="1" {{ 'selected' if gs('maint')=='1' }}>ON</option></select>
<label>Maintenance message</label><input name="maint_text" value="{{ gs('maint_text') }}"></div>
<div class="card"><h3>Support</h3>
<label>Telegram support</label><select name="support_tg_on"><option value="1" {{ 'selected' if gs('support_tg_on')=='1' }}>ON</option><option value="0" {{ 'selected' if gs('support_tg_on')!='1' }}>OFF</option></select>
<label>Telegram username or link</label><input name="support_tg" value="{{ gs('support_tg') }}" placeholder="@username">
<label>WhatsApp support</label><select name="support_wa_on"><option value="1" {{ 'selected' if gs('support_wa_on')=='1' }}>ON</option><option value="0" {{ 'selected' if gs('support_wa_on')!='1' }}>OFF</option></select>
<label>WhatsApp number (with country code)</label><input name="support_wa" value="{{ gs('support_wa') }}" placeholder="919XXXXXXXXX"></div>
<div class="card"><h3>Payment Gateway (UPI QR, automatic)</h3>
<p class="mu">Choose the gateway, paste the <b>API token</b> and press <b>Save &amp; Connect</b>. QR is created, payment is detected automatically and the key is delivered / wallet is credited.</p>
<label>Gateway</label><select name="gw_gateway"><option value="paytm" {{ 'selected' if gs('gw_gateway')!='fampay' }}>Paytm</option><option value="fampay" {{ 'selected' if gs('gw_gateway')=='fampay' }}>FamPay</option></select>
<label>API token</label><input name="gw_token" value="{{ gs('gw_token') }}" autocomplete="off" placeholder="paste API key from your gateway">
<label>Gateway Base URL (change this when you move your gateway)</label><input name="gw_base" value="{{ gs('gw_base') or 'https://paymentgateway-0km8.onrender.com' }}">
<label>Webhook signing secret (optional - from gateway dashboard &rarr; Webhooks)</label><input name="gw_webhook_secret" value="{{ gs('gw_webhook_secret') }}" autocomplete="off">
<label>Payment page name (shown to customer)</label><input name="pay_name" value="{{ gs('pay_name') }}">
<label>Payment valid for (minutes)</label><input name="pay_expire" value="{{ gs('pay_expire') }}">
<button type="submit" formaction="/gateway/connect">Save &amp; Connect</button>
<p class="mu">Status: <b class="{{ 'ok' if gs('gw_connected')=='1' else 'no' }}">{{ 'Connected' if gs('gw_connected')=='1' else ('Token saved - press Save & Connect' if gw_on() else 'Not connected') }}</b><br>
Webhook URL to set in your gateway: <code>{{ webhook_url() }}</code></p></div>
<div class="card"><h3>Admin notifications</h3>
<p class="mu">You get a Telegram message for every new purchase, wallet top-up, failed key delivery and new verified user. Each message has a <b>Contact User</b> button.</p>
<label>Send notifications to (chat ID of a group / channel - empty = your admin Telegram)</label><input name="notify_chat" value="{{ gs('notify_chat') }}" placeholder="e.g. -1001234567890">
<label>New purchase (user or reseller)</label><select name="notify_purchase"><option value="1" {{ 'selected' if gs('notify_purchase')!='0' }}>ON</option><option value="0" {{ 'selected' if gs('notify_purchase')=='0' }}>OFF</option></select>
<label>Wallet balance added</label><select name="notify_topup"><option value="1" {{ 'selected' if gs('notify_topup')!='0' }}>ON</option><option value="0" {{ 'selected' if gs('notify_topup')=='0' }}>OFF</option></select>
<label>Key delivery failed</label><select name="notify_fail"><option value="1" {{ 'selected' if gs('notify_fail')!='0' }}>ON</option><option value="0" {{ 'selected' if gs('notify_fail')=='0' }}>OFF</option></select>
<label>New user verified</label><select name="notify_newuser"><option value="1" {{ 'selected' if gs('notify_newuser')!='0' }}>ON</option><option value="0" {{ 'selected' if gs('notify_newuser')=='0' }}>OFF</option></select>
<button type="submit" formaction="/notifications/test">Send sample messages to my Telegram</button></div>
<div class="card"><h3>Store screen &amp; sign-up</h3>
<label>Phone number verification at /start</label><select name="verify_on"><option value="1" {{ 'selected' if gs('verify_on')!='0' }}>ON (ask phone number)</option><option value="0" {{ 'selected' if gs('verify_on')=='0' }}>OFF (no phone needed)</option></select>
<label>Shop screen lines (one per line, shown under "Product Lineup")</label><textarea name="shop_bullets" rows="5">{{ gs('shop_bullets') }}</textarea>
<p class="mu"><b>Premium emoji:</b> type a normal emoji (🔑 🔥 🛡 🚫 💎 ...) - if that emoji has a premium ID in main.py it becomes premium automatically.
Or write <code>🔥{6141106778563158041}</code> (emoji + <b>{premium ID}</b>) to use any premium emoji you want.</p></div>
<div class="card"><h3>Manual payments (UPI / Binance)</h3>
<p class="mu">Customer pays, taps <b>I Have Paid</b>, sends the transaction ID, and YOU get a notification with Approve / Reject.</p>
<label>Pay UPI button (needs the UPI ID in "Payment (deposits)")</label><select name="pay_upi_on"><option value="1" {{ 'selected' if gs('pay_upi_on')=='1' }}>ON</option><option value="0" {{ 'selected' if gs('pay_upi_on')!='1' }}>OFF</option></select>
<label>Pay Binance button</label><select name="pay_binance_on"><option value="1" {{ 'selected' if gs('pay_binance_on')=='1' }}>ON</option><option value="0" {{ 'selected' if gs('pay_binance_on')!='1' }}>OFF</option></select>
<label>Binance payment details shown to customer (Binance Pay ID / UID / wallet address + network). Empty = button hidden.</label>
<textarea name="binance_text" rows="4">{{ gs('binance_text') }}</textarea></div>
<div class="card"><h3>Links</h3><label>Tutorial video link (Watch Guide Video)</label><input name="tutorial_url" value="{{ gs('tutorial_url') }}" placeholder="https://youtube.com/...">
<label>All Update File link</label><input name="update_url" value="{{ gs('update_url') }}" placeholder="https://t.me/... or drive link"></div>
<div class="savebar"><button>Save settings</button></div></form>{% endblock %}"""

USERS = """{% extends 'base.html' %}{% block body %}<div class="ph"><h1>Users</h1><span class="mu">{{ total }} found</span></div>
<form class="row" method="get"><input name="q" value="{{ q }}" placeholder="Search Telegram ID / chat ID / phone number / @username / name" autofocus>
<input type="hidden" name="f" value="{{ f }}"><select name="sort" style="width:auto;flex:none" onchange="this.form.submit()"><option value="new" {{ 'selected' if sort=='new' }}>Newest</option><option value="spent" {{ 'selected' if sort=='spent' }}>Top spenders</option><option value="orders" {{ 'selected' if sort=='orders' }}>Most hacks bought</option><option value="bal" {{ 'selected' if sort=='bal' }}>Highest balance</option></select>
<button style="margin:0">Search</button></form><br>
<div class="chips">{% for k,lab in [('all','All'),('usr','Users'),('res','Resellers'),('unv','Not verified'),('ban','Banned')] %}<a class="chip {{ 'on' if f==k }}" href="/users?f={{ k }}&sort={{ sort }}&q={{ q|urlencode }}">{{ lab }} <b>{{ cnt[k] }}</b></a>{% endfor %}</div>
<div class="card tw"><table><tr><th>Telegram ID</th><th>Name</th><th>Phone</th><th>Account</th><th>Hacks bought</th><th>Spent</th><th>Balance</th><th></th></tr>
{% for u in rows %}<tr><td><a class="lk" href="/users/{{ u.id }}"><code>{{ u.id }}</code></a></td><td><a class="lk" href="/users/{{ u.id }}"><b>{{ u.name }}</b></a>{% if u.username %}<br><span class="mu">@{{ u.username }}</span>{% endif %}</td><td>{{ u.phone or '-' }}</td>
<td><span class="bd {{ 'no' if u.banned else 'ok' }}">{{ 'banned' if u.banned else u.role }}</span>{% if not u.verified %}<br><span class="mu">not verified</span>{% endif %}</td><td>{{ u.hacks }}</td><td>{{ u.symbol }}{{ '%.2f'|format(u.spent) }}</td>
<td>{{ u.symbol }}{{ '%.2f'|format(u.balance) }}{% set h_ = [[u.refund_hold or 0, u.balance]|min, 0]|max %}{% if h_ > 0 %}<br><span class="wt">Refund hold: {{ '%.2f'|format(h_) }}</span>{% endif %}</td>
<td><a href="/users/{{ u.id }}"><button type="button" style="margin:0">Profile</button></a></td></tr>{% endfor %}
{% if not rows %}<tr><td colspan="8" class="mu">No users found.</td></tr>{% endif %}</table></div>
<div class="row" style="justify-content:center">{% if pg > 1 %}<a href="/users?f={{ f }}&sort={{ sort }}&q={{ q|urlencode }}&p={{ pg-1 }}"><button type="button" class="sec">← Prev</button></a>{% endif %}<span class="mu">Page {{ pg }} / {{ pages }}</span>{% if pg < pages %}<a href="/users?f={{ f }}&sort={{ sort }}&q={{ q|urlencode }}&p={{ pg+1 }}"><button type="button" class="sec">Next →</button></a>{% endif %}</div>{% endblock %}"""

PROFILE = """{% extends 'base.html' %}{% block body %}{% set u = d.u %}
<div class="ph"><h1>{{ u.name }} <span class="bd {{ 'no' if u.banned else 'ok' }}">{{ 'banned' if u.banned else u.role }}</span></h1><a href="/users"><button type="button" class="sec" style="margin:0">← All users</button></a></div>
<div class="grid">
<div class="card stat"><i>🛒</i><b>{{ d.hacks }}</b><span>Hacks bought</span></div><div class="card stat"><i>💸</i><b>{{ u.symbol }}{{ '%.2f'|format(d.spent) }}</b><span>Total spent</span></div>
<div class="card stat"><i>👛</i><b>{{ u.symbol }}{{ '%.2f'|format(u.balance) }}</b><span>Wallet balance</span></div><div class="card stat"><i>📥</i><b>{{ u.symbol }}{{ '%.2f'|format(d.deposited) }}</b><span>Total deposited</span></div>
<div class="card stat"><i>🎁</i><b>{{ u.symbol }}{{ '%.2f'|format(u.ref_balance or 0) }}</b><span>Referral balance</span></div><div class="card stat"><i>👥</i><b>{{ d.nrefs }}</b><span>People referred</span></div></div>
<div class="card"><h3>Profile</h3><div class="tw"><table>
<tr><td class="mu">Telegram ID / Chat ID</td><td><code>{{ u.id }}</code></td></tr>
<tr><td class="mu">Username</td><td>{% if u.username %}<a class="lk" href="https://t.me/{{ u.username }}" target="_blank" rel="noopener">@{{ u.username }}</a>{% else %}-{% endif %}</td></tr>
<tr><td class="mu">Phone</td><td>{{ u.phone or '-' }}</td></tr><tr><td class="mu">Country</td><td>{{ u.country }} · {{ u.currency }}</td></tr>
<tr><td class="mu">Account type</td><td>{{ u.role }}</td></tr><tr><td class="mu">Verified</td><td>{{ 'Yes' if u.verified else 'No' }}</td></tr><tr><td class="mu">Banned</td><td>{{ 'YES' if u.banned else 'No' }}</td></tr>
<tr><td class="mu">Joined</td><td>{{ u.joined|dts }}</td></tr>
<tr><td class="mu">First / last purchase</td><td>{{ d.first|dts if d.first else '-' }}{% if d.last %} &nbsp;→&nbsp; {{ d.last|dts }}{% endif %}</td></tr>
<tr><td class="mu">Referred by</td><td>{% if d.refby %}<a class="lk" href="/users/{{ d.refby.id }}">{{ d.refby.name }} ({{ d.refby.id }})</a>{% else %}-{% endif %}</td></tr>
{% set h_ = [[u.refund_hold or 0, u.balance]|min, 0]|max %}{% if h_ > 0 %}<tr><td class="mu">Refund hold</td><td class="wt">{{ '%.2f'|format(h_) }}</td></tr>{% endif %}</table></div></div>
<div class="card"><h3>Actions</h3><form method="post" action="/users/{{ u.id }}" class="row" style="flex-wrap:wrap"><input type="hidden" name="csrf" value="{{ csrf() }}">
<input name="amt" placeholder="+100 / -50" style="width:100px;flex:none"><label style="margin:0;display:flex;align-items:center;gap:4px;white-space:nowrap"><input type="checkbox" name="hold" value="1" style="width:auto"> refund hold</label><button name="a" value="bal" style="margin:0">Balance</button>
{% if (u.refund_hold or 0) > 0 and u.balance > 0 %}<button name="a" value="rok" style="margin:0" onclick="return confirm('Approve the refunded money?')">Approve refund</button><button name="a" value="rno" class="red" style="margin:0" onclick="return confirm('Take the refunded money back?')">Deduct refund</button>{% endif %}
<button name="a" value="role" style="margin:0">{{ 'Make user' if u.role=='reseller' else 'Make reseller' }}</button><button name="a" value="ban" class="red" style="margin:0">{{ 'Unban' if u.banned else 'Ban' }}</button></form>
<form method="post" action="/users/{{ u.id }}" class="row" style="margin-top:12px"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="msg"><input name="text" placeholder="Send a message to this user on Telegram..." required><button style="margin:0">Send</button></form></div>
<div class="card"><h3>Hacks bought - by product</h3><div class="tw"><table><tr><th>Product</th><th>Times</th><th>Spent</th></tr>{% for r in d.by_product %}<tr><td>{{ r.product }}</td><td>{{ r.n }}</td><td>{{ u.symbol }}{{ '%.2f'|format(r.s) }}</td></tr>{% endfor %}{% if not d.by_product %}<tr><td colspan="3" class="mu">No purchases yet.</td></tr>{% endif %}</table></div></div>
<div class="card"><h3>Order history ({{ d.hacks }})</h3><div class="tw"><table><tr><th>Date</th><th>Order</th><th>Product</th><th>Plan</th><th>Price</th><th>Key</th></tr>{% for o in d.orders %}<tr><td>{{ o.created|dts }}</td><td><code>{{ o.order_no }}</code></td><td>{{ o.product }}</td><td>{{ o.plan }}</td><td>{{ u.symbol }}{{ '%.2f'|format(o.price) }}</td><td><code>{{ o.key }}</code></td></tr>{% endfor %}{% if not d.orders %}<tr><td colspan="6" class="mu">No orders.</td></tr>{% endif %}</table></div></div>
<div class="card"><h3>Deposit history</h3><div class="tw"><table><tr><th>Date</th><th>Amount</th><th>Status</th><th>Transaction / UTR</th></tr>{% for x in d.deposits %}<tr><td>{{ x.created|dts }}</td><td>{{ u.symbol }}{{ '%.2f'|format(x.amount) }}</td><td><span class="bd {{ 'ok' if x.status=='paid' else 'no' if x.status in ('rejected','cancelled') else '' }}">{{ x.status }}</span></td><td><code>{{ x.utr or '-' }}</code></td></tr>{% endfor %}{% if not d.deposits %}<tr><td colspan="4" class="mu">No deposits.</td></tr>{% endif %}</table></div></div>
{% if d.refs %}<div class="card"><h3>People referred ({{ d.nrefs }})</h3><div class="tw"><table><tr><th>ID</th><th>Name</th><th>Joined</th></tr>{% for r in d.refs %}<tr><td><a class="lk" href="/users/{{ r.id }}"><code>{{ r.id }}</code></a></td><td>{{ r.name }}{% if r.username %} <span class="mu">@{{ r.username }}</span>{% endif %}</td><td>{{ r.joined|dts }}</td></tr>{% endfor %}</table></div></div>{% endif %}
<div class="card" id="rgapi"><h3>🔑 RGAPI System (reseller API)</h3>
<p class="mu">Status: <b class="{{ 'ok' if u.api_on else 'no' }}">{{ 'ON' if u.api_on else 'OFF' }}</b>{% if u.api_on %} &middot; API orders: <b>{{ u.api_cnt or 0 }}</b> &middot; last used: {{ u.api_last|dts if u.api_last else 'never' }}{% if u.api_ip %} ({{ u.api_ip }}){% endif %}{% endif %}</p>
{% if u.api_on %}<label>Server URL</label><input readonly value="{{ public_url() }}" onclick="this.select()"><label>API token</label><input readonly value="{{ u.api_token }}" onclick="this.select()">
<p class="mu">He sees a <b>RGAPI System</b> button in My Profile (above Back) with his token, product / plan IDs and the API docs.</p>{% endif %}
<form method="post" action="/users/{{ u.id }}" class="row"><input type="hidden" name="csrf" value="{{ csrf() }}">
{% if u.api_on %}<button name="a" value="rgapi_off" class="red">Turn OFF</button><button name="a" value="rgapi_regen" onclick="return confirm('New token? The old one stops working at once.')">New token</button>{% else %}<button name="a" value="rgapi_on">Turn ON RGAPI</button>{% endif %}</form></div>
<div class="card" id="custom"><h3>🎯 Product Customize</h3>
<p class="mu">Set a special price for THIS {{ u.role }} only. Leave a box empty = normal price. Prices are in ₹ (base currency); the bot converts to his currency automatically. {% if ncust %}<b>{{ ncust }} custom price(s) active.</b>{% endif %}</p>
<details {{ 'open' if ncust else '' }}><summary style="cursor:pointer;font-weight:700;margin-bottom:10px">Show all products &amp; plans ({{ prods|length }})</summary>
<form method="post" action="/users/{{ u.id }}"><input type="hidden" name="csrf" value="{{ csrf() }}">
{% for p in prods %}<div style="margin:12px 0 4px"><b>{{ p.name }}</b></div>
<div class="tw"><table><tr><th>Plan</th><th>Normal price</th><th>Custom price</th></tr>
{% for pl in p.plans %}<tr><td>{{ pl.name }}{% if not pl.active %} <span class="mu">(hidden)</span>{% endif %}</td><td>₹{{ '%g'|format(pl.dflt) }}</td>
<td><input name="cp_{{ pl.id }}" value="{{ '%g'|format(pl.cust) if pl.cust else '' }}" placeholder="normal" inputmode="decimal" style="width:110px;{{ 'border-color:#22c55e' if pl.cust else '' }}"></td></tr>{% endfor %}</table></div>{% endfor %}
{% if not prods %}<p class="mu">No products yet.</p>{% endif %}
<button name="a" value="prices" style="margin-top:14px">💾 Save all prices</button>
{% if ncust %}<button name="a" value="prices_reset" class="red" onclick="return confirm('Remove ALL custom prices of this user?')">Reset all to normal</button>{% endif %}
</form></details></div>
{% endblock %}"""

PRODUCTS = """{% extends 'base.html' %}{% block body %}<div class="ph"><h1>Products</h1><a href="/products/new"><button type="button" style="margin:0">+ Add product</button></a></div>
<div class="chips"><a class="chip {{ 'on' if cf=='all' }}" href="/products">All <b>{{ n_all }}</b></a>{% for c in cats() %}<a class="chip {{ 'on' if cf==c.id|string }}" href="/products?cat={{ c.id }}">{{ c.name }} <b>{{ c.nprod }}</b></a>{% endfor %}<a class="chip {{ 'on' if cf=='none' }}" href="/products?cat=none">No category <b>{{ n_none }}</b></a></div>
<form id="bulk" method="post" action="/products/bulk"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="confirm" id="dc" value=""></form>
<div class="bar"><label class="chk"><input type="checkbox" id="selall"> Select all</label><span class="mu" id="cnt">0 selected</span>
<input type="search" id="q" placeholder="Search product..." autocomplete="off">
<select name="cat_id" form="bulk"><option value="">Move selected to category...</option><option value="0">- no category -</option>{% for c in cats() %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select>
<button form="bulk" name="a" value="move">Move</button><button form="bulk" name="a" value="show" class="sec">Show</button><button form="bulk" name="a" value="hide" class="sec">Hide</button>
<button form="bulk" name="a" value="del" class="red" onclick="var n=document.querySelectorAll('.pc:checked').length;if(!n){alert('Tick at least one product first');return false}return confirm('Delete '+n+' selected product(s) with all their plans and unsold keys? This cannot be undone.')">🗑️ Delete selected</button>
<button type="button" class="grn" onclick="cpAll()">🔗 Copy ALL links</button>
<button form="bulk" name="a" value="delall" class="red" onclick="var t=prompt('This deletes ALL products (every category) with their plans and unsold keys.\\nType DELETE to confirm:');if(t!=='DELETE'){return false}document.getElementById('dc').value=t;return true">Delete ALL</button></div>
<div class="card tw"><table id="ptab"><tr><th></th><th>Name</th><th>Category</th><th>Plans</th><th>Stock</th><th>Status</th><th>Link</th><th></th></tr>
{% for p in rows %}<tr data-n="{{ p.name|lower }}" data-l="{{ plink(p.id) }}"><td><input class="pc" type="checkbox" name="pid" value="{{ p.id }}" form="bulk"></td><td><a class="lk" href="/products/{{ p.id }}"><b>{{ p.name }}</b></a></td>
<td><form method="post" action="/products/{{ p.id }}" class="row"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="setcat"><select name="cat_id" style="min-width:140px" onchange="this.form.requestSubmit()"><option value="0">- none -</option>{% for c in cats() %}<option value="{{ c.id }}" {{ 'selected' if p.cat_id==c.id }}>{{ c.name }}</option>{% endfor %}</select></form></td>
<td>{{ p.nplans }}</td><td>{{ 'API (auto)' if p.stock >= 999999 else p.stock }}</td><td><span class="bd {{ 'ok' if p.active else 'no' }}">{{ 'Visible' if p.active else 'Hidden' }}</span></td><td><button type="button" class="sec" style="margin:0" onclick="cp('{{ plink(p.id) }}',this)">📋 Copy link</button></td><td><a class="lk" href="/products/{{ p.id }}">Open</a></td></tr>{% endfor %}
{% if not rows %}<tr><td colspan="8" class="mu">No products here.</td></tr>{% endif %}</table></div>
<script>function cp(t,b){if(!t){alert('Bot username not loaded yet - start the bot / save the Bot Token first.');return}
function ok(){var o=b?b.textContent:'';if(b){b.textContent='✅ Copied';setTimeout(function(){b.textContent=o},1500)}else alert('Copied')}
if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(ok,function(){fb()})}else fb();
function fb(){var a=document.createElement('textarea');a.value=t;document.body.appendChild(a);a.select();try{document.execCommand('copy');ok()}catch(e){prompt('Copy this:',t)}a.remove()}}
function cpAll(){var L=[];document.querySelectorAll('#ptab tr[data-n]').forEach(function(r){if(r.style.display!=='none'&&r.getAttribute('data-l'))L.push(r.cells[1].innerText.trim()+' - '+r.getAttribute('data-l'))});
if(!L.length){alert('No links (is the bot running?)');return}cp(L.join('\\n'),null)}</script>
<script>(function(){var all=document.getElementById('selall'),cnt=document.getElementById('cnt'),q=document.getElementById('q');
function vis(){return [].filter.call(document.querySelectorAll('#ptab tr[data-n]'),function(r){return r.style.display!=='none'})}
function upd(){var n=document.querySelectorAll('.pc:checked').length;cnt.textContent=n+' selected'}
all.onchange=function(){vis().forEach(function(r){r.querySelector('.pc').checked=all.checked});upd()};
document.querySelectorAll('.pc').forEach(function(c){c.onchange=upd});
q.oninput=function(){var s=q.value.toLowerCase().trim();document.querySelectorAll('#ptab tr[data-n]').forEach(function(r){r.style.display=r.getAttribute('data-n').indexOf(s)>=0?'':'none'})};})();</script>
<div class="card"><h3>Premium emoji for products &amp; plans</h3>
<p class="mu">Paste a premium emoji ID (send the emoji to the bot to get it). <b>One emoji for all products</b> / <b>one emoji for all plans</b> is used everywhere automatically.
An emoji set on a single product (open the product) wins over the "all products" emoji.</p>
<form method="post" action="/products/emoji"><input type="hidden" name="csrf" value="{{ csrf() }}">
<label>One emoji for ALL products</label><input name="emoji_all_products" value="{{ gs('emoji_all_products') }}" inputmode="numeric" placeholder="premium emoji ID" autocomplete="off">
<label>One emoji for ALL plans (A to Z)</label><input name="emoji_all_plans" value="{{ gs('emoji_all_plans') }}" inputmode="numeric" placeholder="premium emoji ID" autocomplete="off">
<button name="a" value="save">Save</button>
<button name="a" value="apply" class="red" onclick="return confirm('Remove every single-product emoji so the ONE emoji is used for all products?')">Save &amp; use for ALL products</button></form></div>{% endblock %}"""

ASSIGN = """{% extends 'base.html' %}{% block body %}<div class="ph"><h1>{{ c.name }} &middot; choose products</h1><a class="lk" href="/categories">&larr; Categories</a></div>
<p class="mu" style="margin-top:-6px">Tick every product that should be inside <b>{{ c.name }}</b>, then press the Save button. Unticked products leave this category.</p>
<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">
<div class="bar"><label class="chk"><input type="checkbox" id="selall"> Select all</label><span class="mu" id="cnt"></span><input type="search" id="q" placeholder="Search product..." autocomplete="off"></div>
{% for p in rows %}<label class="pick {{ 'sel' if p.cat_id==c.id }}" data-n="{{ p.name|lower }}"><input class="pc" type="checkbox" name="pid" value="{{ p.id }}" {{ 'checked' if p.cat_id==c.id }}><span>{{ p.name }}</span>
<span class="mu">{% if p.cat_id and p.cat_id!=c.id and names.get(p.cat_id) %}now in: {{ names.get(p.cat_id) }}{% elif not p.active %}hidden{% endif %}</span></label>{% endfor %}
{% if not rows %}<div class="card mu">No products yet.</div>{% endif %}
<div class="savebar"><button id="sv">Save</button></div></form>
<script>(function(){var all=document.getElementById('selall'),cnt=document.getElementById('cnt'),q=document.getElementById('q'),sv=document.getElementById('sv');
function rows(){return [].filter.call(document.querySelectorAll('.pick'),function(r){return r.style.display!=='none'})}
function upd(){var n=document.querySelectorAll('.pc:checked').length;cnt.textContent=n+' selected';sv.textContent='Save ('+n+' selected)';
 document.querySelectorAll('.pick').forEach(function(r){r.classList.toggle('sel',r.querySelector('.pc').checked)})}
all.onchange=function(){rows().forEach(function(r){r.querySelector('.pc').checked=all.checked});upd()};
document.querySelectorAll('.pc').forEach(function(c){c.onchange=upd});
q.oninput=function(){var s=q.value.toLowerCase().trim();document.querySelectorAll('.pick').forEach(function(r){r.style.display=r.getAttribute('data-n').indexOf(s)>=0?'':'none'})};upd();})();</script>{% endblock %}"""

PRODUCT = """{% extends 'base.html' %}{% block body %}<h1>{{ p.name }}</h1>
<div class="card"><h3>🔗 Direct link of this product</h3><p class="mu">Share this link anywhere. When a customer taps it, the bot opens and shows THIS product directly (no searching).</p>
{% if plink(p.id) %}<input readonly value="{{ plink(p.id) }}" onclick="this.select()"><button type="button" onclick="var i=this.previousElementSibling;i.select();try{navigator.clipboard.writeText(i.value)}catch(e){document.execCommand('copy')}this.textContent='✅ Copied'">📋 Copy link</button>
{% else %}<p class="no">Bot username not loaded yet - save the Bot Token / start the bot, then refresh.</p>{% endif %}</div>
<div class="card"><h3>Product</h3>{% if p.api_pid %}<p class="mu">Connected to panel product <b>#{{ p.api_pid }}</b> - keys are bought from the panel automatically. Prices follow the Panel API percentages unless you edit a price by hand.</p>{% endif %}<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="edit">
<label>Name</label><input name="name" value="{{ p.name }}"><label>Description</label><input name="descr" value="{{ p.descr }}">
<label>Update group link (Join Telegram button after purchase)</label><input name="link" value="{{ p.link or '' }}" placeholder="https://t.me/yourgroup">
<label>Premium emoji ID for THIS product (empty = use the "all products" emoji)</label><input name="emoji_id" value="{{ p.emoji_id or '' }}" inputmode="numeric" placeholder="premium emoji ID" autocomplete="off">
<label>Category (shown after the customer picks a category in Shop Now)</label><select name="cat_id"><option value="0">- none -</option>{% for c in cats() %}<option value="{{ c.id }}" {{ 'selected' if p.cat_id==c.id }}>{{ c.name }}</option>{% endfor %}</select>
<label>Sort order (small = first)</label><input name="sort" value="{{ p.sort }}">
<label>Visibility</label><select name="active"><option value="1" {{ 'selected' if p.active }}>Visible</option><option value="0" {{ 'selected' if not p.active }}>Hidden</option></select>
<button>Save</button></form>
<form method="post" onsubmit="return confirm('Delete this product, its plans and unsold keys?')"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="del"><button class="red">Delete product</button></form></div>
<div class="card tw"><h3>Plans (prices in INR)</h3>
<p class="mu">Every plan has its own <b>Stock</b> switch. Choose <b>Out of Stock</b> + Save (or press the red/green button) and the bot shows <b>❌ Out of Stock</b> for that plan and nobody can buy it - also for products connected to the panel API. Choose <b>In stock</b> to sell it again.</p>
<form method="post" class="row" style="flex-wrap:wrap;gap:6px;margin:0 0 10px"><input type="hidden" name="csrf" value="{{ csrf() }}"><button name="a" value="alloos" class="red" style="margin:0" onclick="return confirm('Mark ALL plans of this product Out of Stock?')">❌ All plans Out of Stock</button><button name="a" value="allin" class="grn" style="margin:0">✅ All plans In stock</button></form>
<table><tr><th>Duration</th><th>Panel cost</th><th>User price</th><th>Reseller price</th><th>Show</th><th>Stock</th><th>Stock / Sold</th><th></th></tr>
{% for pl in plans %}{% set fid = 'plf' ~ pl.id %}<tr{% if pl.oos %} style="background:rgba(220,38,38,.08)"{% endif %}>
<td>{% set pp_ = pl.name|pp %}{% if pp_ %}<input form="{{ fid }}" name="dur" value="{{ pp_[0] }}" style="width:70px"> <select form="{{ fid }}" name="unit" style="width:90px"><option value="hours" {{ 'selected' if pp_[1]=='hours' }}>Hours</option><option value="days" {{ 'selected' if pp_[1]=='days' }}>Days</option></select>{% else %}<input form="{{ fid }}" name="name" value="{{ pl.name }}">{% endif %}</td><td class="mu">{% if pl.api_plan_id %}₹{{ '%.2f'|format(pl.base_price) }}<br>API #{{ pl.api_plan_id }}{% else %}-{% endif %}</td><td><input form="{{ fid }}" name="price" value="{{ pl.price }}" style="width:80px"></td><td><input form="{{ fid }}" name="rprice" value="{{ pl.rprice }}" style="width:80px"></td>
<td><select form="{{ fid }}" name="active"><option value="1" {{ 'selected' if pl.active }}>Yes</option><option value="0" {{ 'selected' if not pl.active }}>No</option></select></td>
<td><select form="{{ fid }}" name="oos" style="min-width:120px"><option value="0" {{ 'selected' if not pl.oos }}>✅ In stock</option><option value="1" {{ 'selected' if pl.oos }}>❌ Out of Stock</option></select></td>
<td>{% if pl.oos %}<span class="bd no">OUT OF STOCK</span><br>{% endif %}{% if pl.api_plan_id %}auto / {{ pl.sold }}<br><span class="mu">{{ 'price: manual' if pl.manual else 'price: auto' }}</span>{% else %}{{ pl.stock if not pl.oos else 0 }} / {{ pl.sold }}<br><a class="lk" href="/plans/{{ pl.id }}">Manage keys</a>{% endif %}</td>
<td style="white-space:nowrap"><form id="{{ fid }}" method="post" style="display:inline;margin:0"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="plan_id" value="{{ pl.id }}">
<button name="a" value="saveplan" style="margin:0">Save</button> {% if pl.oos %}<button name="a" value="instock" class="grn" style="margin:0" title="sell this plan again">In stock</button>{% else %}<button name="a" value="outstock" class="red" style="margin:0" title="show Out of Stock in the bot">Out of Stock</button>{% endif %} {% if pl.api_plan_id and pl.manual %}<button name="a" value="autoprice" style="margin:0" title="go back to the automatic % price">Auto</button> {% endif %}<button name="a" value="delplan" class="red" style="margin:0" onclick="return confirm('Delete plan and unsold keys?')">X</button></form></td></tr>{% endfor %}</table></div>
<div class="card"><h3>Add plans</h3><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="addplans">
<div id="rows"></div><button type="button" onclick="addRow()" style="margin:6px 0">+ Add another plan</button>
<script>function addRow(){var d=document.createElement('div');d.className='row';d.style.cssText='flex-wrap:wrap;gap:6px;margin:8px 0';
d.innerHTML='<input name="dur" type="number" min="1" step="1" placeholder="Duration" style="width:95px;flex:none" required><select name="unit" style="width:95px;flex:none"><option value="hours">Hours</option><option value="days" selected>Days</option></select><input name="uprice" placeholder="User price" style="width:110px;flex:none" required><input name="rprice" placeholder="Reseller price" style="width:125px;flex:none"><button type="button" class="red" style="margin:0" onclick="this.parentNode.remove()">X</button>';
document.getElementById('rows').appendChild(d)}addRow();</script>
<button>Save plans</button></form></div>{% endblock %}"""

PLAN = """{% extends 'base.html' %}{% block body %}<h1>{{ pl.pname }} · {{ pl.name }}</h1>
<p class="mu"><a class="lk" href="/products/{{ pl.product_id }}">← back to product</a> · In stock: <b>{{ pl.stock }}</b></p>
<div class="card"><h3>Add keys</h3><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="add">
<label>One key per line (duplicates are skipped)</label><textarea name="keys" rows="8" required></textarea><button>Add keys</button></form></div>
<div class="card tw"><h3>Unsold keys (first 200)</h3><table>{% for k in keys %}<tr><td><code>{{ k.code }}</code></td><td>
<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="delkey"><input type="hidden" name="kid" value="{{ k.id }}"><button class="red" style="margin:0">Delete</button></form></td></tr>{% endfor %}</table>
{% if keys %}<form method="post" onsubmit="return confirm('Delete ALL unsold keys of this plan?')"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="clear"><button class="red">Delete all unsold keys</button></form>{% endif %}</div>{% endblock %}"""

DEPOSITS = """{% extends 'base.html' %}{% block body %}<h1>Deposits</h1>
<p>{% for k,l in tabs %}<a class="lk" href="/deposits?s={{ k }}" style="margin-right:12px;{{ 'font-weight:bold' if k==s }}">{{ l }}</a>{% endfor %}</p>
<div class="card tw"><table><tr><th>#</th><th>User</th><th>Amount</th><th>UTR</th><th>Proof</th><th>Status</th><th>Time</th><th></th></tr>
{% for d in rows %}<tr><td>{{ d.id }}</td><td>{{ d.user_id }}<br><span class="mu">{{ d.name }}</span></td><td>{{ d.symbol }}{{ '%.2f'|format(d.amount) }}</td><td>{{ d.utr or '-' }}</td>
<td>{% if d.proof %}<a class="lk" target="_blank" href="/proof/{{ d.id }}">view</a>{% else %}-{% endif %}</td><td><span class="bd {{ 'ok' if d.status=='paid' else 'no' if d.status in ('rejected','cancelled') else 'wt' }}">{{ d.status }}</span></td><td>{{ d.created|ts }}</td>
<td>{% if d.status in ('pending','review') %}<form method="post" action="/deposits/{{ d.id }}" class="row"><input type="hidden" name="csrf" value="{{ csrf() }}">
<button name="a" value="ok" style="margin:0" onclick="return confirm('Credit {{ d.symbol }}{{ d.amount }} to user?')">Approve</button><button name="a" value="no" class="red" style="margin:0">Reject</button></form>{% endif %}</td></tr>{% endfor %}</table></div>{% endblock %}"""

ORDERS = """{% extends 'base.html' %}{% block body %}<h1>Orders</h1><p><a class="lk" href="/orders.csv">Export all as CSV</a></p><form class="row" method="get"><input name="q" value="{{ q }}" placeholder="User ID or order number"><button style="margin:0">Search</button></form><br>
<div class="card tw"><table><tr><th>Order</th><th>User</th><th>Product</th><th>Price</th><th>Key</th><th>Time</th></tr>
{% for o in rows %}<tr><td>{{ o.order_no }}</td><td>{{ o.user_id }}</td><td>{{ o.product }} · {{ o.plan }}</td><td>{{ o.price }}</td><td><code>{{ o.key }}</code></td><td>{{ o.created|ts }}</td></tr>{% endfor %}</table></div>{% endblock %}"""

BACKUP = """{% extends 'base.html' %}{% block body %}<h1>Backup &amp; Restore</h1>
<div class="card"><h3>Status</h3><p>GitHub backup: <b class="{{ 'ok' if gh else 'no' }}">{{ 'configured' if gh else 'NOT configured' }}</b><br>
Last successful backup: <b>{{ st.last_ok|ts if st.last_ok else 'never' }}</b> {% if st.size %}({{ (st.size/1024)|round(1) }} KB){% endif %}<br>
{% if st.last_err %}<span class="no">Last error: {{ st.last_err }}</span>{% endif %}</p>
{% if not gh %}<p class="mu">Add env vars on Render: <b>GH_TOKEN</b> (fine-grained token, Contents: read &amp; write), <b>GH_REPO</b> (e.g. yourname/rg-backup — keep it PRIVATE). Without it, data is lost when Render restarts.</p>{% endif %}
<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><button name="a" value="now">Backup now</button>
<button name="a" value="send">📤 Send Backup</button></form>
<p class="mu">"Send Backup" makes a backup and sends the file to the Chat ID saved below.</p></div>
<div class="card"><h3>⏱ Auto Backup Timer</h3>
<p>Status: <b class="{{ 'ok' if ac.on else 'no' }}">{{ 'ON' if ac.on else 'OFF' }}</b>
{% if ac.on and ac.chat %} &middot; every <b>{{ ac.hours }}</b> hour(s) &rarr; <code>{{ ac.chat }}</code>{% endif %}<br>
{% if ac.on and ac.next %}Next auto backup: <b>{{ ac.next|ts }}</b><br>{% endif %}
{% if ac.last %}Last auto backup: <b>{{ ac.last|ts }}</b><br>{% endif %}
{% if st.auto_err %}<span class="no">Auto backup error: {{ st.auto_err }} (retrying every 5 min)</span>{% endif %}</p>
<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="auto">
<label>Chat ID (user, group or channel)</label><input name="chat" value="{{ ac.chat }}" placeholder="e.g. 123456789 or -1001234567890" required>
<label>Send a backup every (hours)</label><input name="hours" value="{{ ac.hours }}" placeholder="e.g. 1, 6, 12, 24, 0.5" required>
<label><input type="checkbox" name="on" value="1" {{ 'checked' if ac.on else '' }}> Turn automatic backup ON</label>
<button>Save</button></form>
<p class="mu">A personal Chat ID needs you to press /start on the bot first. For a group or channel, add the bot there (channel: as admin). Minimum 0.25 hour (15 min). First backup is sent within a minute after you turn it ON.</p></div>
<div class="card"><h3>Download</h3><a class="lk" href="/backup/download">Download database file (.db.gz)</a></div>
<div class="card"><h3>Restore</h3><p class="mu">Upload a .db or .db.gz backup. This REPLACES all current data.</p>
<form method="post" enctype="multipart/form-data" onsubmit="return confirm('Replace ALL current data with this backup?')"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="restore">
<input type="file" name="f" required><button class="red">Restore</button></form></div>{% endblock %}"""

BROADCAST = """{% extends 'base.html' %}{% block body %}<h1>Broadcast</h1>
<div class="card"><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">
<label>Message (Telegram HTML allowed: &lt;b&gt;bold&lt;/b&gt;, &lt;i&gt;italic&lt;/i&gt;, &lt;code&gt;code&lt;/code&gt;)</label><textarea name="text" rows="7" required></textarea>
<label>Send to</label><select name="to"><option value="me">Only me (test)</option><option value="all">All verified users</option></select>
<button>Send</button></form>{% if last %}<p class="mu">Last broadcast: {{ last }}</p>{% endif %}</div>{% endblock %}"""

PAYMENTS = '{% extends \'base.html\' %}{% block body %}<h1>QR / Manual Payments</h1><form class="row" method="get" action="/payments"><input name="q" value="{{ qs }}" placeholder="Search order ID / txn ID / user ID / name"><button style="margin:0">Search</button></form><br>\n<p>{% for k,l in tabs %}<a class="lk" href="/payments?s={{ k }}" style="margin-right:12px;{{ \'font-weight:bold\' if k==s }}">{{ l }}</a>{% endfor %}</p>\n<div class="card tw"><table><tr><th>Order ID</th><th>User</th><th>Method</th><th>For</th><th>Amount</th><th>Txn ID</th><th>Proof</th><th>Status</th><th>Time</th><th></th></tr>\n{% for p in rows %}<tr><td>{{ p.pay_no }}</td><td>{{ p.user_id }}<br><span class="mu">{{ p.name }}</span></td><td>{{ p.method }}</td><td>{{ p.title }}</td><td>{{ p.symbol }}{{ \'%.2f\'|format(p.amount) }}</td><td>{{ p.txn or \'-\' }}</td>\n<td>{% if p.proof %}<a class="lk" target="_blank" href="/payproof/{{ p.pay_no }}">view</a>{% else %}-{% endif %}</td>\n<td><span class="bd {{ \'ok\' if p.status==\'paid\' else \'no\' if p.status in (\'cancelled\',\'rejected\') else \'wt\' }}">{{ p.status }}</span></td><td>{{ p.created|ts }}</td>\n<td>{% if p.status in (\'pending\',\'expired\',\'review\') %}<form method="post" action="/payments/{{ p.pay_no }}" class="row"><input type="hidden" name="csrf" value="{{ csrf() }}">\n<button name="a" value="ok" style="margin:0" onclick="return confirm(\'Mark as PAID and deliver to the user?\')">Approve</button><button name="a" value="no" class="red" style="margin:0">Reject</button></form>{% endif %}</td></tr>{% endfor %}</table></div>{% endblock %}'
COUPONS = '{% extends \'base.html\' %}{% block body %}<h1>Coupons</h1>\n<div class="card"><h3>Create coupon</h3><p class="mu">A coupon gives a discount on one purchase. Each user can use a coupon once.</p>\n<form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="add">\n<label>Code (letters/numbers)</label><input name="code" required placeholder="RG50">\n<label>Type</label><select name="kind"><option value="percent">Percent off (%)</option><option value="flat">Flat off (INR)</option></select>\n<label>Value</label><input name="value" required placeholder="10">\n<label>Max total uses (0 = unlimited)</label><input name="max_uses" value="0">\n<label>Valid for days (0 = no expiry)</label><input name="days" value="0"><button>Create coupon</button></form></div>\n<div class="card tw"><table><tr><th>Code</th><th>Discount</th><th>Used</th><th>Expires</th><th>Status</th><th></th></tr>\n{% for c in rows %}<tr><td><b>{{ c.code }}</b></td><td>{{ (c.value|string + \'%\') if c.kind==\'percent\' else (\'₹\' + c.value|string) }}</td><td>{{ c.used }} / {{ c.max_uses or \'∞\' }}</td>\n<td>{{ c.expires|ts if c.expires else \'never\' }}</td><td>{{ \'Active\' if c.active else \'Off\' }}</td>\n<td><form method="post" class="row"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="code" value="{{ c.code }}">\n<button name="a" value="toggle" style="margin:0">{{ \'Turn off\' if c.active else \'Turn on\' }}</button><button name="a" value="del" class="red" style="margin:0" onclick="return confirm(\'Delete coupon?\')">Delete</button></form></td></tr>{% endfor %}</table></div>{% endblock %}'
PAYPAGE = '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>{{ shop }} · Payment</title><style>\n*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 50% -10%,#1b2a4a 0,#0a0e17 55%);color:#eaf0ff;font-family:system-ui,Segoe UI,Roboto,sans-serif;display:flex;justify-content:center;padding:18px}\n.card{width:100%;max-width:410px;background:#111827;border:1px solid #223049;border-radius:20px;padding:22px;box-shadow:0 20px 60px #0008;align-self:flex-start;margin-top:10px}\n.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.shop{font-weight:700;font-size:16px}.sec{font-size:12px;color:#7ee0a0;background:#12301f;padding:4px 10px;border-radius:99px}\n.amt{text-align:center;margin:10px 0 4px;font-size:38px;font-weight:800}.sub{text-align:center;color:#8b96b3;font-size:13px;margin-bottom:14px}\n.qr{background:#fff;border-radius:16px;padding:14px;width:240px;height:240px;margin:0 auto;display:flex;align-items:center;justify-content:center}.qr svg{width:100%;height:100%}\n.row{display:flex;justify-content:space-between;gap:10px;padding:10px 0;border-bottom:1px solid #1d2940;font-size:14px}.row span:first-child{color:#8b96b3}.row b{text-align:right;word-break:break-all}\n.btn{display:block;text-align:center;text-decoration:none;background:#3b82f6;color:#fff;padding:13px;border-radius:12px;font-weight:600;margin-top:16px}.btn.g{background:#16a34a}\n.wait{display:flex;align-items:center;justify-content:center;gap:10px;margin-top:16px;color:#ffd166;font-size:14px}.dot{width:10px;height:10px;border-radius:50%;background:#ffd166;animation:p 1s infinite}@keyframes p{50%{opacity:.25}}\n.tm{text-align:center;color:#8b96b3;font-size:13px;margin-top:8px}.ok{width:84px;height:84px;border-radius:50%;background:#16a34a;margin:6px auto 14px;display:flex;align-items:center;justify-content:center;animation:pop .5s}\n@keyframes pop{0%{transform:scale(.3);opacity:0}100%{transform:scale(1);opacity:1}}.ok svg{width:46px;height:46px}.big{text-align:center;font-size:22px;font-weight:800}.bad{background:#dc2626}\n.mu{color:#8b96b3;font-size:12px;text-align:center;margin-top:14px}\n</style></head><body><div class="card">\n<div class="top"><div class="shop">{{ shop }}</div><div class="sec">🔒 Secure UPI</div></div>\n{% if p.status == \'paid\' %}\n<div class="ok"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7"/></svg></div>\n<div class="big">Payment Successful</div><div class="sub">{{ sym }}{{ \'%.2f\'|format(p.pay_amount or p.amount) }} received</div>\n<div class="row"><span>Order ID</span><b>{{ p.pay_no }}</b></div>\n<div class="row"><span>Transaction ID</span><b>{{ p.txn or \'-\' }}</b></div>\n<div class="row"><span>{{ \'Wallet\' if p.kind==\'topup\' else \'Item\' }}</span><b>{{ \'Recharge added to wallet\' if p.kind==\'topup\' else p.title }}</b></div>\n<div class="row"><span>Paid on</span><b>{{ p.paid_at|ts }} IST</b></div>\n<div class="row"><span>Status</span><b style="color:#4ade80">SUCCESS</b></div>\n<p class="sub" style="margin-top:14px">{{ \'Your wallet balance is updated.\' if p.kind==\'topup\' else \'Your key has been sent in Telegram.\' }}</p>\n{% if bot_user %}<a class="btn g" href="https://t.me/{{ bot_user }}">Back to Telegram</a>{% endif %}\n{% elif p.status in (\'expired\',\'cancelled\') %}\n<div class="ok bad"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></div>\n<div class="big">Payment {{ \'Expired\' if p.status==\'expired\' else \'Cancelled\' }}</div><div class="sub">Order {{ p.pay_no }}<br>If you already paid, it will be added automatically.</div>\n{% if bot_user %}<a class="btn" href="https://t.me/{{ bot_user }}">Back to Telegram</a>{% endif %}\n{% else %}\n<div class="amt">{{ sym }}{{ \'%.2f\'|format(p.pay_amount or p.amount) }}</div><div class="sub">{{ p.title }}</div>\n<div class="qr">{{ qr|safe if qr else \'QR not available\' }}</div>\n<div class="tm">Expires in <b id="t">--:--</b></div>\n<div class="wait"><span class="dot"></span> Waiting for payment…</div>\n{% if p.upi_uri %}<a class="btn" href="{{ p.upi_uri }}">Pay with UPI App</a>{% elif p.pay_url %}<a class="btn" href="{{ p.pay_url }}">Open payment link</a>{% endif %}\n<div class="row" style="margin-top:14px"><span>Order ID</span><b>{{ p.pay_no }}</b></div>\n<p class="mu">Scan with PhonePe, Google Pay, Paytm or any UPI app.<br>Do not close this page — it updates automatically.</p>\n<script>var left={{ left }};function f(){var m=Math.floor(left/60),s=left%60;document.getElementById(\'t\').textContent=(m<10?\'0\':\'\')+m+\':\'+(s<10?\'0\':\'\')+s;if(left<=0){location.reload();return}left--}f();setInterval(f,1000);\nsetInterval(function(){fetch(\'status\').then(function(r){return r.json()}).then(function(j){if(j.status!==\'pending\')location.reload()}).catch(function(){})},3000);</script>\n{% endif %}\n</div></body></html>'

CATS = """{% extends 'base.html' %}{% block body %}<h1>Categories</h1>
<div class="card"><p class="mu">When you add categories, <b>Shop Now</b> first shows the category buttons (e.g. NON ROOT PANEL, ROOT PANEL, iPHONE PANEL, PC PANEL, FF GUILD GLORY ...).
The customer taps a category and sees only the products of that category. Make as many categories as you want. Assign a product to a category in
<a class="lk" href="/products">Products</a> (drop-down in the list). Products with no category appear under the "other" button. No categories = Shop Now shows all products like before.</p>
<form method="post" action="/categories/preview" style="display:inline"><input type="hidden" name="csrf" value="{{ csrf() }}"><button>Send category screen + shop to my Telegram</button></form></div>
<div class="card"><h3>Add category</h3><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="add">
<label>Name (button text)</label><input name="name" required placeholder="e.g. NON ROOT PANEL">
<label>Normal emoji (optional - turns premium automatically if it has a premium ID)</label><input name="emoji" placeholder="e.g. 📱">
<label>Premium emoji ID for the button (optional - wins over the normal emoji)</label><input name="eid" inputmode="numeric" placeholder="premium emoji ID" autocomplete="off">
<label>Sort order (small = first)</label><input name="sort" value="0"><button>Add category</button></form></div>
<div class="card tw"><h3>Your categories</h3><table><tr><th>Name</th><th>Emoji</th><th>Premium ID</th><th>Sort</th><th>Show</th><th>Products</th><th></th></tr>
{% for c in rows %}{% set fid = 'catf' ~ c.id %}<tr>
<td><input form="{{ fid }}" name="name" value="{{ c.name }}" style="min-width:150px"></td><td><input form="{{ fid }}" name="emoji" value="{{ c.emoji }}" style="width:60px"></td>
<td><input form="{{ fid }}" name="eid" value="{{ c.eid }}" inputmode="numeric" style="min-width:150px" autocomplete="off"></td><td><input form="{{ fid }}" name="sort" value="{{ c.sort }}" style="width:60px"></td>
<td><select form="{{ fid }}" name="active"><option value="1" {{ 'selected' if c.active }}>Yes</option><option value="0" {{ 'selected' if not c.active }}>No</option></select></td><td>{{ c.nprod }}</td>
<td style="white-space:nowrap"><form id="{{ fid }}" method="post" style="display:inline;margin:0"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="cid" value="{{ c.id }}"><button name="a" value="save" style="margin:0">Save</button> <a href="/categories/{{ c.id }}/assign"><button type="button" class="grn" style="margin:0">Products</button></a> <button name="a" value="del" class="red" style="margin:0" onclick="return confirm('Delete this category? Its products are kept (they move to the other button).')">X</button></form></td></tr>{% endfor %}
{% if not rows %}<tr><td colspan="7" class="mu">No category yet.</td></tr>{% endif %}</table></div>
<div class="card"><h3>Category screen text</h3><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}"><input type="hidden" name="a" value="text">
<label>Title (empty = shop name)</label><input name="cat_title" value="{{ gs('cat_title') }}" placeholder="{{ gs('shop_name') }}">
<label>Lines under the title (one per line)</label><textarea name="cat_text" rows="4">{{ gs('cat_text') }}</textarea>
<p class="mu"><b>Premium emoji in the lines:</b> type a normal emoji - if it has a premium ID in main.py it becomes premium automatically. Or write <code>🔥{6141106778563158041}</code> (emoji + <b>{premium ID}</b>) for any premium emoji you want.</p>
<label>Button name for products without a category</label><input name="cat_other_name" value="{{ gs('cat_other_name') }}">
<button>Save text</button></form></div>{% endblock %}"""
NEWPRODUCT = '{% extends \'base.html\' %}{% block body %}<h1>Add product</h1>\n<div class="card"><form method="post"><input type="hidden" name="csrf" value="{{ csrf() }}">\n<label>Product name</label><input name="name" required placeholder="e.g. Br Mods Pc Emulator">\n<label>Update group link (Join Telegram button after purchase) - optional</label><input name="link" placeholder="https://t.me/yourgroup">\n<label>Premium emoji ID for this product - optional</label><input name="emoji_id" inputmode="numeric" placeholder="premium emoji ID">\n<label>Category - optional</label><select name="cat_id"><option value="0">- none -</option>{% for c in cats() %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select>\n<h3>Plans</h3><p class="mu">Duration + Hours/Days, then User price and Reseller price (INR). Press <b>+ Add another plan</b> for more. Reseller price empty = same as user price.</p>\n<div id="rows"></div><button type="button" onclick="addRow()" style="margin:6px 0">+ Add another plan</button>\n<script>function addRow(){var d=document.createElement(\'div\');d.className=\'row\';d.style.cssText=\'flex-wrap:wrap;gap:6px;margin:8px 0\';\nd.innerHTML=\'<input name="dur" type="number" min="1" step="1" placeholder="Duration" style="width:95px;flex:none" required><select name="unit" style="width:95px;flex:none"><option value="hours">Hours</option><option value="days" selected>Days</option></select><input name="uprice" placeholder="User price" style="width:110px;flex:none" required><input name="rprice" placeholder="Reseller price" style="width:125px;flex:none"><button type="button" class="red" style="margin:0" onclick="this.parentNode.remove()">X</button>\';\ndocument.getElementById(\'rows\').appendChild(d)}addRow();</script>\n<button>Save product</button></form></div>{% endblock %}'
FIND = '{% extends \'base.html\' %}{% block body %}<h1>Find order</h1>\n<form class="row" method="get"><input name="q" value="{{ q }}" placeholder="Order ID (ORD… / WAL…), transaction ID or user ID" autofocus><button style="margin:0">Find user</button></form><br>\n{% if q and not hits %}<div class="card">Nothing found for <b>{{ q }}</b>.</div>{% endif %}\n{% for h in hits %}<div class="card"><h3>{{ h.kind }}</h3>\n<p><b>Order ID:</b> {{ h.ref }}</p>\n{% for k, v in h.info %}<p class="mu">{{ k }}: <b>{{ v }}</b></p>{% endfor %}\n<p><b>User:</b> {{ h.uname or \'-\' }} · <b>ID:</b> {{ h.uid }} · <b>Username:</b> {{ (\'@\' + h.username) if h.username else \'-\' }}<br><b>Phone:</b> {{ h.phone or \'-\' }} · <b>Wallet:</b> ₹{{ \'%.2f\'|format(h.balance) }}</p>\n<a class="lk" href="/users?q={{ h.uid }}">Open user</a></div>{% endfor %}{% endblock %}'
PANEL = '{% extends \'base.html\' %}{% block body %}<h1>Panel API</h1>\n<div class="card"><h3>1. Connect to your panel</h3>\n<p class="mu">Paste the API token of your main website and press <b>Save &amp; Connect</b>. You can change the token or the server URL any time.</p>\n<form method="post" action="/panel/connect"><input type="hidden" name="csrf" value="{{ csrf() }}">\n<label>Server URL</label><input name="panel_url" value="{{ gs(\'panel_url\') or default_url }}">\n<label>API token</label><input name="panel_token" value="{{ gs(\'panel_token\') }}" autocomplete="off" placeholder="paste API token">\n<button>Save &amp; Connect</button> <button type="submit" formaction="/panel/balance">Check Balance</button>\n<a class="lk" href="/panel/products"><button type="button">Show Products</button></a></form>\n<p class="mu">Status: <b class="{{ \'ok\' if gs(\'panel_connected\')==\'1\' else \'no\' }}">{{ \'Connected\' if gs(\'panel_connected\')==\'1\' else (\'Token saved - press Save & Connect\' if gs(\'panel_token\') else \'Not connected\') }}</b></p></div>\n<div class="card"><h3>2. Your prices (percentage on the panel price)</h3>\n<p class="mu">Every product you add gets its prices automatically: <b>panel price + your %</b>. Change the % and press <b>Save &amp; apply</b> - all products are updated at once, no need to edit each price.</p>\n<form method="post" action="/panel/markup"><input type="hidden" name="csrf" value="{{ csrf() }}">\n<label>Reseller % (reseller price = panel price + this %)</label><input name="mk_reseller" value="{{ rp }}">\n<label>User % (user price = panel price + this %)</label><input name="mk_user" value="{{ up }}">\n<p class="mu">Example: panel price ₹100 &rarr; reseller <b>₹{{ \'%.2f\'|format(ex_r) }}</b> &middot; user <b>₹{{ \'%.2f\'|format(ex_u) }}</b></p>\n<button name="a" value="save">Save %</button>\n<button name="a" value="apply" class="red" onclick="return confirm(\'Recalculate the price of ALL panel products with these percentages? Prices you edited by hand are overwritten too.\')">Save &amp; apply to ALL products</button></form></div>\n<div class="card"><h3>3. Your panel products</h3>\n<p class="mu">In the shop: <b>{{ np }}</b> panel product(s), <b>{{ nl }}</b> plan(s). Press <b>Show Products</b> above to see everything on your panel and add the ones you want (or all).</p>\n<form method="post" action="/panel/auto"><input type="hidden" name="csrf" value="{{ csrf() }}">\n<label>Auto price sync (keeps panel prices up to date, then applies your %)</label>\n<select name="panel_autosync"><option value="1" {{ \'selected\' if gs(\'panel_autosync\')!=\'0\' }}>ON</option><option value="0" {{ \'selected\' if gs(\'panel_autosync\')==\'0\' }}>OFF</option></select>\n<label>Sync every (minutes, 5 - 1440)</label><input name="panel_sync_min" value="{{ gs(\'panel_sync_min\') }}">\n<button>Save</button> <button type="submit" formaction="/panel/sync">Sync prices now</button></form>\n<p class="mu">Last sync: {{ (gs(\'panel_last_sync\')|int)|ts if gs(\'panel_last_sync\')|int else \'never\' }}</p></div>{% endblock %}'
PANELPROD = """{% extends 'base.html' %}{% block body %}<div class="ph"><h1>Panel products</h1><a href="/panel/products"><button type="button" style="margin:0">🔄 Refresh</button></a></div>
<p class="mu"><a class="lk" href="/panel">&larr; back to Panel API</a> &middot; Percentages now: reseller <b>+{{ rp }}%</b>, user <b>+{{ up }}%</b> &middot; Every time you open or refresh this page the list is read fresh from your panel.</p>
<form method="post" action="/panel/add" id="pf"><input type="hidden" name="csrf" value="{{ csrf() }}">
<div class="chips"><button type="button" class="chip on" data-m="all">All <b>{{ rows|length }}</b></button><button type="button" class="chip" data-m="new">🆕 New <b>{{ n_new }}</b></button><button type="button" class="chip" data-m="added">✅ Added <b>{{ rows|length - n_new }}</b></button></div>
<div class="bar"><label class="chk"><input type="checkbox" id="selall"> Select all</label><span class="mu" id="cnt">0 selected</span>
<input type="search" id="q" placeholder="Search product..." autocomplete="off">
<select name="cat_id"><option value="0">Category for new products...</option>{% for c in cats() %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select>
<button name="a" value="selected">➕ Add selected</button><button name="a" value="allnew" class="grn" onclick="return confirm('Add all {{ n_new }} NEW product(s) to your shop?')">Add all NEW</button></div>
{% for r in rows %}<div class="card pcard" data-n="{{ r.name|lower }}" data-new="{{ 0 if r.added else 1 }}"><label style="margin:0;color:var(--tx);font-size:15px"><input class="pc" type="checkbox" name="pid" value="{{ r.id }}" style="width:auto"> <b>{{ r.name }}</b> <span class="mu">(panel #{{ r.id }})</span> {% if r.added %}<span class="bd ok">Added</span>{% else %}<span class="bd" style="background:#f59e0b;color:#111">🆕 NEW</span>{% endif %}</label>
<div class="tw"><table><tr><th>Plan</th><th>Panel price</th><th>Reseller price</th><th>User price</th></tr>
{% for pl in r.plans %}<tr><td>{{ pl.name }}</td><td>₹{{ '%.2f'|format(pl.base) }}</td><td>₹{{ '%.2f'|format(pl.res) }}</td><td>₹{{ '%.2f'|format(pl.usr) }}</td></tr>{% endfor %}</table></div></div>{% endfor %}
{% if not rows %}<div class="card">No products found on the panel.</div>{% endif %}</form>
<script>(function(){var q=document.getElementById('q'),all=document.getElementById('selall'),cnt=document.getElementById('cnt'),mode='all';
function cards(){return [].slice.call(document.querySelectorAll('.pcard'))}
function vis(){return cards().filter(function(c){return c.style.display!=='none'})}
function upd(){cnt.textContent=document.querySelectorAll('.pc:checked').length+' selected'}
function apply(){var s=q.value.toLowerCase().trim();cards().forEach(function(c){var n=c.getAttribute('data-new')==='1';var ok=c.getAttribute('data-n').indexOf(s)>=0&&(mode==='all'||(mode==='new'&&n)||(mode==='added'&&!n));c.style.display=ok?'':'none'})}
q.oninput=apply;q.onkeydown=function(e){if(e.key==='Enter')e.preventDefault()};
all.onchange=function(){vis().forEach(function(c){c.querySelector('.pc').checked=all.checked});upd()};
document.querySelectorAll('.pc').forEach(function(c){c.onchange=upd});
document.querySelectorAll('.chip[data-m]').forEach(function(b){b.onclick=function(){mode=b.getAttribute('data-m');document.querySelectorAll('.chip[data-m]').forEach(function(x){x.classList.toggle('on',x===b)});apply()}});
})();</script>{% endblock %}"""
BOTCFG = """{% extends 'base.html' %}{% block body %}<h1>Bot Token &amp; Admin</h1>
<div class="card"><h3>Status</h3><p>Bot: <b class="{{ 'ok' if running else 'no' }}">{{ status }}</b></p>
<p class="mu">Telegram bot token: <b>{{ tok }}</b> &nbsp;·&nbsp; Admin ID: <b>{{ admin }}</b></p></div>
<div class="card"><h3>1) Bot token</h3><p class="mu">Token leaked or regenerated in @BotFather? Paste the NEW token here and press the button - the bot restarts on the new token at once, no redeploy and no code change. The old token stops working.</p>
<form method="post" action="/botcfg/token"><input type="hidden" name="csrf" value="{{ csrf() }}"><label>New bot token</label><input name="token" placeholder="123456789:AAxxxxxxxx" autocomplete="off" required>
<button>Save &amp; run bot with this token</button></form></div>
<div class="card"><h3>2) Admin ID</h3><p class="mu">The Telegram user ID of the admin (gets all alerts, can use /find etc). Send /start to @userinfobot to see an ID.</p>
<form method="post" action="/botcfg/admin"><input type="hidden" name="csrf" value="{{ csrf() }}"><label>Admin Telegram ID</label><input name="admin_id" value="{{ admin }}" inputmode="numeric" required>
<button>Save admin ID</button></form></div>
<div class="card"><h3>3) Bot name</h3><p class="mu">Shop name = the title in the main menu. Tick the box to also change the name shown on the bot's Telegram profile.</p>
<form method="post" action="/botcfg/name"><input type="hidden" name="csrf" value="{{ csrf() }}"><label>Bot / shop name</label><input name="shop_name" value="{{ gs('shop_name') }}" required>
<label style="display:block;margin:8px 0"><input type="checkbox" name="tg" value="1" style="width:auto"> Also change the Telegram profile name of the bot</label>
<button>Save name</button></form></div>{% endblock %}"""

TG_LOGIN = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RG Admin</title><script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>body{margin:0;background:#090b11;color:#e9edf8;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center}
.c{padding:24px}.s{width:38px;height:38px;border:4px solid #222b41;border-top-color:#6366f1;border-radius:50%;margin:0 auto 14px;animation:r 1s linear infinite}@keyframes r{to{transform:rotate(360deg)}}
a{color:#8b9cff}</style></head><body><div class="c"><div class="s" id="sp"></div><div id="m">Signing in…</div></div>
<script>
(function(){var m=document.getElementById('m'),sp=document.getElementById('sp');
function fail(t){sp.style.display='none';m.innerHTML='🚫 '+t+'<br><br><a href="/login">Login with username &amp; password</a>'}
try{var w=window.Telegram&&Telegram.WebApp;if(!w||!w.initData){fail('Open this page from the bot (/website).');return}
w.ready();w.expand&&w.expand();
fetch('/tg-auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({d:w.initData})})
.then(function(r){return r.json()}).then(function(j){if(j.ok){var nx=new URLSearchParams(location.search).get('next')||'/';if(nx.charAt(0)!=='/'||nx.charAt(1)==='/')nx='/';location.replace(nx)}else{fail(j.err||'Not allowed.')}})
.catch(function(){fail('Network error. Try again.')})}catch(e){fail('Error. Try again.')}})();
</script></body></html>"""

LOGIN_WAIT = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Waiting for approval</title><style>body{margin:0;background:#090b11;color:#e9edf8;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center}
.c{max-width:340px;padding:28px;background:#131826;border:1px solid #222b41;border-radius:16px}.s{width:42px;height:42px;border:4px solid #222b41;border-top-color:#fbbf24;border-radius:50%;margin:0 auto 16px;animation:r 1s linear infinite}
@keyframes r{to{transform:rotate(360deg)}}a{color:#8b9cff}small{color:#8a94ae}</style></head><body><div class="c"><div class="s" id="sp"></div>
<h3 id="t" style="margin:0 0 8px">Waiting for owner approval</h3><div id="m"><small>A device alert was sent to the owner on Telegram. Please wait…</small></div></div>
<script>
var r={{ rid|tojson }};
function tick(){fetch('/login/status?r='+encodeURIComponent(r),{cache:'no-store'}).then(function(x){return x.json()}).then(function(j){
if(j.st==='ok'){location.replace('/')}
else if(j.st==='no'){location.replace('/login')}
else if(j.st==='wait'){setTimeout(tick,2000)}
else{document.getElementById('sp').style.display='none';document.getElementById('t').textContent='Request expired';
document.getElementById('m').innerHTML='<a href="/login">Back to login</a>'}}).catch(function(){setTimeout(tick,3000)})}
tick();
</script></body></html>"""

BANNED_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ACCESS BLOCKED</title><style>body{margin:0;background:#7f0d0d;color:#fff;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;animation:p 1.2s ease-in-out infinite}
@keyframes p{0%,100%{background:#7f0d0d}50%{background:#c81e1e}}.c{padding:28px;max-width:380px}h1{font-size:30px;margin:10px 0}.i{font-size:64px}</style></head>
<body><div class="c"><div class="i">🚨</div><h1>ACCESS BLOCKED</h1><p>This device has been <b>banned</b>.<br>The owner denied this login attempt.</p></div></body></html>"""

RGAPIADM = """{% extends 'base.html' %}{% block body %}<div class="ph"><h1>🔑 RGAPI</h1><span class="mu">{{ on|length }} active</span></div>
<div class="card"><h3>Give a user / reseller API access</h3>
<p class="mu">Search by Telegram (chat) ID, name, @username or phone number, then press <b>Turn ON</b>. He gets an <b>RGAPI System</b> button in My Profile (above Back). His bot connects with: <b>Server URL</b> <code>{{ public_url() }}</code> + his <b>API token</b>.</p>
<form class="row" method="get"><input name="q" value="{{ q }}" placeholder="Chat ID / name / phone / @username" autofocus><button style="margin:0">Search</button></form>
{% if q %}<div class="tw"><table><tr><th>ID</th><th>Name</th><th>Phone</th><th>Account</th><th>RGAPI</th><th></th></tr>
{% for u in found %}<tr><td><a class="lk" href="/users/{{ u.id }}"><code>{{ u.id }}</code></a></td><td><b>{{ u.name }}</b>{% if u.username %}<br><span class="mu">@{{ u.username }}</span>{% endif %}</td><td>{{ u.phone or '-' }}</td><td>{{ u.role }}</td>
<td><span class="bd {{ 'ok' if u.api_on else 'no' }}">{{ 'ON' if u.api_on else 'OFF' }}</span></td>
<td><form method="post" action="/users/{{ u.id }}" style="margin:0"><input type="hidden" name="csrf" value="{{ csrf() }}">{% if u.api_on %}<button name="a" value="rgapi_off" class="red" style="margin:0">Turn OFF</button>{% else %}<button name="a" value="rgapi_on" style="margin:0">Turn ON</button>{% endif %}</form></td></tr>{% endfor %}
{% if not found %}<tr><td colspan="6" class="mu">Nobody found.</td></tr>{% endif %}</table></div>{% endif %}</div>
<div class="card"><h3>Users with RGAPI ON</h3><div class="tw"><table><tr><th>ID</th><th>Name</th><th>Account</th><th>Balance</th><th>API orders</th><th>API spent</th><th>Last used</th><th></th></tr>
{% for u in on %}<tr><td><a class="lk" href="/users/{{ u.id }}#rgapi"><code>{{ u.id }}</code></a></td><td><b>{{ u.name }}</b>{% if u.username %}<br><span class="mu">@{{ u.username }}</span>{% endif %}</td><td>{{ u.role }}</td><td>{{ u.symbol }}{{ '%.2f'|format(u.balance) }}</td><td>{{ u.api_orders }}</td><td>{{ u.symbol }}{{ '%.2f'|format(u.api_spent) }}</td>
<td>{{ u.api_last|dts if u.api_last else 'never' }}{% if u.api_ip %}<br><span class="mu">{{ u.api_ip }}</span>{% endif %}</td>
<td><form method="post" action="/users/{{ u.id }}" style="margin:0"><input type="hidden" name="csrf" value="{{ csrf() }}"><button name="a" value="rgapi_off" class="red" style="margin:0">Turn OFF</button></form></td></tr>{% endfor %}
{% if not on %}<tr><td colspan="8" class="mu">Nobody yet. Search a user above and turn RGAPI ON.</td></tr>{% endif %}</table></div></div>{% endblock %}"""

app.jinja_loader = DictLoader({"rgapiadm.html": RGAPIADM, "categories.html": CATS, "botcfg.html": BOTCFG, "panel.html": PANEL, "panelprod.html": PANELPROD, "find.html": FIND, "newproduct.html": NEWPRODUCT, "payments.html": PAYMENTS, "coupons.html": COUPONS, "backup.html": BACKUP, "broadcast.html": BROADCAST,"products.html": PRODUCTS, "assign.html": ASSIGN, "product.html": PRODUCT, "plan.html": PLAN, "deposits.html": DEPOSITS, "orders.html": ORDERS,"base.html": BASE, "login.html": LOGIN, "home.html": HOME, "emojis.html": EMOJIS, "settings.html": SETTINGS, "users.html": USERS, "profile.html": PROFILE})


def csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


IST = timezone(timedelta(hours=5, minutes=30))
def public_url():
    return (bot.PUBLIC_URL or request.host_url.rstrip("/"))


app.jinja_env.globals.update(public_url=public_url, csrf=csrf, gs=lambda k: db.get(k), plink=bot.product_link, cats=lambda: db.cats(False), gw_on=gateway.configured,
                             webhook_url=lambda: public_url() + "/webhook/gateway")
app.jinja_env.filters["dts"] = lambda t: datetime.fromtimestamp(t or 0, IST).strftime("%d %b %Y %H:%M") if t else "-"
app.jinja_env.filters["ts"] = lambda t: datetime.fromtimestamp(t or 0, IST).strftime("%d %b %H:%M")


def dev_id():
    d = request.cookies.get("rg_dev", "")
    if len(d) != 32 or not d.isalnum():
        d = secrets.token_hex(16)
        g.newdev = d
    return d


@app.before_request
def guard():
    if request.endpoint in ("health", "static", "pay_page", "pay_status", "gw_webhook") or request.blueprint == "rgapi":
        return
    dev = dev_id()
    # Telegram-verified admins (tg_login / tg_auth) are never blocked by a ban made against somebody else
    if request.endpoint in ("tg_login", "tg_auth"):
        return
    if not session.get("ok") and secure.is_blocked(dev, client_ip()):      # signed-in admins are never locked out by a shared-IP ban
        return Response(BANNED_PAGE, 403, mimetype="text/html")
    if request.endpoint == "login_status":
        return
    if request.method == "POST" and not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x")):
        return "Bad request", 400
    if request.endpoint in ("login", "login_wait"):
        return
    if not session.get("ok"):
        return redirect(url_for("login"))
    uid = session.get("uid")          # logged in through Telegram: the access ends the moment he is removed as admin
    if uid and not secure.is_admin(uid):
        session.clear()
        return redirect(url_for("login"))


def page(name, **kw):
    return render_template_string("{% extends '" + name + ".html' %}", **kw)


@app.route("/health")
def health():
    return "ok"


@app.route("/login", methods=["GET", "POST"])
def login():
    ip = client_ip()
    f = FAILS.get(ip, [0, 0])
    if request.method == "POST":
        if f[1] > time.time():
            flash(f"Too many attempts. Try again in {int((f[1] - time.time()) // 60) + 1} min.")
            return page("login", title="Login")
        ok = hmac.compare_digest(request.form.get("u", ""), ADMIN_USER) & hmac.compare_digest(request.form.get("p", ""), ADMIN_PASS)
        if ok:
            FAILS.pop(ip, None)
            dev = dev_id()
            ua = request.headers.get("User-Agent", "")
            if secure.device_trusted(dev) or not secure.trusted():
                first = not secure.trusted()          # very first login ever = trusted at once
                secure.trust(dev, ip, ua)
                session.clear()
                session["ok"] = True
                session.permanent = True
                if first:
                    bot.safe(bot.send, bot.ADMIN_ID, "🔓 <b>First admin login</b> on the website — this device is now trusted.\n"
                             f"📱 {bot.esc(secure.short_ua(ua))} · 🌐 <code>{bot.esc(ip)}</code>")
                return redirect("/")
            rid = secure.new_request(dev, ip, ua)      # new device -> the owner must approve in Telegram
            session.clear()
            session["pend"] = rid
            return redirect("/login/wait")
        f[0] += 1
        if f[0] >= 5:
            f = [0, time.time() + 900]
        FAILS[ip] = f
        time.sleep(1.5)
        flash("Wrong username or password")
    return page("login", title="Login")


@app.route("/login/wait")
def login_wait():
    rid = session.get("pend")
    if not rid or not secure.get_request(rid):
        return redirect("/login")
    return render_template_string(LOGIN_WAIT, rid=rid)


@app.route("/login/status")
def login_status():
    rid = request.args.get("r", "")
    if not rid or session.get("pend") != rid:
        return jsonify(st="none")
    p = secure.get_request(rid)
    if not p:
        return jsonify(st="none")
    if p["st"] == "ok" and p["dev"] == dev_id():
        session.pop("pend", None)
        session["ok"] = True
        session.permanent = True
        return jsonify(st="ok")
    if p["st"] == "no":
        session.clear()
        return jsonify(st="no")
    return jsonify(st=p["st"])


@app.route("/tg-login")
def tg_login():
    return Response(TG_LOGIN, mimetype="text/html")


@app.route("/tg-auth", methods=["POST"])
def tg_auth():
    d = (request.get_json(silent=True) or {}).get("d", "")
    uid = secure.verify_init_data(d)
    if not uid or not secure.is_admin(uid):
        return jsonify(ok=False, err="This Telegram account is not an admin.")
    session.clear()
    session["ok"] = True
    session["uid"] = uid
    session.permanent = True
    return jsonify(ok=True)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/")
def home():
    day0 = int(datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    with db.conn() as c:
        s = {"users": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
             "ver": c.execute("SELECT COUNT(*) FROM users WHERE verified=1").fetchone()[0],
             "orders": c.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
             "bal": c.execute("SELECT COALESCE(SUM(balance),0) FROM users").fetchone()[0],
             "pend": c.execute("SELECT COUNT(*) FROM deposits WHERE status='review'").fetchone()[0] + c.execute("SELECT COUNT(*) FROM pay_orders WHERE status='review'").fetchone()[0],
             "stock": c.execute("SELECT COUNT(*) FROM keys WHERE used=0").fetchone()[0],
             "o_today": c.execute("SELECT COUNT(*) FROM orders WHERE created>=?", (day0,)).fetchone()[0],
             "u_today": c.execute("SELECT COUNT(*) FROM users WHERE joined>=?", (day0,)).fetchone()[0]}
    return page("home", s=s, tab="home")


@app.route("/emojis", methods=["GET", "POST"])
def emojis():
    if request.method == "POST":
        used, dups = {}, []
        with db.conn() as c:
            for r in c.execute("SELECT k, note FROM emojis").fetchall():
                k = r["k"]
                eid = request.form.get("id_" + k, "").strip()
                if eid and not eid.isdigit():
                    continue
                c.execute("UPDATE emojis SET eid=?, fallback=? WHERE k=?", (eid, request.form.get("fb_" + k, "").strip() or "▫️", k))
                if eid:
                    if eid in used:
                        dups.append(f"{used[eid]}  =  {r['note']}")
                    else:
                        used[eid] = r["note"]
        db.put("emoji_mode", "ok")
        db.emoji_clear()
        with db.conn() as c:
            ids = [r["eid"] for r in c.execute("SELECT eid FROM emojis WHERE eid<>''")]
        bad = bot.emoji_invalid(ids)
        msg = "Saved" + (f" - but {len(bad)} ID(s) are not valid in Telegram: " + ", ".join(bad[:5]) if bad else ". Now press 'Test premium emoji now'.")
        if dups:
            msg += "\nNote - the SAME emoji ID is used in more than one place:\n" + "\n".join(dups[:8])
        flash(msg)
        return redirect("/emojis")
    with db.conn() as c:
        rows = c.execute("SELECT * FROM emojis ORDER BY rowid").fetchall()
    byk = {r["k"]: r for r in rows}
    groups, seen = [], set()
    for title, keys in db.EMOJI_GROUPS:
        seen.update(keys)
        part = [byk[k] for k in keys if k in byk]
        if part:
            groups.append((title, part))
    rest = [r for r in rows if r["k"] not in seen]
    if rest:
        groups.append(("Other", rest))
    return page("emojis", groups=groups, tab="emojis")


@app.route("/emojis/preview", methods=["POST"])
def emoji_preview_route():
    flash("Sent to your Telegram - check the bot chat." if bot.send_menu_preview() else "ADMIN_ID is not set.")
    return redirect("/emojis")


@app.route("/notifications/test", methods=["POST"])
def notifications_test():
    flash("Sample messages sent to your Telegram." if bot.send_samples() else "ADMIN_ID is not set.")
    return redirect("/settings")


@app.route("/products/emoji", methods=["POST"])
def products_emoji():
    f = request.form
    for k in ("emoji_all_products", "emoji_all_plans"):
        v = f.get(k, "").strip()
        if v and not v.isdigit():
            flash("Emoji ID must be digits only.")
            return redirect("/products")
        db.put(k, v)
    if f.get("a") == "apply":
        with db.conn() as c:
            c.execute("UPDATE products SET emoji_id=''")
        flash("Saved. All products now use the ONE emoji.")
    else:
        flash("Saved.")
    db.emoji_clear()
    return redirect("/products")


@app.route("/emojis/test", methods=["POST"])
def emoji_test_route():
    ok, rep = bot.emoji_test()
    flash(("OK: " if ok else "PROBLEM: ") + rep)
    return redirect("/emojis")


@app.route("/emojis/clear/<k>")
def emoji_clear(k):
    with db.conn() as c:
        c.execute("UPDATE emojis SET eid='' WHERE k=?", (k,))
    db.emoji_clear()
    return redirect("/emojis")


@app.route("/botcfg")
def botcfg():
    t = bot.TOKEN or ""
    tok = (t.split(":")[0] + ":" + "•" * 6 + t[-4:]) if ":" in t else "(not set)"
    st = bot.STATUS["v"]
    return page("botcfg", tab="botcfg", tok=tok, admin=bot.ADMIN_ID or "", status=st, running=st.startswith("running"))


@app.route("/botcfg/token", methods=["POST"])
def botcfg_token():
    ok, msg = bot.set_token(request.form.get("token", ""))
    flash(msg)
    return redirect("/botcfg")


@app.route("/botcfg/admin", methods=["POST"])
def botcfg_admin():
    ok, msg = bot.set_admin(request.form.get("admin_id", ""))
    flash(msg)
    return redirect("/botcfg")


@app.route("/botcfg/name", methods=["POST"])
def botcfg_name():
    n = request.form.get("shop_name", "").strip()
    if not n:
        flash("Name cannot be empty.")
        return redirect("/botcfg")
    db.put("shop_name", n)
    msg = "Name saved."
    if request.form.get("tg"):
        ok, d = bot.set_bot_display_name(n)
        msg += " Telegram profile name changed." if ok else " Telegram profile name NOT changed: " + d
    flash(msg)
    return redirect("/botcfg")


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        for k in db.SETTINGS_DEFAULTS:
            if k in request.form:
                v = request.form[k].strip()
                if k in ("min_dep", "max_dep") and not v.isdigit():
                    continue
                if k == "low_stock" and not v.isdigit():
                    continue
                if k == "notify_chat" and v and not v.lstrip("-").isdigit():
                    continue
                if k == "pay_expire" and not (v.isdigit() and 1 <= int(v) <= 60):
                    continue
                if k == "gw_token" and v != db.get("gw_token"):
                    db.put("gw_connected", "0")
                if k == "gw_gateway" and v not in ("paytm", "fampay"):
                    continue
                if k == "btn_color" and v not in ("auto", "blue", "green", "red", "plain"):
                    continue
                if k == "deep_bold" and v not in ("0", "1"):
                    continue
                if k == "gw_base":
                    v = v.rstrip("/")
                    if v and not v.startswith("http"):
                        v = "https://" + v
                if k == "ref_percent":
                    try:
                        if not 0 <= float(v) <= 100:
                            continue
                    except ValueError:
                        continue
                if k.startswith("rate_"):
                    try:
                        if float(v) <= 0:
                            continue
                    except ValueError:
                        continue
                db.put(k, v)
        flash("Saved")
        return redirect("/settings")
    return page("settings", tab="settings", rate_keys=list(db.RATES))


@app.route("/users")
def users():
    q = request.args.get("q", "").strip()
    f = request.args.get("f", "all")
    sort = request.args.get("sort", "new")
    try:
        pg = max(int(request.args.get("p", "1")), 1)
    except ValueError:
        pg = 1
    per = 30
    rows, total = db.search_users(q, f, sort, per, (pg - 1) * per)
    if q and total == 1 and pg == 1:              # one match -> open the profile directly
        return redirect(f"/users/{rows[0]['id']}")
    pages = max((total + per - 1) // per, 1)
    return page("users", rows=rows, q=q, f=f, sort=sort, pg=pg, pages=pages, total=total, cnt=db.user_counts(), tab="users")


@app.route("/users/<int:uid>", methods=["GET"])
def user_profile(uid):
    d = db.user_profile(uid)
    if not d:
        flash("User not found")
        return redirect("/users")
    cust = db.user_prices(uid)
    prods = []
    for p in db.products(False):
        pls = []
        for pl in db.plans_of(p["id"], False):
            dflt = pl["rprice"] if (d["u"]["role"] == "reseller" and pl["rprice"] and pl["rprice"] > 0) else pl["price"]
            pls.append({"id": pl["id"], "name": pl["name"], "dflt": dflt, "cust": cust.get(pl["id"]), "active": pl["active"]})
        if pls:
            prods.append({"name": p["name"], "plans": pls})
    return page("profile", d=d, tab="users", title=d["u"]["name"], prods=prods, ncust=len(cust))


@app.route("/users/<int:uid>", methods=["POST"])
def user_action(uid):
    a = request.form.get("a")
    with db.conn() as c:
        if a == "bal":
            try:
                amt = float(request.form.get("amt", "0"))
                c.execute("UPDATE users SET balance=balance+? WHERE id=?", (amt, uid))
                if amt > 0 and request.form.get("hold") == "1":
                    c.execute("UPDATE users SET refund_hold=ROUND(COALESCE(refund_hold,0)+?,2) WHERE id=?", (amt, uid))
            except ValueError:
                flash("Invalid amount")
        elif a in ("rok", "rno"):
            pass                        # handled below (needs its own connection)
        elif a == "role":
            c.execute("UPDATE users SET role=CASE role WHEN 'reseller' THEN 'user' ELSE 'reseller' END WHERE id=?", (uid,))
        elif a == "ban":
            c.execute("UPDATE users SET banned=1-banned WHERE id=?", (uid,))
    if a in ("prices", "prices_reset"):                    # V18: Product Customize -> one Save for all prices
        if a == "prices_reset":
            with db.conn() as c:
                c.execute("DELETE FROM user_prices WHERE user_id=?", (uid,))
            flash("All custom prices removed - this user pays the normal prices again")
        else:
            vals = {int(k[3:]): v for k, v in request.form.items() if k.startswith("cp_") and k[3:].isdigit()}
            s, cl, bad = db.save_user_prices(uid, vals)
            flash(f"✅ Saved {s} custom price(s)" + (f", {cl} reset to normal" if cl else "") + (f", {bad} invalid ignored (use a number above 0)" if bad else ""))
    if a in ("rgapi_on", "rgapi_off", "rgapi_regen"):            # V20: RGAPI switch on a user's profile / the RGAPI page
        if a == "rgapi_on":
            if rgapi.enable(uid):
                flash("✅ RGAPI is ON for this user. He now sees the RGAPI System button in My Profile.")
                bot.safe(bot.send, uid, "🔑 <b>RGAPI System activated!</b>\nOpen <b>My Profile</b> → <b>RGAPI System</b> to get your API token, product IDs and connection guide.")
        elif a == "rgapi_off":
            rgapi.disable(uid)
            flash("RGAPI turned OFF - his token stops working at once.")
        else:
            rgapi.regen(uid)
            flash("✅ New API token created. The old token no longer works.")
    if a == "msg":
        txt = request.form.get("text", "").strip()
        r = bot.send(uid, bot.esc(txt)) if txt else {"ok": False}
        flash("Message sent." if r.get("ok") else "Could not send (the user blocked the bot or never started it).")
    if a in ("rok", "rno"):
        ok = a == "rok"
        amt = db.hold_decide(uid, ok)
        if amt > 0:
            bot.safe(bot.refund_user_msg, uid, ok, amt, 0)
        flash(("Refund approved: " if ok else "Refund deducted: ") + f"{amt:.2f}")
    return redirect(request.referrer or "/users")


def num(x, default=0.0):
    try:
        return max(float(x), 0.0)
    except (TypeError, ValueError):
        return default


import re


def plan_parts(name):
    """'10 days' -> ('10','days');  anything else -> None (shown as free text)"""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(hours?|hrs?|days?)\s*", name or "", re.I)
    if not m:
        return None
    n = float(m.group(1))
    return (str(int(n)) if n == int(n) else str(n), "hours" if m.group(2).lower().startswith("h") else "days")


def plan_name(n, unit):
    n = num(n)
    return f"{int(n) if n == int(n) else n} {'hours' if unit == 'hours' else 'days'}" if n > 0 else ""


app.jinja_env.filters["pp"] = plan_parts


def parse_plan_rows(f):
    out = []
    for dur, unit, up, rp in zip(f.getlist("dur"), f.getlist("unit"), f.getlist("uprice"), f.getlist("rprice")):
        name, price = plan_name(dur, unit), num(up)
        if name and price > 0:
            out.append((name, price, num(rp)))
    return out


def cat_of(f):
    """category id from a form (0 = none / unknown id)"""
    try:
        cid = int(f.get("cat_id") or 0)
    except ValueError:
        return 0
    return cid if cid and db.cat(cid) else 0


def eid_ok(v):
    v = (v or "").strip()
    return v if v.isdigit() else ""


@app.route("/categories", methods=["GET", "POST"])
def categories():
    if request.method == "POST":
        f, a = request.form, request.form.get("a")
        with db.conn() as c:
            if a == "add" and f.get("name", "").strip():
                if f.get("eid", "").strip() and not eid_ok(f.get("eid")):
                    flash("Premium emoji ID must be digits only - category added without it.")
                c.execute("INSERT INTO categories(name,emoji,eid,sort) VALUES(?,?,?,?)",
                          (f["name"].strip(), f.get("emoji", "").strip(), eid_ok(f.get("eid")), int(num(f.get("sort")))))
                flash("Category added")
            elif a == "save" and f.get("cid", "").isdigit():
                if f.get("eid", "").strip() and not eid_ok(f.get("eid")):
                    flash("Premium emoji ID must be digits only - ID not saved.")
                c.execute("UPDATE categories SET name=?, emoji=?, eid=?, sort=?, active=? WHERE id=?",
                          (f.get("name", "").strip() or "Category", f.get("emoji", "").strip(), eid_ok(f.get("eid")),
                           int(num(f.get("sort"))), 1 if f.get("active") == "1" else 0, int(f["cid"])))
                flash("Saved")
            elif a == "del" and f.get("cid", "").isdigit():
                c.execute("UPDATE products SET cat_id=0 WHERE cat_id=?", (int(f["cid"]),))
                c.execute("DELETE FROM categories WHERE id=?", (int(f["cid"]),))
                flash("Category deleted (its products are now under the other button)")
            elif a == "text":
                for k in ("cat_title", "cat_text", "cat_other_name"):
                    if k in f:
                        db.put(k, f[k].strip())
                flash("Saved")
        db.emoji_clear()
        return redirect("/categories")
    return page("categories", rows=db.cats(False), tab="categories")


@app.route("/categories/preview", methods=["POST"])
def categories_preview():
    flash("Sent to your Telegram - check the bot chat." if bot.send_cat_preview() else "ADMIN_ID is not set.")
    return redirect("/categories")


@app.route("/products/new", methods=["GET", "POST"])
def product_new():
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        plans = parse_plan_rows(f)
        if not name:
            flash("Enter the product name")
            return redirect("/products/new")
        with db.conn() as c:
            eid = f.get("emoji_id", "").strip()
            cur = c.execute("INSERT INTO products(name,link,emoji_id,cat_id) VALUES(?,?,?,?)", (name, f.get("link", "").strip(), eid if eid.isdigit() else "", cat_of(f)))
            pid = cur.lastrowid
            for n, (pn, pr, rp) in enumerate(plans):
                c.execute("INSERT INTO plans(product_id,name,price,rprice,sort) VALUES(?,?,?,?,?)", (pid, pn, pr, rp, n))
        flash(f"Product added with {len(plans)} plan(s). Now open a plan and add its keys.")
        return redirect(f"/products/{pid}")
    return page("newproduct", tab="products")


@app.route("/products", methods=["GET", "POST"])
def products():
    if request.method == "POST" and request.form.get("name", "").strip():
        with db.conn() as c:
            c.execute("INSERT INTO products(name,descr) VALUES(?,?)", (request.form["name"].strip(), request.form.get("descr", "").strip()))
        flash("Product added")
        return redirect("/products")
    allrows = db.products(False)
    valid = {c["id"] for c in db.cats(False)}
    none_ = [p for p in allrows if not p["cat_id"] or p["cat_id"] not in valid]
    cf = request.args.get("cat", "all")
    if cf == "none":
        rows = none_
    elif cf.isdigit() and int(cf) in valid:
        rows = [p for p in allrows if p["cat_id"] == int(cf)]
    else:
        cf, rows = "all", allrows
    return page("products", rows=rows, tab="products", cf=cf, n_all=len(allrows), n_none=len(none_))


@app.route("/products/bulk", methods=["POST"])
def products_bulk():
    """tick many products -> move them to a category / show / hide in ONE tap"""
    f, a = request.form, request.form.get("a")
    ids = [int(x) for x in f.getlist("pid") if x.isdigit()][:900]
    back = request.referrer or "/products"
    if a == "delall":                                   # V18: delete EVERY product (must type DELETE)
        if f.get("confirm", "").strip() != "DELETE":
            flash("⚠️ Nothing deleted - you did not confirm")
            return redirect(back)
        with db.conn() as c:
            n = c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            c.execute("DELETE FROM keys WHERE used=0 AND plan_id IN (SELECT id FROM plans)")
            c.execute("DELETE FROM plans")
            c.execute("DELETE FROM products")
        db.emoji_clear()
        flash(f"🗑️ ALL {n} product(s) deleted")
        return redirect("/products")
    if not ids:
        flash("⚠️ Tick at least one product first")
        return redirect(back)
    q = ",".join("?" * len(ids))
    with db.conn() as c:
        if a == "del":
            c.execute(f"DELETE FROM keys WHERE used=0 AND plan_id IN (SELECT id FROM plans WHERE product_id IN ({q}))", ids)
            c.execute(f"DELETE FROM plans WHERE product_id IN ({q})", ids)
            c.execute(f"DELETE FROM products WHERE id IN ({q})", ids)
            flash(f"🗑️ {len(ids)} product(s) deleted")
        elif a == "move":
            if f.get("cat_id", "") == "":
                flash("⚠️ Choose a category in the box first")
                return redirect(back)
            cid = cat_of(f)
            c.execute(f"UPDATE products SET cat_id=? WHERE id IN ({q})", [cid] + ids)
            name = db.cat(cid)["name"] if cid else "no category"
            flash(f"✅ {len(ids)} product(s) moved to {name}")
        elif a in ("show", "hide"):
            c.execute(f"UPDATE products SET active=? WHERE id IN ({q})", [1 if a == "show" else 0] + ids)
            flash(f"✅ {len(ids)} product(s) are now {'visible' if a == 'show' else 'hidden'}")
    db.emoji_clear()
    return redirect(back)


@app.route("/categories/<int:cid>/assign", methods=["GET", "POST"])
def category_assign(cid):
    c_ = db.cat(cid)
    if not c_:
        return redirect("/categories")
    if request.method == "POST":
        ids = {int(x) for x in request.form.getlist("pid") if x.isdigit()}
        with db.conn() as c:
            c.execute("UPDATE products SET cat_id=0 WHERE cat_id=?", (cid,))          # unticked leave
            for i in list(ids)[:900]:
                c.execute("UPDATE products SET cat_id=? WHERE id=?", (cid, i))
        db.emoji_clear()
        flash(f"✅ Saved - {len(ids)} product(s) are in {c_['name']}")
        return redirect(f"/categories/{cid}/assign")
    names = {x["id"]: x["name"] for x in db.cats(False)}
    return page("assign", c=c_, rows=db.products(False), names=names, tab="categories")


@app.route("/products/<int:pid>", methods=["GET", "POST"])
def product_page(pid):
    p = db.product(pid)
    if not p:
        return redirect("/products")
    if request.method == "POST":
        a, f = request.form.get("a"), request.form
        with db.conn() as c:
            if a == "edit":
                eid = f.get("emoji_id", "").strip()
                if eid and not eid.isdigit():
                    eid = p["emoji_id"] or ""
                    flash("Emoji ID must be digits only - emoji not changed")
                c.execute("UPDATE products SET name=?, descr=?, link=?, active=?, sort=?, emoji_id=?, cat_id=? WHERE id=?",
                          (f.get("name", "").strip() or p["name"], f.get("descr", "").strip(), f.get("link", "").strip(), 1 if f.get("active") == "1" else 0, int(num(f.get("sort"))), eid, cat_of(f), pid))
                flash("Saved")
            elif a == "setcat":
                c.execute("UPDATE products SET cat_id=? WHERE id=?", (cat_of(f), pid))
                flash("Category saved")
                return redirect(request.referrer or "/products")
            elif a == "del":
                c.execute("DELETE FROM keys WHERE used=0 AND plan_id IN (SELECT id FROM plans WHERE product_id=?)", (pid,))
                c.execute("DELETE FROM plans WHERE product_id=?", (pid,))
                c.execute("DELETE FROM products WHERE id=?", (pid,))
                flash("Product deleted")
                return redirect("/products")
            elif a == "addplans":
                rows_ = parse_plan_rows(f)
                base = c.execute("SELECT COALESCE(MAX(sort),0) FROM plans WHERE product_id=?", (pid,)).fetchone()[0]
                for n, (pn, pr, rp) in enumerate(rows_, 1):
                    c.execute("INSERT INTO plans(product_id,name,price,rprice,sort) VALUES(?,?,?,?,?)", (pid, pn, pr, rp, base + n))
                flash(f"{len(rows_)} plan(s) added" if rows_ else "Enter duration and price")
            elif a == "addplan" and f.get("name", "").strip():
                c.execute("INSERT INTO plans(product_id,name,price,rprice) VALUES(?,?,?,?)",
                          (pid, f["name"].strip(), num(f.get("price")), num(f.get("rprice"))))
                flash("Plan added")
            elif a == "saveplan":
                pname = plan_name(f.get("dur"), f.get("unit")) if f.get("dur") else f.get("name", "").strip()
                old = c.execute("SELECT price, rprice, api_plan_id, manual FROM plans WHERE id=? AND product_id=?", (int(f.get("plan_id", 0)), pid)).fetchone()
                manual = old["manual"] if old else 0
                if old and old["api_plan_id"] and (abs(num(f.get("price")) - old["price"]) > 0.001 or abs(num(f.get("rprice")) - old["rprice"]) > 0.001):
                    manual = 1                      # price edited by hand: auto-sync will not overwrite it
                oos = 1 if f.get("oos") == "1" else 0
                c.execute("UPDATE plans SET name=?, price=?, rprice=?, active=?, manual=?, oos=? WHERE id=? AND product_id=?",
                          (pname or "Plan", num(f.get("price")), num(f.get("rprice")), 1 if f.get("active") == "1" else 0, manual, oos, int(f.get("plan_id", 0)), pid))
                flash("Plan saved" + (" - ❌ Out of Stock" if oos else ""))
            elif a in ("outstock", "instock"):          # V22: one-tap Out of Stock / In stock
                c.execute("UPDATE plans SET oos=? WHERE id=? AND product_id=?", (1 if a == "outstock" else 0, int(f.get("plan_id", 0)), pid))
                flash("❌ Plan marked Out of Stock" if a == "outstock" else "✅ Plan is In stock again")
            elif a in ("alloos", "allin"):              # V22: whole product
                c.execute("UPDATE plans SET oos=? WHERE product_id=?", (1 if a == "alloos" else 0, pid))
                flash("❌ All plans are Out of Stock" if a == "alloos" else "✅ All plans are In stock")
            elif a == "autoprice":
                row = c.execute("SELECT base_price FROM plans WHERE id=? AND product_id=? AND api_plan_id>0", (int(f.get("plan_id", 0)), pid)).fetchone()
                if row:
                    up_, rp_ = panel.calc(row["base_price"])
                    c.execute("UPDATE plans SET price=?, rprice=?, manual=0 WHERE id=?", (up_, rp_, int(f.get("plan_id", 0))))
                    flash("Price is automatic again")
            elif a == "delplan":
                plid = int(f.get("plan_id", 0))
                c.execute("DELETE FROM keys WHERE plan_id=? AND used=0", (plid,))
                c.execute("DELETE FROM plans WHERE id=? AND product_id=?", (plid, pid))
                flash("Plan deleted")
        return redirect(f"/products/{pid}")
    return page("product", p=p, plans=db.plans_of(pid, False), tab="products")


@app.route("/plans/<int:plid>", methods=["GET", "POST"])
def plan_page(plid):
    pl = db.plan(plid)
    if not pl:
        return redirect("/products")
    if request.method == "POST":
        a = request.form.get("a")
        if a == "add":
            n = db.add_keys(plid, request.form.get("keys", ""))
            flash(f"{n} key(s) added")
        elif a == "delkey":
            with db.conn() as c:
                c.execute("DELETE FROM keys WHERE id=? AND plan_id=? AND used=0", (int(request.form.get("kid", 0)), plid))
        elif a == "clear":
            with db.conn() as c:
                c.execute("DELETE FROM keys WHERE plan_id=? AND used=0", (plid,))
            flash("Unsold keys deleted")
        return redirect(f"/plans/{plid}")
    with db.conn() as c:
        keys = c.execute("SELECT id, code FROM keys WHERE plan_id=? AND used=0 ORDER BY id LIMIT 200", (plid,)).fetchall()
    return page("plan", pl=pl, keys=keys, tab="products")


@app.route("/deposits")
def deposits():
    tabs = [("review", "To review"), ("pending", "Waiting for user"), ("paid", "Approved"), ("rejected", "Rejected"), ("cancelled", "Cancelled")]
    st = request.args.get("s", "review")
    if st not in dict(tabs):
        st = "review"
    with db.conn() as c:
        rows = c.execute("""SELECT d.*, u.name, u.symbol FROM deposits d LEFT JOIN users u ON u.id=d.user_id
                            WHERE d.status=? ORDER BY d.id DESC LIMIT 100""", (st,)).fetchall()
    return page("deposits", rows=rows, s=st, tabs=tabs, tab="deposits")


@app.route("/deposits/<int:did>", methods=["POST"])
def deposit_action(did):
    d = bot.approve_deposit(did, request.form.get("a") == "ok")
    flash("Done" if d else "Already handled")
    return redirect(request.referrer or "/deposits")


@app.route("/proof/<int:did>")
def proof(did):
    d = db.dep_get(did)
    data = bot.fetch_file(d["proof"]) if d and d["proof"] else None
    if not data:
        return "No proof", 404
    return Response(data, mimetype="image/jpeg")


@app.route("/orders")
def orders():
    q = request.args.get("q", "").strip()
    with db.conn() as c:
        if q:
            rows = c.execute("SELECT * FROM orders WHERE CAST(user_id AS TEXT)=? OR order_no LIKE ? ORDER BY id DESC LIMIT 200", (q, f"%{q}%")).fetchall()
        else:
            rows = c.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 200").fetchall()
    return page("orders", rows=rows, q=q, tab="orders")


@app.route("/backup", methods=["GET", "POST"])
def backup_page():
    if request.method == "POST":
        a = request.form.get("a")
        if a == "now":
            ok, msg = backup.run_now()
            flash(msg)
        elif a == "send":                      # V18: Send Backup -> goes to the saved Chat ID
            ok, msg = backup.send_backup(bot.send_doc_to)
            flash(msg)
        elif a == "auto":                      # V18: timer settings
            ok, msg = backup.save_auto(request.form.get("chat"), request.form.get("hours"), request.form.get("on") == "1")
            flash(msg)
        elif a == "restore":
            f = request.files.get("f")
            if f and backup.restore_bytes(f.read()):
                db.init()
                db.emoji_clear()
                flash("Restored successfully")
            else:
                flash("Restore failed: not a valid backup file")
        return redirect("/backup")
    return page("backup", st=backup.STATUS, gh=backup.enabled(), ac=backup.auto_info(), tab="backup")


@app.route("/backup/download")
def backup_download():
    return Response(backup.snapshot(), mimetype="application/gzip",
                    headers={"Content-Disposition": "attachment; filename=rg_backup_" + time.strftime("%Y%m%d_%H%M") + ".db.gz"})


BC = {"last": ""}


@app.route("/broadcast", methods=["GET", "POST"])
def broadcast_page():
    if request.method == "POST":
        text = request.form.get("text", "").strip()
        if text:
            ids = None if request.form.get("to") == "all" else [bot.ADMIN_ID]
            n = len(ids or db.broadcast_targets())
            BC["last"] = f"sending to {n} user(s)..."

            def done(ok, fail):
                BC["last"] = f"{time.strftime('%H:%M')} - delivered {ok}, failed {fail}"
            bot.broadcast(text, ids, done)
            flash(f"Broadcast started for {n} user(s)")
        return redirect("/broadcast")
    return page("broadcast", last=BC["last"], tab="broadcast")


@app.route("/orders.csv")
def orders_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["order_no", "user_id", "product", "plan", "price", "key", "time"])
    with db.conn() as c:
        for o in c.execute("SELECT * FROM orders ORDER BY id DESC"):
            w.writerow([o["order_no"], o["user_id"], o["product"], o["plan"], o["price"], o["key"], o["created"]])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=orders.csv"})


# ------------------------------------------------------------------ Part 4: QR payment page, webhook, payments, coupons
@app.route("/pay/<token>")
def pay_page(token):
    p = db.pay_by_token(token)
    if not p:
        return "Payment not found", 404
    u = db.user(p["user_id"])
    exp = int(db.get("pay_expire", "10") or 10) * 60
    left = max(int(p["created"] + exp - time.time()), 0)
    if p["status"] == "pending" and left <= 0:
        db.pay_update(p["pay_no"], status="expired")
        p = db.pay_get(p["pay_no"])
    qr = ""
    if p["status"] == "pending" and segno and (p["upi_uri"] or p["pay_url"]):
        qr = segno.make(p["upi_uri"] or p["pay_url"], error="m").svg_inline(scale=6, border=1, dark="#000", light="#fff")
    return render_template_string(PAYPAGE, p=p, qr=qr, left=left, shop=db.get("pay_name") or db.get("shop_name"),
                                  sym=u["symbol"] if u else "₹", bot_user=bot.BOT_USERNAME["v"])


@app.route("/pay/<token>/status")
def pay_status(token):
    p = db.pay_by_token(token)
    return {"status": p["status"] if p else "none"}


@app.route("/gateway/connect", methods=["POST"])
def gateway_connect():
    f = request.form
    for k in ("gw_gateway", "gw_token", "gw_base", "gw_webhook_secret", "pay_name", "pay_expire"):
        if k not in f:
            continue
        v = f[k].strip()
        if k == "gw_gateway" and v not in ("paytm", "fampay"):
            continue
        if k == "pay_expire" and not (v.isdigit() and 1 <= int(v) <= 60):
            continue
        if k == "gw_base":
            v = v.rstrip("/")
            if v and not v.startswith("http"):
                v = "https://" + v
        db.put(k, v)
    ok, msg = gateway.connect_test()
    db.put("gw_connected", "1" if ok else "0")
    flash(("✅ " if ok else "❌ ") + msg)
    return redirect("/settings")


@app.route("/webhook/gateway", methods=["GET", "POST"])
def gw_webhook():
    if request.method == "GET":
        return "ok"
    raw = request.get_data(as_text=True)
    secret = db.get("gw_webhook_secret").strip()
    signed = False
    if secret:
        if not gateway.verify_signature(secret, request.headers.get("X-Payment-Gateway-Timestamp", "0"),
                                        request.headers.get("X-Payment-Gateway-Signature", ""), raw):
            return "bad signature", 401
        signed = True
    try:
        d = json.loads(raw or "{}")
    except ValueError:
        d = {}
    if not isinstance(d, dict) or d.get("event") != "payment.success" or str(d.get("status", "")).upper() != "SUCCESS":
        return "ok"
    no = str(d.get("order_id") or "")
    p = db.pay_get(no) if no else None
    if not p:
        return "ok"
    txn = str(d.get("transaction_id") or "")
    if signed:
        try:
            paid_amt = float(d.get("amount"))
        except (TypeError, ValueError):
            paid_amt = None
        want = p["pay_amount"] or p["amount"]
        if paid_amt is not None and abs(paid_amt - want) > 0.01:
            return "amount mismatch", 200
        threading.Thread(target=bot.complete_pay, args=(no, txn), daemon=True).start()
    else:
        st, t2, _a = gateway.check(no)
        if st == "paid":
            threading.Thread(target=bot.complete_pay, args=(no, t2 or txn), daemon=True).start()
    return "ok"


@app.route("/find")
def find_page():
    q = request.args.get("q", "").strip()
    return page("find", q=q, hits=db.find_order(q) if q else [], tab="find")


@app.route("/payments")
def payments():
    tabs = [("review", "To review"), ("pending", "Waiting"), ("paid", "Paid"), ("rejected", "Rejected"), ("expired", "Expired"), ("cancelled", "Cancelled"), ("all", "All")]
    st = request.args.get("s", "review")
    q = """SELECT p.*, u.name, u.symbol FROM pay_orders p LEFT JOIN users u ON u.id=p.user_id"""
    qs = request.args.get("q", "").strip()
    conds, args = [], []
    if qs:
        st = "all"
        conds.append("(p.pay_no LIKE ? OR p.txn LIKE ? OR u.name LIKE ? OR CAST(p.user_id AS TEXT)=?)")
        args += [f"%{qs}%", f"%{qs}%", f"%{qs}%", qs]
    elif st != "all":
        conds.append("p.status=?")
        args.append(st)
    with db.conn() as c:
        rows = c.execute(q + (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY p.id DESC LIMIT 150", args).fetchall()
    return page("payments", rows=rows, s=st, tabs=tabs, tab="payments", qs=qs)


@app.route("/payments/<no>", methods=["POST"])
def payment_action(no):
    if request.form.get("a") == "ok":
        pp = db.pay_get(no)
        p = bot.complete_pay(no, (pp["txn"] if pp else "") or "ADMIN-" + time.strftime("%H%M%S"))
        flash("Approved and delivered" if p else "Already handled")
    else:
        p = bot.reject_pay(no)
        flash("Rejected, user informed" if p else "Already handled")
    return redirect(request.referrer or "/payments")


@app.route("/payproof/<no>")
def payproof(no):
    p = db.pay_get(no)
    data = bot.fetch_file(p["proof"]) if p and p["proof"] else None
    if not data:
        return "No proof", 404
    return Response(data, mimetype="image/jpeg")


@app.route("/coupons", methods=["GET", "POST"])
def coupons():
    if request.method == "POST":
        a, f = request.form.get("a"), request.form
        code = "".join(ch for ch in f.get("code", "").upper() if ch.isalnum())[:32]
        with db.conn() as c:
            if a == "add" and code:
                kind = "flat" if f.get("kind") == "flat" else "percent"
                val = num(f.get("value"))
                if val <= 0 or (kind == "percent" and val > 100):
                    flash("Invalid value")
                else:
                    days = int(num(f.get("days")))
                    c.execute("INSERT OR REPLACE INTO coupons(code,kind,value,max_uses,used,expires,active,created) VALUES(?,?,?,?,COALESCE((SELECT used FROM coupons WHERE code=?),0),?,1,?)",
                              (code, kind, val, int(num(f.get("max_uses"))), code, int(time.time()) + days * 86400 if days else 0, int(time.time())))
                    flash("Coupon saved")
            elif a == "toggle" and code:
                c.execute("UPDATE coupons SET active=1-active WHERE code=?", (code,))
            elif a == "del" and code:
                c.execute("DELETE FROM coupons WHERE code=?", (code,))
        return redirect("/coupons")
    with db.conn() as c:
        rows = c.execute("SELECT * FROM coupons ORDER BY created DESC").fetchall()
    return page("coupons", rows=rows, tab="coupons")


# ------------------------------------------------------------------ PART 10: Panel API
def _panel_counts():
    with db.conn() as c:
        return (c.execute("SELECT COUNT(*) FROM products WHERE api_pid>0").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM plans WHERE api_plan_id>0").fetchone()[0])


@app.route("/panel")
def panel_page():
    rp, up = panel.markups()
    ex_u, ex_r = panel.calc(100, rp, up)
    np_, nl = _panel_counts()
    return page("panel", tab="panel", rp=rp, up=up, ex_r=ex_r, ex_u=ex_u, np=np_, nl=nl, default_url=panel.DEFAULT_URL)


@app.route("/panel/connect", methods=["POST"])
def panel_connect():
    f = request.form
    url = f.get("panel_url", "").strip().rstrip("/")
    if url and not url.startswith("http"):
        url = "https://" + url
    db.put("panel_url", url or panel.DEFAULT_URL)
    db.put("panel_token", f.get("panel_token", "").strip())
    ok, msg = panel.connect_test()
    db.put("panel_connected", "1" if ok else "0")
    flash(("✅ " if ok else "❌ ") + msg)
    return redirect("/panel")


@app.route("/panel/balance", methods=["POST"])
def panel_balance():
    f = request.form
    if f.get("panel_token", "").strip() and f.get("panel_token").strip() != db.get("panel_token"):
        db.put("panel_token", f.get("panel_token").strip())      # token typed but not saved yet
    try:
        flash("💰 Panel balance: ₹%.2f" % panel.balance())
    except panel.PanelError as e:
        flash("❌ " + e.msg)
    return redirect("/panel")


@app.route("/panel/markup", methods=["POST"])
def panel_markup():
    f = request.form
    try:
        r, u = float(f.get("mk_reseller", "")), float(f.get("mk_user", ""))
        if not (0 <= r <= 10000 and 0 <= u <= 10000):
            raise ValueError
    except ValueError:
        flash("Enter the percentages as numbers (0 or more)")
        return redirect("/panel")
    db.put("panel_mk_reseller", ("%g" % r))
    db.put("panel_mk_user", ("%g" % u))
    if f.get("a") == "apply":
        flash(f"Saved. Reseller +{r:g}% · User +{u:g}% applied to {panel.reprice_all(force=True)} plan(s).")
    else:
        flash("Percentages saved. New products use them. Press 'Save & apply to ALL products' to update the existing ones.")
    return redirect("/panel")


@app.route("/panel/auto", methods=["POST"])
def panel_auto():
    f = request.form
    db.put("panel_autosync", "0" if f.get("panel_autosync") == "0" else "1")
    v = f.get("panel_sync_min", "").strip()
    if v.isdigit() and 5 <= int(v) <= 1440:
        db.put("panel_sync_min", v)
    flash("Saved")
    return redirect("/panel")


@app.route("/panel/sync", methods=["POST"])
def panel_sync():
    try:
        ul, nl, miss = panel.sync_existing()
        flash(f"✅ Synced: {ul} plan price(s) refreshed, {nl} new plan(s) added" + (f", ⚠️ {miss} plan(s) no longer on the panel (buying them will fail - hide them)" if miss else ""))
    except panel.PanelError as e:
        flash("❌ " + e.msg)
    return redirect("/panel")


@app.route("/panel/products")
def panel_products():
    try:
        plist = panel.products()
    except panel.PanelError as e:
        flash("❌ " + e.msg)
        return redirect("/panel")
    with db.conn() as c:
        have = {r["api_pid"] for r in c.execute("SELECT api_pid FROM products WHERE api_pid>0")}
    rp, up = panel.markups()
    rows = []
    for p in plist:
        try:
            pid = int(p.get("product_id"))
        except (TypeError, ValueError):
            continue
        pls = []
        for pl in (p.get("plans") or []):
            base = panel._f(pl.get("price"))
            u_, r_ = panel.calc(base, rp, up)
            pls.append({"name": pl.get("name"), "base": base, "usr": u_, "res": r_})
        rows.append({"id": pid, "name": p.get("name") or f"Product {pid}", "plans": pls, "added": pid in have})
    rows.sort(key=lambda r: r["added"])                 # NEW products first
    return page("panelprod", tab="panel", rows=rows, rp=("%g" % rp), up=("%g" % up), n_new=sum(1 for r in rows if not r["added"]))


@app.route("/rgapi-admin")
def rgapi_admin():
    q = request.args.get("q", "").strip()
    found = db.search_users(q, "all", "new", 15, 0)[0] if q else []
    return page("rgapiadm", q=q, found=found, on=rgapi.enabled_users(), tab="rgapi", title="RGAPI")


@app.route("/panel/add", methods=["POST"])
def panel_add():
    f = request.form
    ids, plist = None, None
    if f.get("a") == "allnew":                           # V18: every product that is not in the shop yet
        try:
            plist = panel.products()
        except panel.PanelError as e:
            flash("❌ " + e.msg)
            return redirect("/panel/products")
        with db.conn() as c:
            have = {r["api_pid"] for r in c.execute("SELECT api_pid FROM products WHERE api_pid>0")}
        ids = [int(p["product_id"]) for p in plist if str(p.get("product_id", "")).isdigit() and int(p["product_id"]) not in have]
        if not ids:
            flash("No new products - everything on the panel is already in your shop")
            return redirect("/panel/products")
    elif f.get("a") != "all":
        ids = [int(x) for x in f.getlist("pid") if x.isdigit()]
        if not ids:
            flash("Select at least one product")
            return redirect("/panel/products")
    try:
        np_, nl, ul = panel.import_products(ids, plist)   # read fresh from the panel
    except panel.PanelError as e:
        flash("❌ " + e.msg)
        return redirect("/panel/products")
    cid = cat_of(f)
    if cid:
        with db.conn() as c:
            cond = "cat_id=0 OR cat_id NOT IN (SELECT id FROM categories)"
            if ids is None:
                c.execute(f"UPDATE products SET cat_id=? WHERE api_pid>0 AND ({cond})", (cid,))
            elif ids:
                c.execute(f"UPDATE products SET cat_id=? WHERE api_pid IN ({','.join('?' * len(ids))}) AND ({cond})", [cid] + ids)
        db.emoji_clear()
    flash(f"✅ {np_} new product(s), {nl} new plan(s) added, {ul} existing plan(s) refreshed. Prices are set by your % automatically.")
    return redirect("/products")
