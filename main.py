import os, threading, time
import requests
import db, bot, web, backup, panel, secure

# =====================================================================
#  PREMIUM EMOJI IDs  -  PUT YOUR IDs HERE (once, inside the code)
#  Between the quotes "" paste the premium emoji ID (digits only).
#  Empty "" = normal emoji is shown. Everyone who runs this code sees the
#  premium emoji automatically - nothing to set on the website.
#  (Get an ID: send a premium emoji to the bot from the ADMIN account.)
# =====================================================================
ONE_EMOJI_FOR_ALL_PRODUCTS = "6142990495384609987"   # same premium emoji before every product name
ONE_EMOJI_FOR_ALL_PLANS = "6005570495603282482"      # same premium emoji on every plan line + Buy button

PREMIUM_EMOJI = {
    "top": "6141146421111300287",               # 🔝  Main menu title
    "party": "6142959455655960440",             # 🎉  Welcome line
    "bars": "6140966689614866077",              # 📶  Store highlights title
    "key": "6140861913887679512",               # 🔑  Premium Game Keys
    "fire": "6141106778563158041",              # 🔥  Instant Delivery
    "shield": "6143013061142782073",            # 🛡️  Secure Payments
    "gift": "6140936358555821070",              # 🎁  VIP Rewards
    "h24": "6140798460040847656",               # 🕐  24/7 Support line
    "tap": "6140856974675288623",               # 👇  Tap Product Store line
    "sale": "6140688749396238437",              # 💥  Shop Now button
    "money": "6143375633691976069",             # 💰  Add Balance button / titles
    "history": "5444856076954520455",           # 📜  All History button
    "user": "6140671964664046472",              # 👤  My Profile button
    "share": "6141038776345959792",             # 🔗  Referral button
    "yt": "6140866938999415767",                # ▶️  Tutorial / Watch Video
    "folder": "5316571734604790521",            # 📁  All Update File button
    "support": "6141216798445411800",           # 💬  Support button
    "cart": "6140997621969331424",              # 🛒  Orders
    "diamond": "6143355606259473869",           # 💎  Spent / lifetime spent
    "check": "6140718118382608136",             # ✅  ID / success
    "cancel": "6152347399466524710",            # ❌  Cancel button
    "confirm": "4969754504137278548",           # ✅  Confirm button
    "back": "6142931379454745597",              # ➡️  Back buttons
    "download": "6140978646803817445",          # 📥  Download All Keys
    "telegram": "5201691993775818138",          # ✈️  Chat on Telegram
    "whatsapp": "6140964172764029055",          # 📞  Chat on WhatsApp
    "megaphone": "6141072895566159509",         # 📣  Invite link line
    "chart": "6140966689614866077",             # 📊  Deposit limits
    "calendar": "6143442858520092650",          # 📅  Joined date
    "wallet": "6143112369376600310",            # 👛  Balance
    "info": "5294118805222479957",              # ℹ️  Notes
    "phone": "6140964172764029055",             # 📱  Phone
    "globe": "6142925207586741378",             # 🌐  Country
    "gift2": "6140936358555821070",             # 🎀  Referral balance
    "fire2": "6141106778563158041",             # 🔥  Name line
    "time": "6141054362782278896",              # ⏱  Order time
    "box": "6140966689614866077",               # 📦  Stock lines
    "bag": "6140997621969331424",               # 🛍️  Buy Now button
    "wait": "6141054362782278896",              # ⏳  Pending payment / admin alerts
    "paid": "6140784441267592769",              # 💳  I Have Paid button
    "qr": "6143375633691976069",                # 📲  QR payment title
    "receipt": "6140838154128597715",           # 🧾  Order summary title
    "idcard": "6140955071728329327",            # 🆔  User ID line
    "coupon": "6140830156899492069",            # 🎟️  Coupon button / line
    "success": "6140812843886322200",           # ✅  Payment successful title
    "txn": "6199626932036835673",               # 🔖  Transaction ID line
    "crown": "6140936371440723437",             # 👑  Account type line
    "ban": "6140937801664831687",               # 🚫  Order line (QR screen)
    "home": "6142929377999986746",              # 🏠  Main Panel button
    "lineup": "6140936371440723437",            # 🟧  Product Lineup title
    "upi": "6140784441267592769",               # 💳  Pay UPI button
    "binance": "6143355606259473869",           # 🟡  Pay Binance button
    "local": "6140969601602691703",             # 🏦  Pay Local (bKash/bank) button
    "b_shop": "6143363736632567248",            # 💥  Menu button: Shop Now
    "b_addbal": "6142930043719918238",          # 💰  Menu button: Add Balance
    "b_history": "5388922215347534633",         # 📜  Menu button: All History
    "b_profile": "6140671964664046472",         # 👤  Menu button: My Profile
    "b_referral": "6141038776345959792",        # 🔗  Menu button: Referral
    "b_tutorial": "6140866938999415767",        # ▶️  Menu button: Tutorial
    "b_update": "5316571734604790521",          # 📁  Menu button: All Update File
    "b_support": "6141216798445411800",         # 💬  Menu button: Support
    "r_title": "6141038776345959792",           # 🔗  Referral screen: title
    "r_money": "6142974114379341801",           # 💰  Referral screen: commission line
    "r_invite": "6141072895566159509",          # 📣  Referral screen: invite link line
    "r_send": "6140940597688541545",            # 🔗  Referral screen: Send Link button + share line
    "t_title": "6140933644136489327",           # ▶️  Tutorial screen: title
    "t_watch": "6140866938999415767",           # ▶️  Tutorial screen: Watch Guide Video button
    "c_title": "6142959455655960440",           # 💎  Confirmation: title
    "c_details": "6142918554682400788",         # 📋  Confirmation: Order Details heading
    "c_point": "6140856974675288623",           # 👇  Confirmation: pointing hand
    "c_order": "6143013061142782073",           # 🛡️  Confirmation: Order ID
    "c_product": "6140688749396238437",         # 🛒  Confirmation: Product
    "c_plan": "6141054362782278896",            # ⏱  Confirmation: Plan
    "c_date": "6143442858520092650",            # 📅  Confirmation: Date
    "c_time": "4970227504590619958",            # ⏰  Confirmation: Time
    "c_amount": "6143375633691976069",          # 💰  Confirmation: Amount
    "c_status": "6140784441267592769",          # 💳  Confirmation: Payment Status
    "c_ok": "6140812843886322200",              # ✅  Confirmation: Successful tick
    "c_key": "6140861913887679512",             # 🔑  Confirmation: Your License Key
    "c_arrow": "6140978646803817445",           # ➡️  Confirmation: arrow before the key
    "c_addbal": "6152136108550398060",          # 🎉  Confirmation: Add Wallet Balance
    "c_curbal": "5445221832074483553",          # ➕  Confirmation: Current Balance
    "c_shield": "6142929377999986746",          # 🛡️  Confirmation: thank-you line
    "c_rocket": "5294118805222479957",          # 🚀  Confirmation: rocket
    "c_line": "",            # ➖  Confirmation: divider line (repeated 10 times)
    "n_alert": "6141030723282280185",           # 🚨  Admin alert: siren in the title
    "n_user": "6140671964664046472",            # 👤  Admin alert: Name / User
    "n_link": "6140940597688541545",            # 🔗  Admin alert: Username
    "n_id": "6140955071728329327",              # 🆔  Admin alert: Telegram ID / Chat ID / Order ID
    "n_phone": "6140964172764029055",           # 📱  Admin alert: Phone
    "n_globe": "6142925207586741378",           # 🌐  Admin alert: Country
    "n_type": "6140794216613159976",            # 👥  Admin alert: Account type
    "n_game": "5197371802136892976",            # 🎮  Admin alert: Product / Hack purchased
    "n_plan": "6141054362782278896",            # ⏱  Admin alert: Plan
    "n_money": "6143375633691976069",           # 💰  Admin alert: Price / Amount
    "n_method": "6140784441267592769",          # 💳  Admin alert: Payment method
    "n_key": "6140861913887679512",             # 🔑  Admin alert: Key
    "n_date": "6143442858520092650",            # 📅  Admin alert: Date / Time
    "n_wallet": "6143112369376600310",          # 💼  Admin alert: Wallet / Balance
    "n_cash": "6142974114379341801",            # 💵  Admin alert: Amount added
    "n_diamond": "6143355606259473869",         # 💎  Admin alert: Total hack purchase value
    "n_inbox": "6140846293091623402",           # 📥  Admin alert: Total deposited
    "n_tag": "6140830156899492069",             # 🏷️  Admin alert: UTR / Transaction ID
    "n_fail": "6152347399466524710",            # ❌  Admin alert: Status (key not delivered)
    "n_note": "6142918554682400788",            # 📝  Admin alert: Reason
    "n_chat": "6141216798445411800",            # 💬  Admin alert: Chat ID
    "n_box": "6140966689614866077",             # 📦  Admin alert: Product (failed order)
}
# =====================================================================



