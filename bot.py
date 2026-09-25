import os
import re
import math
import sqlite3
import asyncio
from datetime import datetime, timezone

import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

ORDER_URL = "https://t.me/Sijadsa"

MARKET = "TR"
LANGUAGES = "tr-TR,en-US"

STRONG_DEAL_MIN_DISCOUNT = 50

# تحديث العروض كل 30 دقيقة
DEALS_UPDATE_SECONDS = 1800

# عدد الألعاب التي نطلبها من قائمة العروض
DEALS_FETCH_COUNT = 200

# عدد الألعاب التي نعرضها للمستخدم
DEALS_DISPLAY_COUNT = 15

DB_FILE = "price_alerts.db"


# =========================================================
# GLOBAL DATA
# =========================================================

STRONG_DEALS_CACHE = []
STRONG_DEALS_UPDATED_AT = None

STRONG_DEALS_LOCK = asyncio.Lock()


# =========================================================
# DATABASE
# =========================================================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            game_name TEXT,
            url TEXT,
            old_price INTEGER,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS last_requests (
            user_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            game_name TEXT,
            url TEXT,
            current_price INTEGER,
            updated_at TEXT,
            PRIMARY KEY (user_id, product_id)
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# PRICE CALCULATION
# =========================================================

def calculate_price(price):
    price = float(price)

    if price <= 25:
        return 3000
    elif price <= 50:
        return 4000
    elif price <= 100:
        return 6000
    elif price <= 150:
        return 8000
    elif price <= 200:
        return 10000
    elif price <= 249:
        return 11000
    elif price <= 260:
        return 12000
    elif price <= 300:
        return 13000
    elif price <= 400:
        return 15000
    elif price <= 500:
        return 18000
    elif price <= 550:
        return 20000
    elif price <= 650:
        return 23000
    elif price <= 750:
        return 26000
    elif price <= 850:
        return 29000
    elif price <= 1000:
        return 33000

    extra = price - 1000
    extra_steps = math.ceil(extra / 100)

    return 33000 + (extra_steps * 3000)


def format_store_price(price):
    price = int(price)

    if price % 1000 == 0:
        return f"{price // 1000} ألف"

    return f"{price:,} دينار"


# =========================================================
# PRODUCT ID
# =========================================================

def extract_product_id(url):
    if not url:
        return None

    # Xbox Store IDs عادة 12 حرف/رقم
    patterns = [
        r"/([0-9A-Za-z]{12})(?:[/?#]|$)",
        r"[?&]cid=([0-9A-Za-z]{12})",
        r"\b([0-9A-Za-z]{12})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)

        if match:
            return match.group(1).upper()

    return None


# =========================================================
# HTTP
# =========================================================

def http_get_json(url, params=None, timeout=25):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=timeout,
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# MICROSOFT DISPLAY CATALOG
# =========================================================

def get_product_data(product_id):
    url = "https://displaycatalog.mp.microsoft.com/v7.0/products"

    params = {
        "bigIds": product_id,
        "market": MARKET,
        "languages": LANGUAGES,
        "fieldsTemplate": "Details",
        "actionFilter": "Browse",
    }

    try:
        data = http_get_json(url, params=params)

        products = data.get("Products", [])

        if not products:
            return None

        return products[0]

    except Exception as e:
        print("PRODUCT ERROR:", product_id, e)
        return None


# =========================================================
# HELPERS FOR PRODUCT DATA
# =========================================================

def find_numbers_by_key(obj, wanted_keys, result=None):
    if result is None:
        result = []

    if isinstance(obj, dict):
        for key, value in obj.items():

            key_lower = str(key).lower()

            if key_lower in wanted_keys:
                if isinstance(value, (int, float)):
                    result.append(float(value))

                elif isinstance(value, str):
                    try:
                        result.append(float(value))
                    except:
                        pass

            find_numbers_by_key(
                value,
                wanted_keys,
                result
            )

    elif isinstance(obj, list):
        for item in obj:
            find_numbers_by_key(
                item,
                wanted_keys,
                result
            )

    return result


def find_dates_by_key(obj, wanted_keys, result=None):
    if result is None:
        result = []

    if isinstance(obj, dict):
        for key, value in obj.items():

            key_lower = str(key).lower()

            if key_lower in wanted_keys:

                if isinstance(value, str):
                    if "T" in value or "-" in value:
                        result.append(value)

            find_dates_by_key(
                value,
                wanted_keys,
                result
            )

    elif isinstance(obj, list):
        for item in obj:
            find_dates_by_key(
                item,
                wanted_keys,
                result
            )

    return result


# =========================================================
# GAME NAME
# =========================================================

def get_game_name(product):
    try:
        localized = product.get("LocalizedProperties", [])

        if localized:

            first = localized[0]

            if first.get("ProductTitle"):
                return first["ProductTitle"]

            description = first.get("ProductDescription", {})

            if isinstance(description, dict):
                title = description.get("Title")

                if title:
                    return title

    except:
        pass

    return "لعبة Xbox"


# =========================================================
# PRICE EXTRACTION
# =========================================================

def get_price_info(product):
    """
    نحاول استخراج السعر الحالي والسعر الأصلي
    من DisplaySkuAvailabilities.
    """

    availabilities = product.get(
        "DisplaySkuAvailabilities",
        []
    )

    candidates = []

    for availability in availabilities:

        # فقط العناصر التي عندها سعر
        numbers_list = []

        # أسعار محتملة
        current_values = find_numbers_by_key(
            availability,
            {
                "listprice",
                "saleprice",
                "currentprice",
                "retailprice",
                "price",
            }
        )

        original_values = find_numbers_by_key(
            availability,
            {
                "msrp",
                "originalprice",
                "regularprice",
            }
        )

        if current_values:
            current = min(
                x for x in current_values
                if x >= 0
            )

            candidates.append(
                {
                    "current": current,
                    "original": (
                        max(original_values)
                        if original_values
                        else None
                    ),
                    "availability": availability,
                }
            )

    if not candidates:
        return None

    # نحاول اختيار المرشح الذي لديه تخفيض حقيقي
    for candidate in candidates:

        current = candidate["current"]
        original = candidate["original"]

        if (
            original is not None
            and original > current
            and original > 0
        ):
            return current, original, candidate["availability"]

    # إذا ماكو MSRP واضح
    candidate = candidates[0]

    return (
        candidate["current"],
        candidate["original"],
        candidate["availability"],
    )


# =========================================================
# EXPIRY
# =========================================================

def extract_expiry(availability):
    if not availability:
        return None

    dates = find_dates_by_key(
        availability,
        {
            "enddate",
            "endDate".lower(),
        }
    )

    if not dates:
        return None

    future_dates = []

    now = datetime.now(timezone.utc)

    for date_string in dates:

        try:
            normalized = date_string.replace(
                "Z",
                "+00:00"
            )

            dt = datetime.fromisoformat(
                normalized
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            if dt > now:
                future_dates.append(dt)

        except:
            continue

    if not future_dates:
        return None

    return min(future_dates)


def get_remaining_text(expiry):
    if not expiry:
        return "غير محدد"

    now = datetime.now(timezone.utc)

    if expiry <= now:
        return "انتهى التخفيض"

    seconds = int(
        (expiry - now).total_seconds()
    )

    days = seconds // 86400
    seconds %= 86400

    hours = seconds // 3600
    seconds %= 3600

    minutes = seconds // 60

    parts = []

    if days:
        parts.append(f"{days} يوم")

    if hours:
        parts.append(f"{hours} ساعة")

    if minutes:
        parts.append(f"{minutes} دقيقة")

    if not parts:
        return "أقل من دقيقة"

    return " ".join(parts)


# =========================================================
# DISCOUNT
# =========================================================

def calculate_discount(current, original):

    if not original or original <= 0:
        return 0

    if current >= original:
        return 0

    discount = (
        (original - current)
        / original
        * 100
    )

    return int(round(discount))


# =========================================================
# SAVE LAST REQUEST
# =========================================================

def save_last_request(
    user_id,
    product_id,
    game_name,
    url,
    current_price,
):

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO last_requests
        (
            user_id,
            product_id,
            game_name,
            url,
            current_price,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)

        ON CONFLICT(user_id, product_id)
        DO UPDATE SET
            game_name = excluded.game_name,
            url = excluded.url,
            current_price = excluded.current_price,
            updated_at = excluded.updated_at
    """, (
        user_id,
        product_id,
        game_name,
        url,
        current_price,
        datetime.now(timezone.utc).isoformat(),
    ))

    conn.commit()
    conn.close()


# =========================================================
# CHECK ACTIVE ALERT
# =========================================================

def has_active_alert(user_id, product_id):

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        SELECT id
        FROM alerts
        WHERE user_id = ?
        AND product_id = ?
        AND active = 1
        LIMIT 1
    """, (
        user_id,
        product_id,
    ))

    result = cur.fetchone()

    conn.close()

    return result is not None


# =========================================================
# GAME MESSAGE
# =========================================================

def build_game_message(
    game_name,
    discount,
    expiry,
    current_iqd,
):
    text = f"🎮 {game_name}\n\n"

    if discount > 0:

        text += "🔥 اللعبة عليها تخفيض!\n"
        text += f"📉 نسبة الخصم: {discount}%\n"

        if expiry:
            expiry_text = expiry.strftime(
                "%Y-%m-%d الساعة %H:%M"
            )

            text += f"⏳ ينتهي التخفيض: {expiry_text}\n"
            text += (
                f"📅 متبقي: "
                f"{get_remaining_text(expiry)}\n"
            )

    text += (
        f"\n💰 سعر اللعبة: "
        f"{format_store_price(current_iqd)} 🇮🇶"
    )

    return text


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    keyboard = [
        [
            InlineKeyboardButton(
                "🔥 العروض القوية",
                callback_data="strong_deals"
            )
        ]
    ]

    await update.message.reply_text(
        "يرجى إرسال رابط اللعبة من Xbox Store 👇",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# ID COMMAND
# =========================================================

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        f"🆔 Telegram ID:\n`{update.effective_user.id}`",
        parse_mode="Markdown"
    )


# =========================================================
# GAME URL
# =========================================================

async def handle_game_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    product_id = extract_product_id(text)

    if not product_id:

        await update.message.reply_text(
            "يرجى إرسال رابط لعبة من Xbox Store 🎮"
        )

        return

    await update.message.reply_text(
        "⏳ جاري جلب معلومات اللعبة..."
    )

    product = get_product_data(product_id)

    if not product:

        await update.message.reply_text(
            "❌ ماكدرت أجيب معلومات اللعبة."
        )

        return

    game_name = get_game_name(product)

    price_info = get_price_info(product)

    if not price_info:

        await update.message.reply_text(
            f"🎮 {game_name}\n\n"
            "❌ ماكدرت أتعرف على سعر اللعبة."
        )

        return

    current_price = price_info[0]
    original_price = price_info[1]
    availability = price_info[2]

    discount = calculate_discount(
        current_price,
        original_price
    )

    current_iqd = calculate_price(
        current_price
    )

    expiry = extract_expiry(
        availability
    )

    save_last_request(
        update.effective_user.id,
        product_id,
        game_name,
        text,
        current_iqd,
    )

    message = build_game_message(
        game_name,
        discount,
        expiry,
        current_iqd,
    )

    buttons = [
        [
            InlineKeyboardButton(
                "🛒 اطلب الآن",
                callback_data=f"order:{product_id}"
            )
        ]
    ]

    if has_active_alert(
        update.effective_user.id,
        product_id
    ):

        buttons.append([
            InlineKeyboardButton(
                "🔕 إلغاء التنبيه",
                callback_data=f"cancel:{product_id}"
            )
        ])

    else:

        buttons.append([
            InlineKeyboardButton(
                "🔔 نبهني إذا نزل السعر",
                callback_data=f"alert:{product_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔥 العروض القوية",
            callback_data="strong_deals"
        )
    ])

    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# =========================================================
# DEAL API
# =========================================================

def extract_product_ids(obj):
    """
    استخراج Xbox Product IDs من أي شكل JSON.
    """

    found = set()

    valid_keys = {
        "productid",
        "product_id",
        "bigid",
        "big_id",
        "id",
    }

    def walk(value, parent_key=""):

        if isinstance(value, dict):

            for key, child in value.items():

                key_lower = str(key).lower()

                if key_lower in valid_keys:

                    if isinstance(child, str):

                        candidate = child.strip()

                        if re.fullmatch(
                            r"[0-9A-Za-z]{12}",
                            candidate
                        ):
                            found.add(
                                candidate.upper()
                            )

                walk(child, key_lower)

        elif isinstance(value, list):

            for item in value:
                walk(item, parent_key)

        elif isinstance(value, str):

            # فقط إذا كنا داخل سياق ID
            if parent_key in valid_keys:

                if re.fullmatch(
                    r"[0-9A-Za-z]{12}",
                    value.strip()
                ):
                    found.add(
                        value.strip().upper()
                    )

    walk(obj)

    return list(found)


# =========================================================
# GET DEAL IDs
# =========================================================

def get_deal_product_ids():

    endpoint = (
        "https://reco-public.rec.mp.microsoft.com/"
        "channels/Reco/V8.0/Lists/api/list/"
        "Computed/Deal"
    )

    params = {
        "market": "tr",
        "language": "tr-tr",
        "itemType": "Game",
        "deviceFamily": "Windows.Xbox",
        "count": str(DEALS_FETCH_COUNT),
        "skipItems": "0",
    }

    print("🔥 Getting Xbox Deal list...")

    try:

        response = requests.get(
            endpoint,
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            },
            timeout=30,
        )

        print(
            "🔥 Deal API status:",
            response.status_code
        )

        if response.status_code != 200:

            print(
                "🔥 Deal API response:",
                response.text[:1000]
            )

            return []

        data = response.json()

        ids = extract_product_ids(data)

        print(
            "🔥 Product IDs found:",
            len(ids)
        )

        if not ids:

            if isinstance(data, dict):
                print(
                    "🔥 Deal top keys:",
                    list(data.keys())[:30]
                )

            print(
                "🔥 Deal response sample:",
                str(data)[:2000]
            )

        return ids

    except Exception as e:

        print(
            "DEAL ENDPOINT ERROR:",
            repr(e)
        )

        return []


# =========================================================
# FETCH PRODUCTS IN BATCHES
# =========================================================

def get_products_batch(product_ids):

    if not product_ids:
        return []

    url = (
        "https://displaycatalog.mp.microsoft.com/"
        "v7.0/products"
    )

    params = {
        "bigIds": ",".join(product_ids),
        "market": MARKET,
        "languages": LANGUAGES,
        "fieldsTemplate": "Details",
        "actionFilter": "Browse",
    }

    try:

        response = requests.get(
            url,
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            },
            timeout=40,
        )

        if response.status_code != 200:

            print(
                "🔥 DisplayCatalog error:",
                response.status_code,
                response.text[:500]
            )

            return []

        data = response.json()

        return data.get(
            "Products",
            []
        )

    except Exception as e:

        print(
            "BATCH PRODUCT ERROR:",
            repr(e)
        )

        return []


