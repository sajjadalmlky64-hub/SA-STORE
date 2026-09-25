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

DB_FILE = "price_alerts.db"


# =========================================================
# PRICE BROWSE SETTINGS
# =========================================================

# تحديث قاعدة الألعاب كل 6 ساعات
PRICE_GAMES_CACHE_SECONDS = 21600

PRICE_GAMES_CACHE = []
PRICE_GAMES_UPDATED_AT = None

PRICE_GAMES_LOCK = asyncio.Lock()


# قوائم Xbox التي نستخدمها للحصول على الألعاب
PRICE_LISTS = [
    "Computed/TopPaid",
    "Computed/MostPlayed",
    "Computed/BestRated",
    "Computed/New",
]

PRICE_LIST_COUNT = 150


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
# HTTP JSON
# =========================================================

def http_get_json(
    url,
    params=None,
    timeout=30
):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
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
# GET PRODUCT
# =========================================================

def get_product_data(product_id):

    url = (
        "https://displaycatalog.mp.microsoft.com/"
        "v7.0/products"
    )

    params = {
        "bigIds": product_id,
        "market": MARKET,
        "languages": LANGUAGES,
        "fieldsTemplate": "Details",
        "actionFilter": "Browse",
    }

    try:

        data = http_get_json(
            url,
            params=params
        )

        products = data.get(
            "Products",
            []
        )

        if not products:
            return None

        return products[0]

    except Exception as e:

        print(
            "PRODUCT ERROR:",
            product_id,
            repr(e)
        )

        return None


# =========================================================
# GET PRODUCTS BATCH
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

        data = http_get_json(
            url,
            params=params,
            timeout=45
        )

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
# GAME NAME
# =========================================================

def get_game_name(product):

    try:

        localized = product.get(
            "LocalizedProperties",
            []
        )

        if localized:

            first = localized[0]

            if first.get("ProductTitle"):
                return first["ProductTitle"]

    except:
        pass

    return "Xbox Game"


# =========================================================
# PRICE EXTRACTION
# =========================================================

def get_price_info(product):

    availabilities = product.get(
        "DisplaySkuAvailabilities",
        []
    )

    candidates = []

    for availability in availabilities:

        sku = availability.get(
            "Sku",
            {}
        )

        # -----------------------------------------
        # الطريقة الأساسية
        # -----------------------------------------

        price = None
        original = None

        try:

            price_obj = (
                sku.get("LocalizedProperties", [])
            )

        except:
            price_obj = []

        # -----------------------------------------
        # بحث recursive عن الأسعار
        # -----------------------------------------

        def walk(obj):

            nonlocal price
            nonlocal original

            if isinstance(obj, dict):

                for key, value in obj.items():

                    key_lower = str(key).lower()

                    if key_lower in {
                        "listprice",
                        "saleprice",
                        "currentprice",
                    }:

                        try:

                            number = float(value)

                            if number >= 0:

                                if price is None:
                                    price = number

                        except:
                            pass

                    if key_lower in {
                        "msrp",
                        "originalprice",
                        "regularprice",
                    }:

                        try:

                            number = float(value)

                            if number > 0:
                                original = number

                        except:
                            pass

                    walk(value)

            elif isinstance(obj, list):

                for item in obj:
                    walk(item)

        walk(availability)

        if price is not None:

            candidates.append({
                "current": price,
                "original": original,
                "availability": availability,
            })

    if not candidates:
        return None

    # نفضل السعر الذي لديه MSRP أعلى
    for item in candidates:

        current = item["current"]
        original = item["original"]

        if (
            original is not None
            and original > current
        ):
            return (
                current,
                original,
                item["availability"]
            )

    item = candidates[0]

    return (
        item["current"],
        item["original"],
        item["availability"]
    )


# =========================================================
# EXPIRY
# =========================================================

def extract_expiry(availability):

    if not availability:
        return None

    found = []

    def walk(obj):

        if isinstance(obj, dict):

            for key, value in obj.items():

                if str(key).lower() == "enddate":

                    if isinstance(value, str):
                        found.append(value)

                walk(value)

        elif isinstance(obj, list):

            for item in obj:
                walk(item)

    walk(availability)

    now = datetime.now(
        timezone.utc
    )

    future = []

    for value in found:

        try:

            dt = datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00"
                )
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            if dt > now:
                future.append(dt)

        except:
            pass

    if not future:
        return None

    return min(future)


# =========================================================
# REMAINING TIME
# =========================================================