def keepalive():
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    while True:
        time.sleep(240)
        try:
            requests.get(url + "/health", timeout=20)
        except Exception:
            pass


if __name__ == "__main__":
    backup.restore_if_missing()      # fresh Render disk -> pull last backup from GitHub
    db.init()
    bot.load_config()       # token / admin ID saved from the website
    if not bot.TOKEN:
        print("No bot token yet - open the website -> Bot Token and paste it.")
    db.CODE_EMOJI = {k: v.strip() for k, v in PREMIUM_EMOJI.items() if v and v.strip().isdigit()}
    db.CODE_ALL_PRODUCTS = ONE_EMOJI_FOR_ALL_PRODUCTS.strip()
    db.CODE_ALL_PLANS = ONE_EMOJI_FOR_ALL_PLANS.strip()
    db.emoji_clear()
    db.migrate_inr()
    db.migrate_v9()
    threading.Thread(target=keepalive, daemon=True).start()
    threading.Thread(target=secure.startup, daemon=True).start()      # V15: /start only for users, /admin /website for admins
    threading.Thread(target=bot.pay_watch, daemon=True).start()
    threading.Thread(target=panel.sync_loop, daemon=True).start()     # V10: keeps panel prices up to date
    threading.Thread(target=backup.loop, args=(bot.send_doc_admin, bot.send_doc_to), daemon=True).start()
    from waitress import serve
    threading.Thread(target=lambda: serve(web.app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")), threads=8), daemon=True).start()
    bot.run()
