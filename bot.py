import os
import re
import math
import asyncio
import difflib
import sqlite3
import requests

from datetime import datetime, timezone
from collections import Counter

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)


# =========================================================
# الإعدادات
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = (os.getenv("ADMIN_CHAT_ID") or "").strip()
# Telegram private-chat IDs are numeric. Public channel/group usernames may begin with @.
if ADMIN_CHAT_ID.lstrip("-").isdigit():
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)

ORDER_URL = "https://t.me/Sijadsa"
DB_FILE = "price_alerts.db"

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN غير موجود في Variables")


# =========================================================
# Headers
# =========================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# كاش دائم داخل تشغيل البوت لنتائج البحث
SEARCH_RESULT_CACHE = {}

# آخر قائمة نتائج بحث لكل مستخدم، حتى نقدر نرجع لها بعد اختيار إصدار.
SEARCH_SELECTIONS = {}


# =========================================================
# قاعدة البيانات
# =========================================================

def init_database():

    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            game_name TEXT NOT NULL,
            url TEXT NOT NULL,
            old_price INTEGER NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS last_requests (
            user_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            game_name TEXT NOT NULL,
            url TEXT NOT NULL,
            current_price INTEGER NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, product_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS favorites (
            user_id INTEGER NOT NULL,
            product_id TEXT NOT NULL,
            game_name TEXT NOT NULL,
            url TEXT NOT NULL,
            current_price INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, product_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            customer_name TEXT NOT NULL,
            game_name TEXT NOT NULL,
            product_id TEXT NOT NULL,
            price INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()


# =========================================================
# المفضلة
# =========================================================

def favorite_exists(user_id, product_id):

    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()

    cursor.execute(
        "SELECT 1 FROM favorites WHERE user_id = ? AND product_id = ? LIMIT 1",
        (user_id, product_id)
    )

    exists = cursor.fetchone() is not None
    connection.close()

    return exists


def add_favorite(user_id, product_id, game_name, url, current_price):

    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO favorites
        (user_id, product_id, game_name, url, current_price)
        VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, product_id, game_name, url, current_price)
    )

    connection.commit()
    connection.close()


def remove_favorite(user_id, product_id):

    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()

    cursor.execute(
        "DELETE FROM favorites WHERE user_id = ? AND product_id = ?",
        (user_id, product_id)
    )

    changed = cursor.rowcount
    connection.commit()
    connection.close()

    return changed > 0


def get_favorites(user_id):

    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT product_id, game_name, url, current_price
        FROM favorites
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (user_id,)
    )

    rows = cursor.fetchall()
    connection.close()

    return rows


# =========================================================
# حساب السعر العراقي
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


# =========================================================
# استخراج Product ID من الرابط
# =========================================================

def get_product_id(url):

    matches = re.findall(
        r"(?<![A-Za-z0-9])([A-Za-z0-9]{12})(?![A-Za-z0-9])",
        url
    )

    if matches:
        return matches[-1].upper()

    return None


# =========================================================
# تحويل السعر
# =========================================================

