RG Shop Bot - V10 = PART 10 / 2 (FINAL)  (includes everything from V1 to V9 part 9)
=====================================================
Replace ALL files in your GitHub repo with these and redeploy. Old data is kept. Env variables are the same.

1) YOUR GATEWAY (FamPay + Paytm) - fully automatic
   Website -> Settings -> "Payment Gateway":
     Gateway: Paytm or FamPay  |  API token  |  Base URL (changeable any time)  ->  press "Save & Connect".
   Connect shows "Connected successfully" (or the exact problem, e.g. Invalid API token).
   Pay via UPI creates the QR, detects the payment by itself (polling + webhook), then delivers the key / adds wallet balance.
   FamPay adds paise to the amount (e.g. 90.90 -> 91.27): the bot, QR page and success message show the EXACT amount to pay.
   Webhook (optional, faster): copy the Webhook URL shown in Settings into your gateway dashboard -> Webhooks,
   and paste its signing secret in Settings. Signature + timestamp + amount are verified. Without the secret the bot
   still works by checking payments every few seconds.
   If the gateway token is empty, Pay via UPI falls back to the manual UPI flow (UTR + admin approve).

2) STORE SCREENS (same style as your screenshots, prices in INR only)
   Shop: bot name, line, Product Lineup, your 4 lines (editable in Settings), "Pick what you want", products as buttons.
   Product: name / Account Type (User or Reseller) / See Current Plans & Pricing / tree of plans / CHOOSE A PLAN, Buy buttons.
   Checkout Summary: product, plan, quantity, price, Final Total (+ name, ID, phone, wallet balance).
   Buttons in order: Pay via Wallet (always shown) | Pay via UPI | Pay via Binance | Apply Coupon Code | BACK.
   After a purchase: key + [Join Telegram] (product's update group) + [Main Panel]. Not shown for Add Balance.
   Reseller sees the reseller price automatically (Users -> "Make reseller").

3) ADMIN: ADD PRODUCT (Website -> Products -> + Add product)
   Product name + update group link, then plan rows: Duration + Hours/Days + User price + Reseller price,
   "+ Add another plan" for more. Product page: edit name/link, edit each plan (duration, unit, prices), add plans, delete.

4) Phone number verification ON/OFF  (Settings -> "Store screen & sign-up").
5) Everything is INR now. Old users with other currencies were converted once to INR automatically.

V7 CHANGES
- Pay via UPI screen = your screenshot: QR photo + "UPI PAYMENT GATEWAY" caption (Amount, Order, Expires, Instant Verification, How to pay).
  Only ONE button: "Back to Store" (goes to the main menu). No verify button - payment is detected automatically,
  then the key is delivered. Order ID looks like ORD2026111414220951360A and is the same ID sent to your gateway.
  Amount = exact amount to pay (FamPay paise included).
- Wallet purchase message = your screenshot (WALLET PAYMENT SUCCESSFUL / ORDER DETAILS / YOUR KEY ...),
  buttons: "Join Telegram Group" (product update group) and "Main Menu".
- Purchase paid by UPI / Binance: first a "PAYMENT SUCCESSFUL" notification (Order ID, Transaction ID, amount),
  then the same delivery message (title PAYMENT SUCCESSFUL, Method: UPI Method / Binance Method) with the same two buttons.

V8 CHANGES
- QR not paid within 5 minutes -> the QR message is removed and this message is sent (same as your screenshot):
  PAYMENT EXPIRED / Order Id : <real order ID> / Not paid within 5 minutes / QR / payment details are no longer valid / Tap /start to begin a new order.
  The time is Settings -> "Payment valid for (minutes)" (now 5 by default). A payment that still arrives late is added automatically.
- FIND WHO MADE AN ORDER (admin):
  Website -> "Find Order": type the order ID (ORD... payment order, WAL... shop order), a transaction ID or a user ID -> shows the user
  (name, ID, @username, phone, wallet) and the order details. Website -> QR Payments also has a search box.
  Telegram (admin only): /find ORD2026...  gives the same details in the bot.