# =========================================================
# REFRESH STRONG DEALS
# =========================================================

async def refresh_strong_deals():

    global STRONG_DEALS_CACHE
    global STRONG_DEALS_UPDATED_AT

    async with STRONG_DEALS_LOCK:

        try:

            print("================================")
            print("🔥 Updating strong deals...")
            print("================================")

            product_ids = await asyncio.to_thread(
                get_deal_product_ids
            )

            if not product_ids:

                print(
                    "⚠️ No product IDs received."
                )

                # لا نمسح العروض القديمة
                # إذا فشل المصدر مؤقتاً
                return

            deals = []

            # نستخدم batches صغيرة حتى ما يصير
            # request طويل جداً
            batch_size = 20

            for i in range(
                0,
                len(product_ids),
                batch_size
            ):

                batch_ids = product_ids[
                    i:i + batch_size
                ]

                print(
                    f"🔥 Batch: "
                    f"{i + 1}-"
                    f"{i + len(batch_ids)}"
                )

                products = await asyncio.to_thread(
                    get_products_batch,
                    batch_ids
                )

                print(
                    "🔥 Products:",
                    len(products)
                )

                for product in products:

                    try:

                        product_id = (
                            product.get("ProductId")
                            or product.get("Id")
                        )

                        if not product_id:
                            continue

                        game_name = get_game_name(
                            product
                        )

                        price_info = get_price_info(
                            product
                        )

                        if not price_info:
                            continue

                        current_price = (
                            price_info[0]
                        )

                        original_price = (
                            price_info[1]
                        )

                        availability = (
                            price_info[2]
                        )

                        discount = calculate_discount(
                            current_price,
                            original_price
                        )

                        if discount < STRONG_DEAL_MIN_DISCOUNT:
                            continue

                        expiry = extract_expiry(
                            availability
                        )

                        # إذا انتهى التخفيض
                        if expiry:

                            now = datetime.now(
                                timezone.utc
                            )

                            if expiry <= now:
                                continue

                        current_iqd = calculate_price(
                            current_price
                        )

                        deals.append({
                            "product_id": product_id,
                            "name": game_name,
                            "discount": discount,
                            "current_price": current_price,
                            "original_price": original_price,
                            "iqd_price": current_iqd,
                            "expiry": expiry,
                        })

                    except Exception as e:

                        print(
                            "🔥 Deal product parse error:",
                            repr(e)
                        )

            # ترتيب حسب أعلى خصم
            deals.sort(
                key=lambda x: (
                    x["discount"],
                    -x["iqd_price"]
                ),
                reverse=True
            )

            # إزالة التكرار
            unique = []
            seen = set()

            for deal in deals:

                pid = deal["product_id"]

                if pid in seen:
                    continue

                seen.add(pid)
                unique.append(deal)

            if unique:

                STRONG_DEALS_CACHE = unique[
                    :DEALS_DISPLAY_COUNT
                ]

                STRONG_DEALS_UPDATED_AT = (
                    datetime.now(timezone.utc)
                )

                print(
                    "🔥 Strong deals:",
                    len(STRONG_DEALS_CACHE)
                )

            else:

                print(
                    "⚠️ No 50%+ deals found."
                )

                # لا نمسح الكاش القديم
                # حتى ما يختفي القسم إذا API تعطل مؤقتاً

        except Exception as e:

            print(
                "STRONG DEALS UPDATE ERROR:",
                repr(e)
            )