def to_float(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    value = str(value).strip()

    value = (
        value
        .replace("₺", "")
        .replace("TRY", "")
        .replace("TL", "")
        .replace("\xa0", "")
        .replace(" ", "")
    )

    if "," in value and "." in value:

        if value.rfind(",") > value.rfind("."):

            value = value.replace(".", "")
            value = value.replace(",", ".")

        else:

            value = value.replace(",", "")

    elif "," in value:

        value = value.replace(",", ".")

    try:
        return float(value)

    except Exception:
        return None


# =========================================================
# جلب بيانات المنتج
# =========================================================

def get_product_data(product_id):

    url = (
        "https://displaycatalog.mp.microsoft.com/"
        "v7.0/products"
    )

    params = {
        "bigIds": product_id,
        "market": "TR",
        "languages": "tr-TR,en-US",
        "fieldsTemplate": "Details",
        "actionFilter": "Browse"
    }

    response = SESSION.get(
        url,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    products = data.get("Products", [])

    if products:
        return products[0]

    product = data.get("Product")

    if product:
        return product

    raise Exception(
        "Microsoft لم يعثر على اللعبة"
    )


# =========================================================
# اسم اللعبة
# =========================================================

def get_game_name(product):

    localized = product.get(
        "LocalizedProperties",
        []
    )

    for item in localized:

        title = item.get("ProductTitle")

        if title:
            return title

    title = product.get("ProductTitle")

    if title:
        return title

    return "لعبة Xbox"


# =========================================================
# استخراج الأسعار
# =========================================================

def get_prices(product):

    results = []

    sku_availabilities = product.get(
        "DisplaySkuAvailabilities",
        []
    )

    for sku_data in sku_availabilities:

        for availability in sku_data.get(
            "Availabilities",
            []
        ):

            price_data = availability.get(
                "OrderManagementData",
                {}
            ).get(
                "Price",
                {}
            )

            if not price_data:
                continue

            currency = price_data.get(
                "CurrencyCode",
                ""
            )

            if currency:

                if currency.upper() not in (
                    "TRY",
                    "TL"
                ):
                    continue

            current = to_float(
                price_data.get("ListPrice")
            )

            original = to_float(
                price_data.get("MSRP")
            )

            if current is None:
                continue

            if current <= 0:
                continue

            end_date = availability.get(
                "Conditions",
                {}
            ).get(
                "EndDate"
            )

            if (
                original is not None
                and original > current
            ):

                results.append(
                    (
                        current,
                        original,
                        end_date
                    )
                )

            else:

                results.append(
                    (
                        current,
                        None,
                        end_date
                    )
                )

    return results


# =========================================================
# اختيار أفضل سعر
# =========================================================

def best_price(items):

    valid = []

    for current, original, end_date in items:

        try:
            current = float(current)

        except Exception:
            continue

        if current <= 0:
            continue

        if current > 50000:
            continue

        if original is not None:

            try:
                original = float(original)

            except Exception:
                original = None

        if original is not None:

            if (
                original <= current
                or original > 50000
            ):
                original = None

            else:

                discount = (
                    (original - current)
                    / original
                ) * 100

                if discount >= 99:
                    original = None

        valid.append(
            (
                current,
                original,
                end_date
            )
        )

    discounted = []

    for current, original, end_date in valid:

        if (
            original is not None
            and original > current
        ):

            discount = (
                (original - current)
                / original
            ) * 100

            if 1 <= discount < 99:

                discounted.append(
                    (
                        round(current, 2),
                        round(original, 2),
                        end_date
                    )
                )

    if discounted:

        # إذا Microsoft أعاد أكثر من سعر مخفّض لنفس المنتج،
        # نختار السعر الأكثر تكراراً. عند التعادل نختار الأعلى
        # حتى لا يظهر سعر أقل من سعر المتجر بالخطأ.
        counts = Counter(
            round(x[0], 2)
            for x in discounted
        )

        best_count = max(counts.values())
        candidates = [
            price for price, count in counts.items()
            if count == best_count
        ]
        price = max(candidates)

        matching = [
            item for item in discounted
            if round(item[0], 2) == price
        ]

        # نفس السعر المخفّض قد يظهر بأكثر من MSRP في استجابات Microsoft.
        # نختار أعلى MSRP حتى تكون نسبة الخصم مبنية على السعر الأصلي
        # الحقيقي الظاهر في المتجر، بدل اختيار أول Availability فقط.
        matching.sort(
            key=lambda x: (x[1], x[2] or ""),
            reverse=True
        )

        return matching[0]

    if not valid:
        return None, None, None

    counter = Counter(
        round(x[0], 2)
        for x in valid
    )

    best_count = max(counter.values())
    candidates = [
        price for price, count in counter.items()
        if count == best_count
    ]
    price = max(candidates)

    matching = [
        item for item in valid
        if round(item[0], 2) == price
    ]
    matching.sort(
        key=lambda x: (x[2] or "")
    )

    return matching[0][0], matching[0][1], matching[0][2]


# =========================================================
# معلومات اللعبة من Product ID
# =========================================================

def get_game_info_by_product_id(product_id):

    product = get_product_data(
        product_id
    )

    game_name = get_game_name(
        product
    )

    prices = get_prices(
        product
    )

    (
        current_price,
        original_price,
        end_date
    ) = best_price(
        prices
    )

    if current_price is None:

        raise Exception(
            "Microsoft لم يعثر على سعر اللعبة"
        )

    return (
        product_id.upper(),
        game_name,
        current_price,
        original_price,
        end_date
    )


# =========================================================
# معلومات اللعبة من الرابط
# =========================================================

def get_game_info(url):

    product_id = get_product_id(
        url
    )

    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )

    # المحاولة الأساسية: الـ Product ID الموجود بالرابط.
    try:
        return get_game_info_by_product_id(product_id)
    except Exception as direct_error:
        print("DIRECT URL LOOKUP FAILED:", product_id, repr(direct_error))

    # احتياط: بعض روابط Xbox القديمة/المحدّثة يكون الـID فيها
    # غير قابل للاسترجاع مباشرة من Display Catalog. نستخدم slug
    # من الرابط ونبحث عن المنتج الحالي بدل إرجاع خطأ للمستخدم.
    try:
        from urllib.parse import urlparse

        path = urlparse(str(url)).path.strip("/")
        parts = [part for part in path.split("/") if part]

        slug = None
        for index, part in enumerate(parts):
            if part.lower() == "store" and index + 1 < len(parts):
                slug = parts[index + 1]
                break

        if slug:
            query = re.sub(r"[-_]+", " ", slug).strip()

            results = search_xbox_games_enhanced(
                query,
                10
            )

            for alternative_id, alternative_name in results:
                try:
                    info = get_game_info_by_product_id(
                        alternative_id
                    )
                    SEARCH_RESULT_CACHE[product_id] = info
                    SEARCH_RESULT_CACHE[alternative_id] = info
                    return info
                except Exception as alternative_error:
                    print(
                        "URL FALLBACK FAILED:",
                        alternative_id,
                        alternative_name,
                        repr(alternative_error)
                    )

    except Exception as fallback_error:
        print("URL SLUG FALLBACK ERROR:", repr(fallback_error))

    raise direct_error


# =========================================================
# البحث باسم اللعبة
# =========================================================

def search_xbox_games(
    query,
    top=5
):

    url = (
        "https://displaycatalog.mp.microsoft.com/"
        "v7.0/productFamilies/autosuggest"
    )

    params = {
        "languages": "tr-TR,en-US",
        "market": "TR",
        "platformdependencyname": "windows.xbox",
        "productFamilyNames": "Games,Apps",
        "query": query,
        "topProducts": top
    }

    response = SESSION.get(
        url,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    results = []

    # الشكل الأساسي لاستجابة Microsoft
    for result_group in data.get(
        "Results",
        []
    ):

        for item in result_group.get(
            "Products",
            []
        ):

            product_id = item.get(
                "ProductId"
            )

            title = item.get(
                "Title"
            )

            if not product_id or not title:
                continue

            results.append(
                (
                    str(product_id).upper(),
                    str(title)
                )
            )

    # احتياط إذا تغير شكل الاستجابة
    if not results:

        def walk(value):

            found = []

            if isinstance(value, dict):

                product_id = value.get(
                    "ProductId"
                )

                title = value.get(
                    "Title"
                )

                if product_id and title:

                    found.append(
                        (
                            str(product_id).upper(),
                            str(title)
                        )
                    )

                for child in value.values():

                    found.extend(
                        walk(child)
                    )

            elif isinstance(value, list):

                for child in value:

                    found.extend(
                        walk(child)
                    )

            return found

        results = walk(data)

    # إزالة التكرار
    unique = []
    seen = set()

    for product_id, title in results:

        if product_id in seen:
            continue

        seen.add(product_id)

        unique.append(
            (
                product_id,
                title
            )
        )

        if len(unique) >= top:
            break

    return unique



# =========================================================
# تطبيع أسماء الإصدارات + البحث الذكي
# =========================================================

EDITION_REPLACEMENTS = [
    ("game of the year sürümü", "Game of the Year Edition"),
    ("game of the year edition", "Game of the Year Edition"),
    ("yılın oyunu sürümü", "Game of the Year Edition"),
    ("nihai sürüm", "Ultimate Edition"),
    ("ultimate sürüm", "Ultimate Edition"),
    ("altın sürüm", "Gold Edition"),
    ("gold sürüm", "Gold Edition"),
    ("lüks sürüm", "Deluxe Edition"),
    ("deluxe sürüm", "Deluxe Edition"),
    ("standart sürüm", "Standard Edition"),
    ("standard sürüm", "Standard Edition"),
    ("tam sürüm", "Complete Edition"),
    ("komple sürüm", "Complete Edition"),
    ("premium sürüm", "Premium Edition"),
    ("özel sürüm", "Special Edition"),
    ("legendary sürüm", "Legendary Edition"),
    ("definitive sürüm", "Definitive Edition"),
    ("director's cut sürüm", "Director's Cut Edition"),
    ("director’s cut sürüm", "Director's Cut Edition"),
]


def normalize_edition_name(tit