================ V9 - PART 9 (first half) ================
1) PREMIUM EMOJI - every button / line has its OWN slot (Website -> Premium Emoji, grouped)
   - Main menu: Shop Now, Add Balance, All History, My Profile, Referral, Tutorial, All Update File, Support = 8 separate slots.
   - Referral screen and Tutorial screen have their own slots too. Old IDs are copied once; the 3 Referral slots start EMPTY
     (set the emoji you want there). Saving warns you if the same ID is used in two places.
   - Button "Send main menu / shop / referral / tutorial to my Telegram" = real preview.
2) PRODUCT + PLAN EMOJI (Website -> Products)
   - "One emoji for ALL products" and "One emoji for ALL plans (A to Z)". Plans: shown on every plan line and Buy button.
   - Single product: open the product -> "Premium emoji ID for THIS product" (wins over the all-products emoji).
   - "Save & use for ALL products" clears every single-product emoji.
3) USER MESSAGES (new style, premium emoji slots 'Purchase / balance confirmation')
   - Key bought (wallet / UPI / Binance): Purchase Confirmed + Order Details + License Key.  Buttons: Join Update Group + Back to Main Menu.
   - Balance added: Payment Confirmed + Add Wallet Balance + Current Balance.  Button: Back to Main Menu only.
4) ADMIN NOTIFICATIONS (premium emoji slots 'Admin notifications'; each has a Contact User button)
   - NEW HACK PURCHASE (user or reseller, any payment method)
   - NEW WALLET BALANCE ADDED (previous / current balance, hacks purchased, total deposited, UTR)
   - PAYMENT SUCCESS - KEY DELIVERY FAILED (name, username, user ID, chat ID, phone ... + refund note)
   - NEW USER VERIFIED
   Settings -> "Admin notifications": ON/OFF for each, optional group/channel chat ID,
   and "Send sample messages to my Telegram" to preview everything with fake data.

================ V10 - PART 10 (second half): PANEL API ================
New file: panel.py.  New website tab: "Panel API".   Files changed: db.py, bot.py, web.py, main.py.
Replace ALL files in your GitHub repo and redeploy. Old data is kept (new columns are added automatically).

1) CONNECT  (Website -> Panel API -> step 1)
   Server URL (default https://official2-qg3g.onrender.com) + API token. Both can be changed any time.
   [Save & Connect] -> "Connect successful (username, balance ... INR)" or the exact problem (Invalid API token ...).
   [Check Balance] -> your panel balance.   [Show Products] -> every product that exists on your panel.
   (A sleeping Render panel can need up to a minute for the first call - just press again.)

2) ADD PRODUCTS  (Show Products)
   Tick the products you want and press [Add selected], or press [Add ALL products].
   Products, plans and prices come from the panel; you never add them by hand. Keys are bought from the panel
   automatically when a customer buys (wallet, UPI QR, Binance - all payment methods).
   Adding again later is safe: it only refreshes prices and adds NEW plans.

3) YOUR PRICES = PANEL PRICE + %   (Panel API -> step 2)
   Reseller %  (default 25)   and   User %  (default 200)  -> panel price 100 = reseller 125 / user 300.
   [Save %] = new products use it.   [Save & apply to ALL products] = every product is re-priced at once.
   A price you edit by hand on a product page is kept ("price: manual"); press [Auto] there to go back to the % price.
   The Products page shows the "Panel cost" of every plan.

4) AUTO PRICE SYNC (Panel API -> step 3)
   Every X minutes (default 60) the bot reads the panel prices again, applies your % and adds new plans.
   [Sync prices now] does it immediately.  Can be switched OFF.

5) WHEN A PURCHASE FAILS (panel says no / panel down / no panel balance)
   - Panel clearly refuses -> money is returned AUTOMATICALLY (wallet purchase: wallet refunded;
     UPI/QR payment: the amount is added to the user's wallet). The user gets a clear message.
   - Panel does not answer / crashes (unknown if the key was made) -> NO automatic refund, so you can never lose a key
     AND the money. The user is told "your order is being processed, do not buy again".
   - In both cases YOU get the alert immediately (name, username, user ID, chat ID, phone, product, plan, amount,
     order ID, reason, what happened to the wallet) with a Contact User button.
     For the "unknown" case check the panel order history, then send the key or add balance (Website -> Users).
   - Double tap on Buy while the panel is working is blocked ("previous order still processing").

Products you added the old way (keys pasted by hand) keep working exactly as before.

================ V11 ================
1) PREMIUM EMOJI IDs now live in main.py (PREMIUM_EMOJI dict at the top). Website "Premium Emoji" tab removed.
2) Website -> "Bot Token" tab: change BOT TOKEN (bot restarts on it instantly), ADMIN ID, and BOT NAME (optionally the Telegram profile name too).
   The token is saved in the database; it wins over the BOT_TOKEN env variable. The old hard-coded token was REMOVED from the code:
   set BOT_TOKEN env once OR paste the token on the website after the first deploy.