# =========================================================
# DEALS MESSAGE
# =========================================================

def build_deals_message():

    if not STRONG_DEALS_CACHE:

        return (
            "🔥 العروض القوية\n\n"
            "حالياً ماكو عروض قوية متاحة.\n\n"
            "🔄 يتم تحديث القسم تلقائياً كل 30 دقيقة."
        )

    text = (
        "🔥 العروض القوية\n\n"
        "الألعاب اللي عليها تخفيض 50% أو أكثر:\n\n"
    )

    for index, deal in enumerate(
        STRONG_DEALS_CACHE,
        start=1
    ):

        text += (
            f"{index}. 🎮 {deal['name']}\n"
            f"📉 خصم {deal['discount']}%\n"
            f"💰 {format_store_price(deal['iqd_price'])} 🇮🇶\n"
        )

        if deal["expiry"]:

            text += (
                f"⏳ متبقي: "
                f"{get_remaining_text(deal['expiry'])}\n"
            )

        text += "\n"

    text += (
        "🔄 يتم تحديث العروض تلقائياً كل 30 دقيقة."
    )

    return text


# =========================================================
# DEALS KEYBOARD
# =========================================================

def build_deals_keyboard():

    buttons = []

    for deal in STRONG_DEALS_CACHE:

        name = deal["name"]

        if len(name) > 35:
            name = name[:32] + "..."

        buttons.append([
            InlineKeyboardButton(
                f"🎮 {name}",
                callback_data=(
                    f"deal:{deal['product_id']}"
                )
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔄 تحديث العروض",
            callback_data="refresh_deals"
        )
    ])

    return InlineKeyboardMarkup(buttons)