def get_remaining_text(expiry):

    if not expiry:
        return "غير محدد"

    now = datetime.now(
        timezone.utc
    )

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
        parts.append(
            f"{days} يوم"
        )

    if hours:
        parts.append(
            f"{hours} ساعة"
        )

    if minutes:
        parts.append(
            f"{minutes} دقيقة"
        )

    return (
        " ".join(parts)
        if parts
        else "أقل من دقيقة"
    )


# =========================================================
# DISCOUNT
# =========================================================

def calculate_discount(
    current,
    original
):

    if not original:
        return 0

    if original <= current:
        return 0

    return int(
        round(
            (
                (original - current)
                / original
            ) * 100
        )
    )


# =========================================================
# LAST REQUEST
# =========================================================

def save_last_request(
    user_id,
    product_id,
    game_name,
    url,
    current_price
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
        datetime.now(
            timezone.utc
        ).isoformat(),
    ))

    conn.commit()
    conn.close()


# =========================================================
# ACTIVE ALERT
# =========================================================

def has_active_alert(
    user_id,
    product_id
):

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
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = [
        [
            InlineKeyboardButton(
                "🎯 ألعاب حسب السعر",
                callback_data="price_games"
            )
        ]
    ]

    await update.message.reply_text(
        "يرجى إرسال رابط اللعبة من Xbox Store 👇",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# =========================================================
# ID
# =========================================================

async def get_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        f"🆔 Telegram ID:\n"
        f"`{update.effective_user.id}`",
        parse_mode="Markdown"
    )


# =========================================================
# NORMAL GAME URL
# =========================================================

async def handle_game_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    product_id = extract_product_id(
        text
    )

    if not product_id:

        await update.message.reply_text(
            "يرجى إرسال رابط لعبة من Xbox Store 🎮"
        )

        return

    await update.message.reply_text(
        "⏳ جاري جلب معلومات اللعبة..."
    )

    product = await asyncio.to_thread(
        get_product_data,
        product_id
    )

    if not product:

        await update.message.reply_text(
            "❌ ماكدرت أجيب معلومات اللعبة."
        )

        return

    game_name = get_game_name(
        product
    )

    price_info = get_price_info(
        product
    )

    if not price_info:

        await update.message.reply_text(
            f"🎮 {game_name}\n\n"
            "❌ ماكدرت أتعرف على سعر اللعبة."
        )

        return

    current_price = price_info[0]
    original_price = price_info[1]
    availability = price_info[2]

    current_iqd = calculate_price(
        current_price
    )

    discount = calculate_discount(
        current_price,
        original_price
    )

    expiry = extract_expiry(
        availability
    )

    save_last_request(
        update.effective_user.id,
        product_id,
        game_name,
        text,
        current_iqd
    )

    message = (
        f"🎮 {game_name}\n\n"
    )

    if discount > 0:

        message += (
            "🔥 اللعبة عليها تخفيض!\n"
            f"📉 نسبة الخصم: {discount}%\n"
        )

        if expiry:

            message += (
                f"⏳ ينتهي التخفيض: "
                f"{expiry.strftime('%Y-%m-%d الساعة %H:%M')}\n"
                f"📅 متبقي: "
                f"{get_remaining_text(expiry)}\n"
            )

    message += (
        f"\n💰 سعر اللعبة: "
        f"{format_store_price(current_iqd)} 🇮🇶"
    )

    buttons = [
        [
            InlineKeyboardButton(
                "🛒 اطلب الآن",
                callback_data=(
                    f"order:{product_id}"
                )
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
                callback_data=(
                    f"cancel:{product_id}"
                )
            )
        ])

    else:

        buttons.append([
            InlineKeyboardButton(
                "🔔 نبهني إذا نزل السعر",
                callback_data=(
                    f"alert:{product_id}"
                )
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🎯 ألعاب حسب السعر",
            callback_data="price_games"
        )
    ])

    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )


# =========================================================
# GET PRODUCT IDS FROM XBOX LIST
# =========================================================

def extract_ids_from_list(data):

    found = set()

    valid_keys = {
        "productid",
        "product_id",
        "bigid",
        "big_id",
        "id",
    }

    def walk(obj):

        if isinstance(obj, dict):

            for key, value in obj.items():

                key_lower = str(
                    key
                ).lower()

                if key_lower in valid_keys:

                    if isinstance(value, str):

                        value = value.strip()

                        if re.fullmatch(
                            r"[0-9A-Za-z]{12}",
                            value
                        ):
                            found.add(
                                value.upper()
                            )

                walk(value)

        elif isinstance(obj, list):

            for item in obj:
                walk(item)

    walk(data)

    return list(found)