================ V12 ================
Files changed: db.py, bot.py, web.py (main.py untouched - your PREMIUM_EMOJI IDs stay there). Replace ALL files and redeploy. Old data is kept.
1) DEEP BOLD TITLES: shop name in the main menu, shop screen and category screen is now drawn in extra-thick letters
   (Settings -> "Look & feel" -> Deep bold titles ON/OFF).
2) PREMIUM EMOJI in the shop-screen lines (Premium Keys / Instant Delivery ...): a normal emoji typed in the line turns premium by itself
   when that emoji has an ID in main.py PREMIUM_EMOJI (key, fire, shield, ban, diamond, gift ...).
   Or write  🔥{premium ID}  in any line to use any premium emoji. Same rule works in the category-screen lines and category buttons.
3) CATEGORIES (Website -> Categories): Shop Now first shows the category buttons (NON ROOT PANEL, ROOT PANEL, IPHONE PANEL, PC PANEL, FF GUILD GLORY ...),
   the customer taps one and sees only that category's products. Add / rename / hide / delete / sort any number of categories,
   each with its own normal emoji + premium emoji ID. Category screen title and lines are editable there.
   Assign a product: Products list (drop-down), product page, or Add product form. Products without a category appear under
   one extra button (name editable). No categories at all = Shop Now shows all products as before.
   BACK from a product goes back to its category; BACK from a category goes to the category list.
4) BUTTON COLOUR (Settings -> Look & feel): Auto | all Blue | all Green | all Red | all White (normal).
5) Categories page has "Send category screen + shop to my Telegram" to preview.

================ V13 - REFUND SYSTEM ================
Files changed: db.py, bot.py, web.py (main.py unchanged). Replace ALL files and redeploy. Old data is kept.
1) WALLET purchase fails (server issue / out of stock / panel balance): nothing is charged, user gets "ORDER FAILED - NOTHING CHARGED" (reason: Server issue or Out of stock).
2) QR / UPI / Binance payment, but the key could not be delivered: the FULL paid amount goes back to the user's wallet as a REFUND HOLD
   and the user gets "ORDER FAILED - REFUND ISSUED" (reason, refunded amount, wallet balance, order ref).
3) The refund hold cannot be spent without your approval. Free wallet money (added earlier) can still be used normally.
   When a purchase needs refunded money, you get "REFUND BALANCE - APPROVAL NEEDED" (user, product, price, wallet, locked refund, free money) with Approve / Reject:
   - Approve -> the hold is released, the user is told and gets a "Continue to checkout" button.
   - Reject  -> ALL refunded money is taken back from the wallet, the user is told.
   One request per user at a time. My Profile shows "Refund (needs approval)".
4) Website -> Users: shows "Refund hold", buttons [Approve refund] / [Deduct refund], and a "refund hold" tick box next to the Balance button:
   tick it when YOU add money by hand as a refund (e.g. panel crashed, you checked, no key was made) - the user must then be approved before spending it.
5) Panel did not answer / crashed (unknown if a key was made): still NO automatic refund (as in V10) - you get the alert and decide.

================ V14 ================
Files changed: bot.py, web.py (main.py, db.py unchanged). Replace ALL files and redeploy. Old data is kept.
1) /START: a small "Welcome🎉" appears, the main menu follows at once, and as soon as the menu is on screen
   the Welcome message AND the user's own "/start" message are deleted automatically.
2) NEW ADMIN PANEL LOOK: side menu in groups (Store / Sales / Customers / System), phone-friendly (☰ button),
   Dashboard with quick actions + connection status, Settings has jump buttons and a Save button that stays on screen.
3) NO PAGE REFRESH: every Save / Move / Approve button works in the background. The page stays where you were
   and a small message pops up at the bottom ("Saved"). Slow actions show "⏳ ..." on the button.
4) BULK SELECT (Website -> Products): tick many products (or "Select all"), choose a category in the box, press Move -> all saved at once.
   Also Show / Hide for the ticked products, a search box, and category filter buttons (All / NON ROOT PANEL / No category ...).