# =========================================================
# SHOW STRONG DEALS
# =========================================================

async def show_strong_deals(
    query,
    force_refresh=False
):

    global STRONG_DEALS_UPDATED_AT

    should_refresh = force_refresh

    if STRONG_DEALS_UPDATED_AT is None:
        should_refresh = True

    else:

        age = (
            datetime.now(timezone.utc)
            - STRONG_DEALS_UPDATED_AT
        ).total_seconds()

        if age >= DEALS_UPDATE_SECONDS:
            should_refresh = True

    if should_refresh:

        await refresh_strong_deals()

    await query.edit_message_text(
        build_deals_message(),
        reply_markup=build_deals_keyboard()
    )


# =========================================================
# DEAL DETAILS
# =========================================================

async def show_deal_details(
    query,
    product_id
):

    deal = None

    for item in STRONG_DEALS_CACHE:

        if item["product_id"] == product_id:
            deal = item
            break

    if not deal:

        await query.answer(
            "العرض انتهى أو تم تحديث القائمة.",
            show_alert=True
        )

        return

    text = (
        f"🎮 {deal['name']}\n\n"
        f"🔥 تخفيض قوي!\n"
        f"📉 نسبة الخصم: {deal['discount']}%\n\n"
        f"💰 سعر اللعبة: "
        f"{format_store_price(deal['iqd_price'])} 🇮🇶\n"
    )

    if deal["expiry"]:

        text += (
            f"⏳ ينتهي التخفيض: "
            f"{deal['expiry'].strftime('%Y-%m-%d الساعة %H:%M')}\n"
            f"📅 متبقي: "
            f"{get_remaining_text(deal['expiry'])}\n"
        )

    text += "\n🔥 العرض متوفر حالياً."

    keyboard = [
        [
            InlineKeyboardButton(
                "🛒 اطلب الآن",
                callback_data=f"deal_order:{product_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔔 نبهني إذا نزل السعر",
                callback_data=f"deal_alert:{product_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 رجوع للعروض",
                callback_data="strong_deals"
            )
        ]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# CALLBACKS
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    data = query.data

    # -----------------------------------------
    # Strong deals
    # -----------------------------------------

    if data == "strong_deals":

        await show_strong_deals(
            query
        )

        return

    # -----------------------------------------
    # Refresh deals
    # -----------------------------------------

    if data == "refresh_deals":

        await query.edit_message_text(
            "⏳ جاري تحديث العروض..."
        )

        await refresh_strong_deals()

        await query.edit_message_text(
            build_deals_message(),
            reply_markup=build_deals_keyboard()
        )

        return

    # -----------------------------------------
    # Deal details
    # -----------------------------------------

    if data.startswith("deal:"):

        product_id = data.split(
            ":",
            1
        )[1]

        await show_deal_details(
            query,
            product_id
        )

        return

    # -----------------------------------------
    # Deal order
    # -----------------------------------------

    if data.startswith("deal_order:"):

        product_id = data.split(
            ":",
            1
        )[1]

        deal = None

        for item in STRONG_DEALS_CACHE:

            if item["product_id"] == product_id:
                deal = item
                break

        if not deal:

            await query.answer(
                "العرض لم يعد متوفر.",
                show_alert=True
            )

            return

        user = query.from_user

        username = (
            f"@{user.username}"
            if user.username
            else "بدون يوزرنيم"
        )

        customer_name = user.full_name

        if ADMIN_CHAT_ID:

            admin_text = (
                "🛒 طلب جديد!\n\n"
                f"🎮 اللعبة: {deal['name']}\n"
                f"💰 السعر: "
                f"{format_store_price(deal['iqd_price'])} 🇮🇶\n\n"
                f"👤 الزبون: {customer_name}\n"
                f"📱 اليوزر: {username}\n"
                f"🆔 ID: {user.id}\n"
            )

            try:

                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=admin_text
                )

            except Exception as e:

                print(
                    "ADMIN ORDER ERROR:",
                    repr(e)
                )

        await query.message.reply_text(
            "✅ تم إرسال طلبك.\n\n"
            "💬 للتواصل وإكمال الطلب:\n"
            f"{ORDER_URL}"
        )

        return

    # -----------------------------------------
    # Deal alert
    # -----------------------------------------

    if data.startswith("deal_alert:"):

        product_id = data.split(
            ":",
            1
        )[1]

        deal = None

        for item in STRONG_DEALS_CACHE:

            if item["product_id"] == product_id:
                deal = item
                break

        if not deal:

            await query.answer(
                "العرض لم يعد متوفر.",
                show_alert=True
            )

            return

        user = query.from_user

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO alerts
            (
                user_id,
                chat_id,
                product_id,
                game_name,
                url,
                old_price,
                active,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            user.id,
            query.message.chat_id,
            product_id,
            deal["name"],
            "",
            deal["iqd_price"],
            datetime.now(timezone.utc).isoformat(),
        ))

        conn.commit()
        conn.close()

        await query.answer(
            "🔔 تم تفعيل التنبيه.",
            show_alert=True
        )

        return

    # -----------------------------------------
    # Normal order
    # -----------------------------------------

    if data.startswith("order:"):

        product_id = data.split(
            ":",
            1
        )[1]

        user = query.from_user

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()

        cur.execute("""
            SELECT
                game_name,
                url,
                current_price
            FROM last_requests
            WHERE user_id = ?
            AND product_id = ?
        """, (
            user.id,
            product_id,
        ))

        row = cur.fetchone()

        conn.close()

        if not row:

            await query.answer(
                "❌ ماكدرت ألقى معلومات الطلب.",
                show_alert=True
            )

            return

        game_name, url, current_price = row

        username = (
            f"@{user.username}"
            if user.username
            else "بدون يوزرنيم"
        )

        customer_name = user.full_name

        if ADMIN_CHAT_ID:

            admin_text = (
                "🛒 طلب جديد!\n\n"
                f"🎮 اللعبة: {game_name}\n"
                f"💰 السعر: "
                f"{format_store_price(current_price)} 🇮🇶\n\n"
                f"👤 الزبون: {customer_name}\n"
                f"📱 اليوزر: {username}\n"
                f"🆔 ID: {user.id}\n"
            )

            try:

                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=admin_text
                )

            except Exception as e:

                print(
                    "ADMIN ORDER ERROR:",
                    repr(e)
                )

        await query.message.reply_text(
            "✅ تم إرسال طلبك.\n\n"
            "💬 للتواصل وإكمال الطلب:\n"
            f"{ORDER_URL}"
        )

        return

    # -----------------------------------------
    # Normal alert
    # -----------------------------------------

    if data.startswith("alert:"):

        product_id = data.split(
            ":",
            1
        )[1]

        user = query.from_user

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()

        cur.execute("""
            SELECT
                game_name,
                url,
                current_price
            FROM last_requests
            WHERE user_id = ?
            AND product_id = ?
        """, (
            user.id,
            product_id,
        ))

        row = cur.fetchone()

        if not row:

            conn.close()

            await query.answer(
                "❌ ماكو معلومات محفوظة عن اللعبة.",
                show_alert=True
            )

            return

        game_name, url, current_price = row

        cur.execute("""
            INSERT INTO alerts
            (
                user_id,
                chat_id,
                product_id,
                game_name,
                url,
                old_price,
                active,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """, (
            user.id,
            query.message.chat_id,
            product_id,
            game_name,
            url,
            current_price,
            datetime.now(timezone.utc).isoformat(),
        ))

        conn.commit()
        conn.close()

        keyboard = [
            [
                InlineKeyboardButton(
                    "🛒 اطلب الآن",
                    callback_data=f"order:{product_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔕 إلغاء التنبيه",
                    callback_data=f"cancel:{product_id}"
                )
            ]
        ]

        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

        await query.answer(
            "🔔 تم تفعيل التنبيه.",
            show_alert=True
        )

        return

    # -----------------------------------------
    # Cancel alert
    # -----------------------------------------

    if data.startswith("cancel:"):

        product_id = data.split(
            ":",
            1
        )[1]

        user = query.from_user

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()

        cur.execute("""
            UPDATE alerts
            SET active = 0
            WHERE user_id = ?
            AND product_id = ?
            AND active = 1
        """, (
            user.id,
            product_id,
        ))

        conn.commit()
        conn.close()

        keyboard = [
            [
                InlineKeyboardButton(
                    "🛒 اطلب الآن",
                    callback_data=f"order:{product_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔔 نبهني إذا نزل السعر",
                    callback_data=f"alert:{product_id}"
                )
            ]
        ]

        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

        await query.answer(
            "🔕 تم إلغاء التنبيه.",
            show_alert=True
        )

        return