# =========================================================
# GET IDS FROM XBOX LIST
# =========================================================

def get_ids_from_xbox_list(
    list_name
):

    url = (
        "https://reco-public.rec.mp.microsoft.com/"
        "channels/Reco/V8.0/Lists/api/list/"
        + list_name
    )

    params = {
        "market": "tr",
        "language": "tr-tr",
        "itemType": "Game",
        "deviceFamily": "Windows.Xbox",
        "count": str(
            PRICE_LIST_COUNT
        ),
        "skipItems": "0",
    }

    try:

        response = requests.get(
            url,
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            },
            timeout=30,
        )

        print(
            "PRICE LIST:",
            list_name,
            response.status_code
        )

        if response.status_code != 200:
            return []

        data = response.json()

        return extract_ids_from_list(
            data
        )

    except Exception as e:

        print(
            "PRICE LIST ERROR:",
            list_name,
            repr(e)
        )

        return []


# =========================================================
# BUILD PRICE GAMES CACHE
# =========================================================

async def refresh_price_games():

    global PRICE_GAMES_CACHE
    global PRICE_GAMES_UPDATED_AT

    async with PRICE_GAMES_LOCK:

        print(
            "🎯 Updating price games..."
        )

        all_ids = []

        for list_name in PRICE_LISTS:

            ids = await asyncio.to_thread(
                get_ids_from_xbox_list,
                list_name
            )

            print(
                "🎯",
                list_name,
                "=>",
                len(ids)
            )

            all_ids.extend(ids)

        # إزالة التكرار
        unique_ids = []

        seen = set()

        for product_id in all_ids:

            if product_id in seen:
                continue

            seen.add(product_id)

            unique_ids.append(
                product_id
            )

        print(
            "🎯 Total unique IDs:",
            len(unique_ids)
        )

        games = []

        # دفعات
        batch_size = 20

        for i in range(
            0,
            len(unique_ids),
            batch_size
        ):

            batch_ids = unique_ids[
                i:i + batch_size
            ]

            products = await asyncio.to_thread(
                get_products_batch,
                batch_ids
            )

            print(
                "🎯 Batch:",
                i,
                "Products:",
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

                    name = get_game_name(
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

                    iqd_price = calculate_price(
                        current_price
                    )

                    discount = calculate_discount(
                        current_price,
                        original_price
                    )

                    expiry = extract_expiry(
                        availability
                    )

                    # إذا التخفيض منتهي، نتجاهله
                    if expiry:

                        now = datetime.now(
                            timezone.utc
                        )

                        if expiry <= now:
                            discount = 0

                    games.append({
                        "product_id": product_id,
                        "name": name,
                        "iqd_price": iqd_price,
                        "discount": discount,
                        "expiry": expiry,
                    })

                except Exception as e:

                    print(
                        "PRICE GAME PARSE ERROR:",
                        repr(e)
                    )

        # إزالة الألعاب المكررة
        unique_games = []
        seen_ids = set()

        for game in games:

            pid = game[
                "product_id"
            ]

            if pid in seen_ids:
                continue

            seen_ids.add(pid)

            unique_games.append(
                game
            )

        if unique_games:

            PRICE_GAMES_CACHE = (
                unique_games
            )

            PRICE_GAMES_UPDATED_AT = (
                datetime.now(
                    timezone.utc
                )
            )

            print(
                "🎯 Cached games:",
                len(PRICE_GAMES_CACHE)
            )

        else:

            print(
                "⚠️ No games received."
            )


# =========================================================
# PRICE RANGE
# =========================================================

def get_price_range(
    range_id
):

    ranges = {

        "under5": (
            0,
            5000,
            "أقل من 5,000 د.ع"
        ),

        "5to10": (
            5000,
            10000,
            "5,000 - 10,000 د.ع"
        ),

        "10to15": (
            10000,
            15000,
            "10,000 - 15,000 د.ع"
        ),

        "15to20": (
            15000,
            20000,
            "15,000 - 20,000 د.ع"
        ),

        "20to30": (
            20000,
            30000,
            "20,000 - 30,000 د.ع"
        ),

        "over30": (
            30000,
            999999999,
            "أكثر من 30,000 د.ع"
        ),
    }

    return ranges.get(
        range_id
    )


# =========================================================
# PRICE GAMES MENU
# =========================================================

async def show_price_menu(
    query
):

    keyboard = [

        [
            InlineKeyboardButton(
                "💰 أقل من 5,000",
                callback_data="range:under5"
            )
        ],

        [
            InlineKeyboardButton(
                "💰 5,000 - 10,000",
                callback_data="range:5to10"
            )
        ],

        [
            InlineKeyboardButton(
                "💰 10,000 - 15,000",
                callback_data="range:10to15"
            )
        ],

        [
            InlineKeyboardButton(
                "💰 15,000 - 20,000",
                callback_data="range:15to20"
            )
        ],

        [
            InlineKeyboardButton(
                "💰 20,000 - 30,000",
                callback_data="range:20to30"
            )
        ],

        [
            InlineKeyboardButton(
                "💰 أكثر من 30,000",
                callback_data="range:over30"
            )
        ],
    ]

    await query.edit_message_text(
        "🎯 ألعاب حسب السعر\n\n"
        "اختار ميزانيتك:",
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# =========================================================
# SHOW GAMES BY RANGE
# =========================================================

async def show_games_by_range(
    query,
    range_id
):

    global PRICE_GAMES_UPDATED_AT

    price_range = get_price_range(
        range_id
    )

    if not price_range:

        await query.answer(
            "❌ اختيار غير صحيح.",
            show_alert=True
        )

        return

    minimum = price_range[0]
    maximum = price_range[1]
    title = price_range[2]

    # تحديث الكاش إذا قديم
    needs_update = False

    if not PRICE_GAMES_CACHE:
        needs_update = True

    elif PRICE_GAMES_UPDATED_AT:

        age = (
            datetime.now(
                timezone.utc
            )
            - PRICE_GAMES_UPDATED_AT
        ).total_seconds()

        if age >= PRICE_GAMES_CACHE_SECONDS:
            needs_update = True

    if needs_update:

        await query.edit_message_text(
            "⏳ جاري جلب الألعاب والأسعار...\n"
            "قد يستغرق الأمر قليلاً أول مرة."
        )

        await refresh_price_games()

    matching = []

    for game in PRICE_GAMES_CACHE:

        price = game[
            "iqd_price"
        ]

        if (
            price >= minimum
            and price <= maximum
        ):
            matching.append(game)

    # ترتيب من الأرخص للأغلى
    matching.sort(
        key=lambda x: (
            x["iqd_price"],
            x["name"].lower()
        )
    )

    # نعرض أول 30
    matching = matching[:30]

    if not matching:

        keyboard = [[
            InlineKeyboardButton(
                "🔙 رجوع",
                callback_data="price_games"
            )
        ]]

        await query.edit_message_text(
            f"🎯 {title}\n\n"
            "حالياً ماكدرت ألقى ألعاب ضمن هذا السعر.",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

        return

    text = (
        f"🎯 ألعاب {title}\n\n"
    )

    for index, game in enumerate(
        matching,
        start=1
    ):

        text += (
            f"{index}. 🎮 {game['name']}\n"
            f"💰 {format_store_price(game['iqd_price'])} 🇮🇶\n"
        )

        if game["discount"] > 0:

            text += (
                f"🔥 خصم {game['discount']}%\n"
            )

        text += "\n"

    text += (
        f"📋 عدد النتائج: {len(matching)}"
    )

    keyboard = []

    # زر لكل لعبة
    for game in matching:

        name = game["name"]

        if len(name) > 35:
            name = name[:32] + "..."

        keyboard.append([
            InlineKeyboardButton(
                f"🎮 {name}",
                callback_data=(
                    f"pricegame:{game['product_id']}"
                )
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 تغيير الميزانية",
            callback_data="price_games"
        )
    ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )


# =========================================================
# SHOW SELECTED PRICE GAME
# =========================================================

async def show_price_game(
    query,
    product_id
):

    product = await asyncio.to_thread(
        get_product_data,
        product_id
    )

    if not product:

        await query.answer(
            "❌ اللعبة لم تعد متوفرة.",
            show_alert=True
        )

        return

    game_name = get_game_name(
        product
    )

    price_info = get_price_info(
        product
    )

    if not price_info:

        await query.answer(
            "❌ ماكدرت أجيب السعر.",
            show_alert=True
        )

        return

    current_price = price_info[0]
    original_price = price_info[1]
    availability = price_info[2]

    current_iqd = calculate_price(
        current_price
    )

    discount = calculate_discount(
        current_price,
        original_price
    )

    expiry = extract_expiry(
        availability
    )

    text = (
        f"🎮 {game_name}\n\n"
    )

    if discount > 0:

        text += (
            "🔥 اللعبة عليها تخفيض!\n"
            f"📉 نسبة الخصم: {discount}%\n"
        )

        if expiry:

            text += (
                f"⏳ ينتهي التخفيض: "
                f"{expiry.strftime('%Y-%m-%d الساعة %H:%M')}\n"
                f"📅 متبقي: "
                f"{get_remaining_text(expiry)}\n"
            )

    text += (
        f"\n💰 سعر اللعبة: "
        f"{format_store_price(current_iqd)} 🇮🇶"
    )

    # نخزنها حتى يشتغل الطلب والتنبيه
    user_id = query.from_user.id

    xbox_url = (
        f"https://www.xbox.com/tr-TR/"
        f"games/store/{product_id}"
    )

    save_last_request(
        user_id,
        product_id,
        game_name,
        xbox_url,
        current_iqd
    )

    buttons = [
        [
            InlineKeyboardButton(
                "🛒 اطلب الآن",
                callback_data=(
                    f"order:{product_id}"
                )
            )
        ]
    ]

    if has_active_alert(
        user_id,
        product_id
    ):

        buttons.append([
            InlineKeyboardButton(
                "🔕 إلغاء التنبيه",
                callback_data=(
                    f"cancel:{product_id}"
                )
            )
        ])

    else:

        buttons.append([
            InlineKeyboardButton(
                "🔔 نبهني إذا نزل السعر",
                callback_data=(
                    f"alert:{product_id}"
                )
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 رجوع للأسعار",
            callback_data="price_games"
        )
    ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    data = query.data

    # =====================================================
    # PRICE GAMES
    # =====================================================

    if data == "price_games":

        await show_price_menu(
            query
        )

        return

    # =====================================================
    # PRICE RANGE
    # =====================================================

    if data.startswith("range:"):

        range_id = data.split(
            ":",
            1
        )[1]

        await show_games_by_range(
            query,
            range_id
        )

        return

    # =====================================================
    # PRICE GAME
    # =====================================================

    if data.startswith("pricegame:"):

        product_id = data.split(
            ":",
            1
        )[1]

        await show_price_game(
            query,
            product_id
        )

        return

    # =====================================================
    # NORMAL ORDER
    # =====================================================

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

        if ADMIN_CHAT_ID:

            admin_text = (
                "🛒 طلب جديد!\n\n"
                f"🎮 اللعبة: {game_name}\n"
                f"💰 السعر: "
                f"{format_store_price(current_price)} 🇮🇶\n\n"
                f"👤 الزبون: {user.full_name}\n"
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

    # =====================================================
    # ALERT
    # =====================================================

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
                "❌ ماكو معلومات محفوظة.",
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
            datetime.now(
                timezone.utc
            ).isoformat(),
        ))

        conn.commit()
        conn.close()

        keyboard = [
            [
                InlineKeyboardButton(
                    "🛒 اطلب الآن",
                    callback_data=(
                        f"order:{product_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🔕 إلغاء التنبيه",
                    callback_data=(
                        f"cancel:{product_id}"
                    )
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

    # =====================================================
    # CANCEL ALERT
    # =====================================================

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
                    callback_data=(
                        f"order:{product_id}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🔔 نبهني إذا نزل السعر",
                    callback_data=(
                        f"alert:{product_id}"
                    )
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
# ALERT CHECK
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


def deactivate_alert(
    alert_id
):

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

            current_price = calculate_price(
                price_info[0]
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

                keyboard = [[
                    InlineKeyboardButton(
                        "🛒 اطلب الآن",
                        callback_data=(
                            f"order:{product_id}"
                        )
                    )
                ]]

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
# BACKGROUND
# =========================================================

async def background_loop(
    application
):

    await asyncio.sleep(60)

    while True:

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
            3600
        )


# =========================================================
# POST INIT
# =========================================================

async def post_init(
    application
):

    init_db()

    print(
        "================================"
    )

    print(
        "🤖 SA STORE BOT STARTED"
    )

    print(
        "🎯 Price Games enabled"
    )

    print(
        "🔔 Price Alerts enabled"
    )

    print(
        "🛒 Orders enabled"
    )

    print(
        "🔥 Strong Deals: NOT INCLUDED"
    )

    print(
        "================================"
    )

    application.create_task(
        background_loop(
            application
        )
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

    print(
        "🚀 Starting polling..."
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