5) CATEGORY -> "Products" button (Website -> Categories): one screen with every product as a big tick row.
   Tick the ones that belong to e.g. NON ROOT PANEL (or Select all) -> press Save. Unticked products leave that category.
6) PANEL API -> Show Products: new box "Put new products into category" - added products go straight into that category
   (only products that have no category yet are changed).

================ V15 - ADMIN ROLES + WEBSITE AUTO LOGIN + DEVICE SECURITY ================
Files changed: bot.py, web.py, main.py.  NEW file: secure.py.  Replace ALL files and redeploy. Old data is kept.
REQUIRED: env variable PUBLIC_URL (or RENDER_EXTERNAL_URL) must be an https:// address - the website button needs it.
1) MENUS: normal users / resellers see only /start.  Owner + admins see /start, /admin, /website.
   (Telegram's per-chat command menu is set by the bot itself, so it overrides the list from BotFather.)
2) /website (or /admin -> "Open Admin Website"): a button opens the website INSIDE Telegram and signs in by itself - no username/password.
   Telegram's signed data proves who tapped, so it only works for the owner and admins.
3) ADD / REMOVE ADMINS (owner only): /admin -> Manage Admins -> Add Admin (send the Telegram ID or forward his message) / Remove.
   Also /addadmin 123456789 and /removeadmin 123456789.  A removed admin loses the commands and any open website session at once.
4) DEVICE SECURITY for the username/password login:
   - Very first login ever = trusted automatically (you get a "First admin login" message).
   - Any NEW device with the correct password -> the owner gets "ADMIN LOGIN - NEW DEVICE" in Telegram (device, IP, time)
     with [Yes, it's me] / [No - Ban].  The login page waits for the answer (3 minutes, then it is refused).
       Yes -> that device is trusted and enters.   No -> device + IP are banned and a red "ACCESS BLOCKED" page is shown.
   - /admin -> Security: see trusted devices and bans, "Remove trusted devices", "Unban all".
   - Telegram auto-login (point 2) is never blocked by a ban made against somebody else.
5) CHANGE THE DEFAULT PASSWORD: set env ADMIN_USER and ADMIN_PASS on Render (the code default is public in the files).

================ V16 - BROADCAST FROM THE BOT ================
Files changed: bot.py, secure.py.  NEW file: bcast.py.  Replace ALL files and redeploy. Old data is kept (new tables are created by themselves).
Owner + admins: /broadcast  (or /admin -> Broadcast).
1) TARGET: All (users + resellers) | Only users | Only resellers | One person (Telegram ID, or forward his message).
2) CONTENT: text, photo, video, audio, voice, GIF, file, round video - sent exactly as you wrote it (caption, formatting, premium emoji kept).
   Flow: pick target -> send the message -> "Ready to send" -> Send now / Cancel.  Runs in the background, you get a report when it is done.
3) HISTORY (/broadcast -> Broadcast history): last 10, each with time, target, type, delivered / failed.
   - Edit: replaces the text (text broadcast) or the caption (photo / video / audio / file) for everyone who got it.
   - Delete from all: removes the message from every user's chat.
   Voice and round-video messages can be deleted but not edited (Telegram does not allow editing them).
4) The website Broadcast page still works as before (text only).

================ V17 - USERS: SEARCH + FULL PROFILE ================
Files changed: web.py, db.py, bot.py, secure.py.  Replace ALL files and redeploy. Old data is kept.
1) Website -> Users: every user in pages of 30, with Telegram ID, name + @username, phone, account type, Hacks bought, Spent, Balance.
   Filters: All / Users / Resellers / Not verified / Banned (with counts).  Sort: Newest / Top spenders / Most hacks bought / Highest balance.
2) SEARCH box: Telegram ID (= chat ID), phone number (+91 / spaces are ignored), @username, or name.  Exactly one match opens the profile at once.
3) PROFILE page (click a user): hacks bought, total spent, wallet balance, total deposited, referral balance, people referred,
   Telegram ID, @username (opens Telegram), phone, country, account type, verified / banned, joined, first + last purchase, referred by,
   hacks bought per product, FULL order history with every key, deposit history, list of people he referred.
   Actions on the profile: add / remove balance (+ refund hold), approve / deduct refund, make reseller / user, ban / unban,
   and "send a message to this user" on Telegram.