# =========================================================
# PRICE ALERT CHECK
# =========================================================

def get_active_alerts():

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            user_id,
            chat_id,
            product_id,
            game_name,
            url,
            old_price
        FROM alerts
        WHERE active = 1
    """)

    rows = cur.fetchall()

    conn.close()

    return rows


def deactivate_alert(alert_id):

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
        UPDATE alerts
        SET active = 0
        WHERE id = ?
    """, (
        alert_id,
    ))

    conn.commit()
    conn.close()


async def check_price_alerts(
    application
):

    alerts = await asyncio.to_thread(
        get_active_alerts
    )

    print(
        "🔔 Active alerts:",
        len(alerts)
    )

    for alert in alerts:

        (
            alert_id,
            user_id,
            chat_id,
            product_id,
            game_name,
            url,
            old_price,
        ) = alert

        try:

            product = await asyncio.to_thread(
                get_product_data,
                product_id
            )

            if not product:
                continue

            price_info = get_price_info(
                product
            )

            if not price_info:
                continue

            current_price = (
                calculate_price(
                    price_info[0]
                )
            )

            if current_price < old_price:

                text = (
                    "🔔 نزل سعر لعبة!\n\n"
                    f"🎮 {game_name}\n"
                    f"💰 السعر القديم: "
                    f"{format_store_price(old_price)} 🇮🇶\n"
                    f"🔥 السعر الجديد: "
                    f"{format_store_price(current_price)} 🇮🇶\n"
                )

                keyboard = [
                    [
                        InlineKeyboardButton(
                            "🛒 اطلب الآن",
                            callback_data=(
                                f"order:{product_id}"
                            )
                        )
                    ]
                ]

                await application.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(
                        keyboard
                    )
                )

                await asyncio.to_thread(
                    deactivate_alert,
                    alert_id
                )

        except Exception as e:

            print(
                "ALERT ERROR:",
                repr(e)
            )


# =========================================================
# BACKGROUND LOOP
# =========================================================

async def background_loop(
    application
):

    # أول تحديث بعد تشغيل البوت
    await asyncio.sleep(10)

    while True:

        try:

            await refresh_strong_deals()

        except Exception as e:

            print(
                "BACKGROUND DEAL ERROR:",
                repr(e)
            )

        try:

            await check_price_alerts(
                application
            )

        except Exception as e:

            print(
                "BACKGROUND ALERT ERROR:",
                repr(e)
            )

        await asyncio.sleep(
            DEALS_UPDATE_SECONDS
        )


# =========================================================
# POST INIT
# =========================================================

async def post_init(application):

    init_db()

    print("================================")
    print("🤖 SA STORE BOT STARTED")
    print("🔥 Strong Deals enabled")
    print("🔔 Price Alerts enabled")
    print("🛒 Orders enabled")
    print("================================")

    application.create_task(
        background_loop(application)
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN is missing from Railway Variables"
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "id",
            get_id
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callback_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_game_url
        )
    )

    print("🚀 Starting polling...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
