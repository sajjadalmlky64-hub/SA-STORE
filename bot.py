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

# تحديث قائمة الألعاب كل 6 ساعات
PRICE_GAMES_CACHE_SECONDS = 21600

# عدد الألعاب المطلوب جلبها
PRICE_GAMES_COUNT = 300

# عدد الألعاب المعروضة للمستخدم
MAX_DISPLAY_GAMES = 30


# =========================================================
# CACHE
# =========================================================

PRICE_GAMES_CACHE = []
PRICE_GAMES_UPDATED_AT = None

PRICE_GAMES_LOCK = asyncio.Lock()


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
# SA STORE PRICE
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

def extract_product_id(value):

    if not value:
        return None

    patterns = [
        r"/([0-9A-Za-z]{12})(?:[/?#]|$)",
        r"[?&]cid=([0-9A-Za-z]{12})",
        r"\b([0-9A-Za-z]{12})\b",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            value
        )

        if match:
            return match.group(1).upper()

    return None


# =========================================================
# HTTP
# =========================================================

def get_json(
    url,
    params=None,
    timeout=35
):

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
# DISPLAY CATALOG
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

        data = get_json(
            url,
            params
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

        data = get_json(
            url,
            params,
            timeout=50
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

            for item in localized:

                title = item.get(
                    "ProductTitle"
                )

                if title:
                    return title

    except:
        pass

    return "Xbox Game"


# =========================================================
# RECURSIVE NUMBER FINDER
# =========================================================

def find_numbers(
    obj,
    keys,
    result=None
):

    if result is None:
        result = []

    if isinstance(obj, dict):

        for key, value in obj.items():

            key_lower = str(
                key
            ).lower()

            if key_lower in keys:

                if isinstance(
                    value,
                    (int, float)
                ):

                    result.append(
                        float(value)
                    )

                elif isinstance(
                    value,
                    str
                ):

                    try:

                        result.append(
                            float(value)
                        )

                    except:
                        pass

            find_numbers(
                value,
                keys,
                result
            )

    elif isinstance(obj, list):

        for item in obj:

            find_numbers(
                item,
                keys,
                result
            )

    return result


# =========================================================
# PRICE
# =========================================================

def get_price_info(product):

    availabilities = product.get(
        "DisplaySkuAvailabilities",
        []
    )

    if not availabilities:
        return None

    candidates = []

    for availability in availabilities:

        current_values = find_numbers(
            availability,
            {
                "listprice",
                "saleprice",
                "currentprice",
                "displayprice",
                "price",
            }
        )

        original_values = find_numbers(
            availability,
            {
                "msrp",
                "originalprice",
                "regularprice",
            }
        )

        if not current_values:
            continue

        # نختار أصغر سعر موجب
        positive_current = [
            x for x in current_values
            if x >= 0
        ]

        if not positive_current:
            continue

        current = min(
            positive_current
        )

        original = None

        positive_original = [
            x for x in original_values
            if x > 0
        ]

        if positive_original:

            original = max(
                positive_original
            )

        candidates.append({
            "current": current,
            "original": original,
            "availability": availability,
        })

    if not candidates:
        return None

    # نفضل المرشح الذي يحتوي على تخفيض
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

    dates = []

    def walk(obj):

        if isinstance(obj, dict):

            for key, value in obj.items():

                if str(key).lower() == "enddate":

                    if isinstance(
                        value,
                        str
                    ):
                        dates.append(value)

                walk(value)

        elif isinstance(obj, list):

            for item in obj:
                walk(item)

    walk(availability)

    now = datetime.now(
        timezone.utc
    )

    future = []

    for value in dates:

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
# REMAINING
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
        (
            expiry - now
        ).total_seconds()
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

    if not parts:
        return "أقل من دقيقة"

    return " ".join(parts)


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

    conn = sqlite3.connect(
        DB_FILE
    )

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


def has_active_alert(
    user_id,
    product_id
):

    conn = sqlite3.connect(
        DB_FILE
    )

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
# NORMAL GAME
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
# EXTRACT IDS
# =========================================================

def extract_product_ids(data):

    found = set()

    possible_keys = {
        "id",
        "productid",
        "product_id",
        "bigid",
        "big_id",
        "product"
    }

    def walk(obj):

        if isinstance(obj, dict):

            for key, value in obj.items():

                key_lower = str(
                    key
                ).lower()

                if key_lower in possible_keys:

                    if isinstance(
                        value,
                        str
                    ):

                        value = value.strip()

                        # Product ID
                        if re.fullmatch(
                            r"[0-9A-Za-z]{12}",
                            value
                        ):
                            found.add(
                                value.upper()
                            )

                        # إذا كان URL
                        else:

                            extracted = (
                                extract_product_id(
                                    value
                                )
                            )

                            if extracted:
                                found.add(
                                    extracted
                                )

                walk(value)

        elif isinstance(obj, list):

            for item in obj:
                walk(item)

        elif isinstance(obj, str):

            # احتياطاً:
            # نبحث عن Product IDs داخل النص
            matches = re.findall(
                r"\b[0-9A-Za-z]{12}\b",
                obj
            )

            for match in matches:
                found.add(
                    match.upper()
                )

    walk(data)

    return list(found)


# =========================================================
# RECOMMENDATIONS LIST
# =========================================================

def request_recommendations(
    list_name
):

    base_url = (
        "https://reco-public.rec.mp.microsoft.com/"
        "channels/Reco/V8.0/Lists/api/list/"
    )

    url = base_url + list_name

    # مهم:
    # Microsoft/Xbox API تستخدم itemTypes
    params_variants = [

        {
            "market": "tr",
            "language": "tr-tr",
            "itemTypes": "Game",
            "deviceFamily": "Windows.Xbox",
            "count": str(
                PRICE_GAMES_COUNT
            ),
            "skipItems": "0",
        },

        # fallback
        {
            "market": "TR",
            "language": "tr-TR",
            "itemTypes": "Game",
            "deviceFamily": "Windows.Xbox",
            "count": str(
                PRICE_GAMES_COUNT
            ),
            "skipItems": "0",
        },

        # fallback قديم
        {
            "market": "tr",
            "language": "tr-tr",
            "itemType": "Game",
            "deviceFamily": "Windows.Xbox",
            "count": str(
                PRICE_GAMES_COUNT
            ),
            "skipItems": "0",
        },
    ]

    for params in params_variants:

        try:

            response = requests.get(
                url,
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json",
                },
                timeout=35,
            )

            print(
                "🎯 LIST:",
                list_name,
                "STATUS:",
                response.status_code
            )

            if response.status_code != 200:
                continue

            data = response.json()

            ids = extract_product_ids(
                data
            )

            print(
                "🎯",
                list_name,
                "IDS:",
                len(ids)
            )

            if ids:
                return ids

        except Exception as e:

            print(
                "LIST ERROR:",
                list_name,
                repr(e)
            )

    return []


# =========================================================
# FALLBACK GAMES API
# =========================================================

def request_games_api(
    list_name
):

    url = (
        "https://reco-public.rec.mp.microsoft.com/"
        "channels/Reco/V8.0/Lists/api/games/"
        + list_name
    )

    params = {
        "market": "tr",
        "language": "tr-tr",
        "itemTypes": "Game",
        "deviceFamily": "Windows.Xbox",
        "count": str(
            PRICE_GAMES_COUNT
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
            timeout=40,
        )

        print(
            "🎯 GAMES API:",
            list_name,
            response.status_code
        )

        if response.status_code != 200:
            return []

        data = response.json()

        ids = extract_product_ids(
            data
        )

        print(
            "🎯 GAMES API IDS:",
            len(ids)
        )

        return ids

    except Exception as e:

        print(
            "GAMES API ERROR:",
            repr(e)
        )

        return []


# =========================================================
# BUILD GAME CACHE
# =========================================================

async def refresh_price_games():

    global PRICE_GAMES_CACHE
    global PRICE_GAMES_UPDATED_AT

    async with PRICE_GAMES_LOCK:

        print(
            "================================"
        )

        print(
            "🎯 Updating price games..."
        )

        print(
            "================================"
        )

        all_ids = []

        # القوائم الأساسية
        lists = [
            "Computed/TopPaid",
            "Computed/MostPlayed",
            "Computed/BestRated",
            "Computed/New",
        ]

        for list_name in lists:

            ids = await asyncio.to_thread(
                request_recommendations,
                list_name
            )

            # إذا فشلت list API
            # نجرب games API
            if not ids:

                print(
                    "⚠️ List API empty:",
                    list_name
                )

                ids = await asyncio.to_thread(
                    request_games_api,
                    list_name
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
            "🎯 TOTAL UNIQUE IDS:",
            len(unique_ids)
        )

        if not unique_ids:

            print(
                "❌ Microsoft returned 0 games."
            )

            return

        games = []

        # =====================================================
        # FETCH DISPLAY CATALOG
        # =====================================================

        batch_size = 20

        for start in range(
            0,
            len(unique_ids),
            batch_size
        ):

            batch = unique_ids[
                start:start + batch_size
            ]

            print(
                "🎯 Fetching batch:",
                start,
                "-",
                start + len(batch)
            )

            products = await asyncio.to_thread(
                get_products_batch,
                batch
            )

            print(
                "🎯 Products returned:",
                len(products)
            )

            for product in products:

                try:

                    product_id = (
                        product.get(
                            "ProductId"
                        )
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

                    games.append({
                        "product_id": product_id,
                        "name": game_name,
                        "iqd_price": iqd_price,
                        "discount": discount,
                        "expiry": expiry,
                    })

                except Exception as e:

                    print(
                        "GAME PARSE ERROR:",
                        repr(e)
                    )

        # إزالة التكرار
        final_games = []

        seen = set()

        for game in games:

            product_id = game[
                "product_id"
            ]

            if product_id in seen:
                continue

            seen.add(
                product_id
            )

            final_games.append(
                game
            )

        if final_games:

            PRICE_GAMES_CACHE = (
                final_games
            )

            PRICE_GAMES_UPDATED_AT = (
                datetime.now(
                    timezone.utc
                )
            )

            print(
                "================================"
            )

            print(
                "🎯 FINAL GAMES:",
                len(PRICE_GAMES_CACHE)
            )

            print(
                "================================"
            )

        else:

            print(
                "❌ No games with prices."
            )


# =========================================================
# PRICE RANGES
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
# PRICE MENU
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
# SHOW GAMES BY PRICE
# =========================================================

async def show_games_by_range(
    query,
    range_id
):

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

    # =====================================================
    # CACHE CHECK
    # =====================================================

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
            "⏳ جاري جلب الألعاب والأسعار...\n\n"
            "أول مرة قد تستغرق عدة ثواني."
        )

        await refresh_price_games()

    # =====================================================
    # FILTER
    # =====================================================

    matching = []

    for game in PRICE_GAMES_CACHE:

        price = game[
            "iqd_price"
        ]

        if (
            price >= minimum
            and price <= maximum
        ):

            matching.append(
                game
            )

    # الأرخص أولاً
    matching.sort(
        key=lambda x: (
            x["iqd_price"],
            x["name"].lower()
        )
    )

    matching = matching[
        :MAX_DISPLAY_GAMES
    ]

    # =====================================================
    # EMPTY
    # =====================================================

    if not matching:

        keyboard = [[
            InlineKeyboardButton(
                "🔙 رجوع",
                callback_data="price_games"
            )
        ]]

        await query.edit_message_text(
            f"🎯 {title}\n\n"
            "حالياً ماكدرت ألقى ألعاب ضمن هذا السعر.\n\n"
            "🔄 حاول مرة ثانية بعد قليل.",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

        return

    # =====================================================
    # MESSAGE
    # =====================================================

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

    # =====================================================
    # BUTTONS
    # =====================================================

    keyboard = []

    for game in matching:

        name = game[
            "name"
        ]

        if len(name) > 35:

            name = (
                name[:32]
                + "..."
            )

        keyboard.append([
            InlineKeyboardButton(
                f"🎮 {name}",
                callback_data=(
                    f"pricegame:"
                    f"{game['product_id']}"
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
# SELECTED GAME
# =========================================================

async def show_price_game(
    query,
    product_id
):

    await query.answer()

    product = await asyncio.to_thread(
        get_product_data,
        product_id
    )

    if not product:

        await query.message.reply_text(
            "❌ اللعبة لم تعد متوفرة."
        )

        return

    game_name = get_game_name(
        product
    )

    price_info = get_price_info(
        product
    )

    if not price_info:

        await query.message.reply_text(
            "❌ ماكدرت أجيب سعر اللعبة."
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

    user_id = query.from_user.id

    xbox_url = (
        "https://www.xbox.com/"
        "tr-TR/games/store/"
        f"{product_id}"
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
# CALLBACK
# =========================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    data = query.data

    # =====================================================
    # PRICE GAMES
    # =====================================================

    if data == "price_games":

        await query.answer()

        await show_price_menu(
            query
        )

        return

    # =====================================================
    # PRICE RANGE
    # =====================================================

    if data.startswith(
        "range:"
    ):

        await query.answer()

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

    if data.startswith(
        "pricegame:"
    ):

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
    # ORDER
    # =====================================================

    if data.startswith(
        "order:"
    ):

        await query.answer()

        product_id = data.split(
            ":",
            1
        )[1]

        user = query.from_user

        conn = sqlite3.connect(
            DB_FILE
        )

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

            await query.message.reply_text(
                "❌ ماكدرت ألقى معلومات الطلب."
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

    if data.startswith(
        "alert:"
    ):

        await query.answer(
            "🔔 تم تفعيل التنبيه.",
            show_alert=True
        )

        product_id = data.split(
            ":",
            1
        )[1]

        user = query.from_user

        conn = sqlite3.connect(
            DB_FILE
        )

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

        return

    # =====================================================
    # CANCEL ALERT
    # =====================================================

    if data.startswith(
        "cancel:"
    ):

        await query.answer(
            "🔕 تم إلغاء التنبيه.",
            show_alert=True
        )

        product_id = data.split(
            ":",
            1
        )[1]

        user = query.from_user

        conn = sqlite3.connect(
            DB_FILE
        )

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

        return


# =========================================================
# ALERT CHECK
# =========================================================

def get_active_alerts():

    conn = sqlite3.connect(
        DB_FILE
    )

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

    conn = sqlite3.connect(
        DB_FILE
    )

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
                    f"{format_store_price(current_price)} 🇮🇶"
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

    await asyncio.sleep(
        60
    )

    while True:

        try:

            await check_price_alerts(
                application
            )

        except Exception as e:

            print(
                "BACKGROUND ERROR:",
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
        "🔥 Strong Deals: DISABLED"
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