4) Bot (owner + admins): /user <Telegram ID | @username | phone>  -> profile card in the chat + "Full profile (website)" button (opens that profile, no login).

================ V18 - BACKUP TIMER + SEND TO ANY CHAT ID ================
Files changed: backup.py, bot.py, web.py, main.py.  Replace ALL files and redeploy. Old data is kept.
Website -> Backup:
1) AUTO BACKUP TIMER: type a Chat ID, type every how many hours (1, 6, 12, 24 ... or 0.5 = 30 min, minimum 0.25), tick "Turn automatic backup ON", press Save.
   The bot then sends the database backup file to that Chat ID automatically, every N hours, even after a Render restart (last send time is stored).
   The first backup is sent within a minute after you turn it ON. If Telegram refuses (wrong ID, bot not started / not in the group), the page shows the error and it retries every 5 minutes.
2) SEND BACKUP button: makes a backup right now (GitHub too) and sends the file to the saved Chat ID.
3) Chat ID can be a person (he must press /start on the bot first), a group, or a channel (add the bot as admin). Groups / channels look like -1001234567890.
4) Timer OFF = old behaviour (file goes to the owner every 6 hours if data changed).

V18 (2) - DELETE MANY PRODUCTS + NEW PANEL PRODUCTS  (file changed: web.py)
Website -> Products: tick products (or "Select all", it also works with the search box / category filter) -> "Delete selected".
  "Delete ALL" removes every product; you must type DELETE to confirm. Plans and unsold keys of those products are removed, old orders/history stay.
Website -> Panel API -> Show Products: the list is read fresh from your panel every time you open or press Refresh.
  New products (not in your shop yet) show first with a 🆕 NEW badge. Chips: All / New / Added, plus a search box.
  Tick the ones you want -> "Add selected" (choose a category if you like), or "Add all NEW" to add every new product at once. Prices use your % automatically.

V18 (3) - PRODUCT CUSTOMIZE (special prices per user / reseller)   (files changed: db.py, web.py)
Website -> Users -> open a user/reseller profile (or search by Chat ID) -> bottom card "Product Customize" -> "Show all products & plans".
Every product and plan is listed with its normal price. Type a custom price (in Rs) for the plans you want, leave others empty, press "Save all prices" once.
That user then sees and pays the custom price in the bot (plan list, buy button, wallet, QR/UPI - everywhere). Other users are not affected.
Empty box = normal price again. "Reset all to normal" removes every custom price of that user. Custom prices are part of the database backup.


=====================================================================
V19 - PRODUCT DIRECT LINKS
=====================================================================
* Every product has its own link:  https://t.me/<YourBotUsername>?start=p_<product id>
* Made automatically for NEW products and for ALL OLD products (no database change, nothing to run).
* Tapping the link opens the bot and shows that product (plans + Buy buttons) directly.
  If the user is not phone-verified yet, the product opens right after verification.
  Hidden / deleted product -> the normal main menu opens.
* Website -> Products: "Link" column with a Copy button for each product, and "Copy ALL links"
  (copies "Name - link" for every product shown). Open a product to see its link on top.
* The link needs the bot username: it is loaded automatically when the bot starts (Bot Token saved).


=====================================================================
V20 - RGAPI (RESELLER API)  -  your resellers connect THEIR bot / website to YOUR shop
=====================================================================
Files changed: db.py, bot.py, web.py, main.py.  NEW file: rgapi.py.  Replace ALL files and redeploy. Old data is kept (new columns/tables are created by themselves).
REQUIRED: env PUBLIC_URL must be an https:// address (same as the admin website button).

1) TURN IT ON (Website -> RGAPI, or the "RGAPI System" card on a user's profile)
   Search by chat ID / name / phone / @username -> [Turn ON]. A token is created. The user gets a message and a new button
   "RGAPI System" in My Profile (above Back). Turn OFF = his token stops working at once. [New token] replaces the token.
   Works for resellers AND normal users. Prices: his custom price (Product Customize) > reseller price > user price.
2) WHAT HE SEES (button opens a website inside Telegram, signs in by itself, no password)
   Connect tab: Server URL + API token (copy / show / regenerate) + 5-step guide.
   Products tab: every product with Product ID, every plan with Plan ID and HIS price, search box, in-stock tag.
   API Docs tab: all endpoints, copy-ready code (cURL, Python, PHP, Node.js), error codes.   Orders tab: his API orders with keys.
3) CONNECT IN ONE STEP (reseller who runs an RG bot)
   His bot already has Website -> Panel API: paste Server URL + API token -> Save & Connect ("Connect successful") -> Check Balance ->
   Show Products -> tick products / "Add all" -> set Reseller % / User % -> Save & apply. His price = your price + his %.
   Prices re-sync automatically (his auto price sync). Nothing else to do.
4) API (header  X-API-Key: <token>)
   GET /api/v1/connect | /api/v1/balance | /api/v1/products(?ids=1,2) | /api/v1/orders | /api/v1/order/<order_id>
   POST /api/v1/purchase  {"plan_id": N, "reference": "unique-id"}  ->  {"success": true, "key": "..."}
5) SAFETY
   - Money comes from his bot wallet. Refunded money that is still locked (refund hold) cannot be spent by API.
   - Same "reference" can never buy twice (a timeout can be retried safely).
   - Product from your main panel fails clearly -> nothing charged (503). Panel does not answer -> NO auto refund, he gets
     "do not buy again" (500) and YOU get the alert (same rule as V10).
   - Rate limit: 180 requests/min, 60 purchases/min per token.  Banned user = API blocked.
   - You get the normal "NEW HACK PURCHASE" alert for every API order (payment method: RGAPI). Referral commission is not paid on API orders.
   - Web server now runs 16 threads (was 8) so slow API purchases never block the admin site.


================ V21 - SPEED FIX (many users at the same time) ================
Files changed: db.py, bot.py, backup.py.   Replace these 3 files (or the whole repo) and redeploy. Data and env variables unchanged.
- Settings are cached for 3 seconds (before: every message / button read the disk 40+ times).
- SQLite: synchronous=NORMAL + busy_timeout + bigger cache (no slow disk sync on every save).
- Telegram connection pool 10 -> 200 (before, with many users connections were dropped and rebuilt = slow).
- Worker threads 16 -> 64, so a few slow actions (panel buy, gateway) can not block the other users.
- Payment checking runs in parallel (one slow gateway call no longer delays the others).


================ V22 - PLAN SAVE FIX + OUT OF STOCK + SPEED ================
Files changed: web.py, db.py, bot.py, rgapi.py  (main.py unchanged - your PREMIUM_EMOJI IDs stay). Replace ALL files and redeploy. Old data is kept.
1) PRODUCT PAGE SAVE BUG FIXED: after one Save, the other plan Save buttons stopped working until the page was opened again.
   Cause: each plan row was a <form> inside a table row - after the no-refresh update the browser cut the inputs off the form.
   Now every row uses its own form id, so you can Save plans again and again without reopening. (Same fix on the Categories table.)
2) OUT OF STOCK (works for panel/API products too): Website -> Products -> open a product -> Plans table:
   - "Stock" column: In stock / Out of Stock + Save, or the one-tap red "Out of Stock" / green "In stock" button per plan.
   - "All plans Out of Stock" / "All plans In stock" for the whole product.
   Bot shows "❌ (Out of Stock)" on that plan + a red "Out of Stock" button, nobody can buy it (wallet, UPI/QR, Binance, RGAPI).
   If every plan of a product is out of stock, the shop list shows "Product · Out of Stock". Auto price sync never changes this switch.
3) SPEED: button taps are answered at once (loading clock stops immediately), Telegram calls retry on a dropped connection and on
   429 "too many requests" (before, the action was silently lost = "bot not responding"), message deletes run in the background,
   new database indexes for profile / history / referral / payment lookups.
4) Bug fix: Panel API -> "Add selected / Add all NEW" pointed to the RGAPI page by mistake - it adds products again.
5) PREMIUM ❌ ON OUT OF STOCK: new slot "oos" in main.py PREMIUM_EMOJI (red cross, same ID as the Cancel button).
   Used on: plan line "(Out of Stock)", the red Out of Stock button, product button in the shop list, checkout screen,
   and the "Reason: Out of stock" line in ORDER FAILED messages. Change the ID in main.py to use another emoji.
   (Pop-up alerts after a tap cannot show premium emoji - Telegram limit - they keep the normal ❌.)
