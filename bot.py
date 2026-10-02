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
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

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

        discounted.sort(
            key=lambda x: x[0]
        )

        return discounted[0]

    if not valid:
        return None, None, None

    counter = Counter(
        round(x[0], 2)
        for x in valid
    )

    price = counter.most_common(1)[0][0]

    return price, None, None


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

    return get_game_info_by_product_id(
        product_id
    )


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


def normalize_edition_name(title):
    if not title:
        return title

    result = str(title)

    for old, new in EDITION_REPLACEMENTS:
        result = re.sub(
            re.escape(old),
            new,
            result,
            flags=re.IGNORECASE
        )

    result = re.sub(
        r"\bSürüm\b",
        "Edition",
        result,
        flags=re.IGNORECASE
    )

    return result


def normalize_search_text(text):
    text = str(text or "").lower().strip()
    text = text.replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", text)
    text = re.sub(
        r"\b(edition|sürüm|version)\b",
        " ",
        text
    )
    return re.sub(r"\s+", " ", text).strip()


def search_similarity(query, title):
    query_norm = normalize_search_text(query)
    title_norm = normalize_search_text(title)

    if not query_norm or not title_norm:
        return 0.0

    return difflib.SequenceMatcher(
        None,
        query_norm,
        title_norm
    ).ratio()


def find_search_suggestion(query, results):
    """
    يرجع نتيجة واحدة فقط إذا كان واضح أن المستخدم أخطأ
    بخطأ إملائي بسيط، وإلا يرجع None.
    """
    query_norm = normalize_search_text(query)

    if not query_norm or not results:
        return None

    best = None

    for product_id, title in results:
        title_norm = normalize_search_text(title)

        if not title_norm:
            continue

        if query_norm == title_norm:
            continue

        score = search_similarity(query, title)
        length_difference = abs(
            len(query_norm) - len(title_norm)
        )

        if score < 0.88 or length_difference > 3:
            continue

        candidate = (
            score,
            product_id,
            title
        )

        if best is None or score > best[0]:
            best = candidate

    if best:
        return best[1], best[2], best[0]

    return None


def generate_typo_variants(query, max_variants=12):
    """
    يولد محاولات بسيطة للأخطاء الإملائية:
    - إضافة حرف صوتي مفقود
    - حذف حرف زائد
    - تبديل حرفين متجاورين
    """
    query = str(query or "").strip()

    if not query:
        return []

    variants = []
    seen = {query.lower()}

    def add(value):
        value = value.strip()

        if (
            len(value) < 2
            or value.lower() in seen
            or len(variants) >= max_variants
        ):
            return

        seen.add(value.lower())
        variants.append(value)

    words = query.split()

    # أولاً: إضافة حرف صوتي. هذا يعالج أخطاء مثل Raidr -> Raider.
    vowels = "eaiou"

    for vowel in vowels:
        for word_index, word in enumerate(words):
            if len(word) < 3:
                continue

            for char_index in range(len(word) + 1):
                new_word = (
                    word[:char_index]
                    + vowel
                    + word[char_index:]
                )

                new_words = list(words)
                new_words[word_index] = new_word
                add(" ".join(new_words))

                if len(variants) >= max_variants:
                    return variants

    # ثانياً: حذف حرف زائد.
    for word_index, word in enumerate(words):
        if len(word) < 4:
            continue

        for char_index in range(len(word)):
            new_word = (
                word[:char_index]
                + word[char_index + 1:]
            )

            new_words = list(words)
            new_words[word_index] = new_word
            add(" ".join(new_words))

            if len(variants) >= max_variants:
                return variants

    # ثالثاً: تبديل حرفين متجاورين.
    for word_index, word in enumerate(words):
        if len(word) < 4:
            continue

        for char_index in range(len(word) - 1):
            chars = list(word)
            chars[char_index], chars[char_index + 1] = (
                chars[char_index + 1],
                chars[char_index]
            )

            new_words = list(words)
            new_words[word_index] = "".join(chars)
            add(" ".join(new_words))

            if len(variants) >= max_variants:
                return variants

    return variants


def search_xbox_games_enhanced(query, top=5):
    """
    البحث العادي أولاً.
    إذا لم نجد نتائج، نجرب تصحيحات إملائية بسيطة.
    """
    results = search_xbox_games(query, top)

    if results:
        return results

    for variant in generate_typo_variants(query):
        try:
            variant_results = search_xbox_games(
                variant,
                top
            )

            if variant_results:
                return variant_results

        except Exception as error:
            print(
                "TYPO SEARCH FAILED:",
                variant,
                repr(error)
            )

    return []

# =========================================================
# حل نتيجة البحث بشكل موثوق
# =========================================================

def resolve_search_result(product_id, result_name=None):

    product_id = str(product_id).upper()

    # إذا البيانات موجودة بالكاش نستخدمها مباشرة
    cached = SEARCH_RESULT_CACHE.get(product_id)

    if cached:
        return cached

    # المحاولة الأولى: Product ID المباشر
    try:

        info = get_game_info_by_product_id(product_id)
        SEARCH_RESULT_CACHE[product_id] = info
        return info

    except Exception as first_error:

        print(
            "DIRECT PRODUCT LOOKUP FAILED:",
            product_id,
            repr(first_error)
        )

    # بعض نتائج autosuggest تكون IDs لنسخة/إضافة
    # بينما الاسم نفسه يحتوي على المنتج الأساسي.
    # نعيد البحث بالاسم ونجرّب كل IDs الناتجة.
    if result_name:

        try:

            alternatives = search_xbox_games(
                result_name,
                top=10
            )

            tried = set()

            for alternative_id, alternative_name in alternatives:

                alternative_id = alternative_id.upper()

                if alternative_id in tried:
                    continue

                tried.add(alternative_id)

                try:

                    info = get_game_info_by_product_id(
                        alternative_id
                    )

                    SEARCH_RESULT_CACHE[product_id] = info
                    SEARCH_RESULT_CACHE[alternative_id] = info

                    return info

                except Exception as alternative_error:

                    print(
                        "ALTERNATIVE PRODUCT FAILED:",
                        alternative_id,
                        alternative_name,
                        repr(alternative_error)
                    )

        except Exception as search_error:

            print(
                "ALTERNATIVE SEARCH FAILED:",
                result_name,
                repr(search_error)
            )

    raise Exception(
        "ماكدرت أجيب سعر نتيجة البحث"
    )


# =========================================================
# تنسيق السعر
# =========================================================

def format_store_price(price):

    price = int(price)

    if price % 1000 == 0:

        return (
            f"{price // 1000} ألف"
        )

    return (
        f"{price:,} دينار"
        .replace(",", ".")
    )


# =========================================================
# حفظ آخر بحث
# =========================================================

def save_last_request(
    user_id,
    product_id,
    game_name,
    url,
    current_price
):

    connection = sqlite3.connect(
        DB_FILE
    )

    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO last_requests
        (
            user_id,
            product_id,
            game_name,
            url,
            current_price,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            user_id,
            product_id,
            game_name,
            url,
            int(current_price)
        )
    )

    connection.commit()
    connection.close()


# =========================================================
# آخر بحث
# =========================================================

def get_last_request(
    user_id,
    product_id
):

    connection = sqlite3.connect(
        DB_FILE
    )

    result = connection.execute(
        """
        SELECT
            game_name,
            url,
            current_price
        FROM last_requests
        WHERE user_id = ?
        AND product_id = ?
        LIMIT 1
        """,
        (
            user_id,
            product_id
        )
    ).fetchone()

    connection.close()

    return result


# =========================================================
# التنبيه موجود؟
# =========================================================

def alert_exists(
    user_id,
    product_id
):

    connection = sqlite3.connect(
        DB_FILE
    )

    result = connection.execute(
        """
        SELECT id
        FROM alerts
        WHERE user_id = ?
        AND product_id = ?
        AND active = 1
        LIMIT 1
        """,
        (
            user_id,
            product_id
        )
    ).fetchone()

    connection.close()

    return result is not None


# =========================================================
# إضافة تنبيه
# =========================================================

def add_alert(
    user_id,
    chat_id,
    product_id,
    game_name,
    url,
    old_price
):

    connection = sqlite3.connect(
        DB_FILE
    )

    existing = connection.execute(
        """
        SELECT id
        FROM alerts
        WHERE user_id = ?
        AND product_id = ?
        AND active = 1
        LIMIT 1
        """,
        (
            user_id,
            product_id
        )
    ).fetchone()

    if existing:

        connection.close()

        return False

    connection.execute(
        """
        INSERT INTO alerts
        (
            user_id,
            chat_id,
            product_id,
            game_name,
            url,
            old_price,
            active
        )
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (
            user_id,
            chat_id,
            product_id,
            game_name,
            url,
            int(old_price)
        )
    )

    connection.commit()
    connection.close()

    return True


# =========================================================
# إلغاء التنبيه
# =========================================================

def cancel_alert(
    user_id,
    product_id
):

    connection = sqlite3.connect(
        DB_FILE
    )

    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE alerts
        SET active = 0
        WHERE user_id = ?
        AND product_id = ?
        AND active = 1
        """,
        (
            user_id,
            product_id
        )
    )

    changed = cursor.rowcount

    connection.commit()
    connection.close()

    return changed > 0


# =========================================================
# التنبيهات الفعالة
# =========================================================

def get_active_alerts():

    connection = sqlite3.connect(
        DB_FILE
    )

    rows = connection.execute(
        """
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
        """
    ).fetchall()

    connection.close()

    return rows


# =========================================================
# إيقاف التنبيه
# =========================================================

def deactivate_alert(
    alert_id
):

    connection = sqlite3.connect(
        DB_FILE
    )

    connection.execute(
        """
        UPDATE alerts
        SET active = 0
        WHERE id = ?
        """,
        (
            alert_id,
        )
    )

    connection.commit()
    connection.close()


# =========================================================
# التاريخ
# =========================================================

def parse_end_date(end_date):

    if not end_date:
        return None

    try:

        value = str(
            end_date
        ).strip()

        if value.endswith("Z"):

            value = (
                value[:-1]
                + "+00:00"
            )

        return datetime.fromisoformat(
            value
        )

    except Exception:

        return None


# =========================================================
# الوقت المتبقي
# =========================================================

def get_remaining_text(end_date):

    dt = parse_end_date(
        end_date
    )

    if not dt:
        return None

    if dt.tzinfo is None:

        dt = dt.replace(
            tzinfo=timezone.utc
        )

    else:

        dt = dt.astimezone(
            timezone.utc
        )

    remaining = (
        dt
        - datetime.now(timezone.utc)
    )

    if remaining.total_seconds() <= 0:
        return None

    seconds = int(
        remaining.total_seconds()
    )

    days = seconds // 86400

    hours = (
        seconds % 86400
    ) // 3600

    minutes = (
        seconds % 3600
    ) // 60

    if days > 1:

        text = (
            f"متبقي: {days} يوم"
        )

        if hours:
            text += (
                f" و{hours} ساعة"
            )

    elif days == 1:

        text = "متبقي: يوم واحد"

        if hours:
            text += (
                f" و{hours} ساعة"
            )

    elif hours:

        text = (
            f"متبقي: {hours} ساعة"
        )

        if minutes:
            text += (
                f" و{minutes} دقيقة"
            )

    else:

        text = (
            f"متبقي: {max(minutes, 1)} دقيقة"
        )

    return (
        text,
        dt.strftime("%Y-%m-%d"),
        dt.strftime("%H:%M")
    )


# =========================================================
# تحديد محتوى DLC / الإضافات
# =========================================================

def is_dlc_title(game_name):

    text = str(game_name or "").strip()

    # نخفي تنبيه السعر عن الـ DLC والإضافات فقط.
    # لا نعتمد على كلمات عامة مثل Bundle حتى لا نمنع التنبيه
    # عن الإصدارات والباندلات التي قد تكون لعبة كاملة.
    patterns = [
        r"\bDLC\b",
        r"\bADD[- ]?ON\b",
        r"\bEXPANSION\b",
        r"\bEKLENTI\b",
        r"\bEKLENTİ\b",
    ]

    return any(
        re.search(pattern, text, flags=re.IGNORECASE)
        for pattern in patterns
    )


# =========================================================
# أزرار اللعبة
# =========================================================

def get_game_keyboard(
    product_id,
    active,
    show_back=False,
    has_discount=False,
    is_favorite=False,
    is_dlc=False
):

    buttons = [
        [
            InlineKeyboardButton(
                "🛒 اطلب الآن",
                callback_data=f"order:{product_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 نسخ السعر",
                callback_data=f"copy:{product_id}"
            ),
            InlineKeyboardButton(
                "💛 إزالة من المفضلة" if is_favorite else "⭐ أضف للمفضلة",
                callback_data=f"favremove:{product_id}" if is_favorite else f"favadd:{product_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "⭐ ألعابي المفضلة",
                callback_data="favlist"
            )
        ]
    ]

    # زر التنبيه يظهر فقط إذا اللعبة غير مخفضة وليست DLC.
    if not has_discount and not is_dlc:

        if active:

            buttons.append(
                [
                    InlineKeyboardButton(
                        "🔕 إلغاء التنبيه",
                        callback_data=f"cancel:{product_id}"
                    )
                ]
            )

        else:

            buttons.append(
                [
                    InlineKeyboardButton(
                        "🔔 نبهني إذا نزل السعر",
                        callback_data=f"alert:{product_id}"
                    )
                ]
            )

    if show_back:

        buttons.append(
            [
                InlineKeyboardButton(
                    "🔙 رجوع للإصدارات",
                    callback_data="backsearch"
                )
            ]
        )

    return InlineKeyboardMarkup(buttons)


# =========================================================
# إنشاء نتيجة اللعبة
# =========================================================

def create_game_result(
    update,
    product_id,
    game_name,
    turkey_price,
    original_price,
    end_date,
    reference,
    show_back=False
):

    store_price = calculate_price(
        turkey_price
    )

    # create_game_result() يُستخدم من الرسائل العادية ومن ضغط الأزرار.
    # في الرسالة العادية يكون لدينا Update.effective_user،
    # أما CallbackQuery فالمستخدم موجود في from_user.
    user = getattr(update, "effective_user", None)

    if user is None:
        user = getattr(update, "from_user", None)

    if user is None:
        raise Exception("ماكدرت أحدد المستخدم")

    save_last_request(
        user.id,
        product_id,
        game_name,
        reference,
        store_price
    )

    discount_percent = None

    if (
        original_price is not None
        and original_price > turkey_price
    ):

        discount_percent = round(
            (
                (
                    original_price
                    - turkey_price
                )
                / original_price
            ) * 100
        )

    expiry_text = ""

    if discount_percent is not None:

        remaining = get_remaining_text(
            end_date
        )

        if remaining:

            (
                remaining_text,
                date_text,
                time_text
            ) = remaining

            expiry_text = (
                f"\n⏳ <b>ينتهي التخفيض:</b> "
                f"{date_text} الساعة {time_text}\n"
                f"📅 <b>{remaining_text}</b>\n"
            )

    price_text = format_store_price(
        store_price
    )

    display_game_name = normalize_edition_name(
        game_name
    )

    if discount_percent is not None:

        message = (
            f"🎮 <b>{display_game_name}</b>\n\n"
            "🔥 <b>اللعبة عليها تخفيض!</b>\n\n"
            f"📉 نسبة الخصم: "
            f"<b>{discount_percent}%</b>\n"
            f"{expiry_text}\n"
            f"💰 سعر اللعبة: "
            f"<b>{price_text}</b> 🇮🇶"
        )

    else:

        message = (
            f"🎮 <b>{display_game_name}</b>\n\n"
            f"💰 سعر اللعبة: "
            f"<b>{price_text}</b> 🇮🇶"
        )

    keyboard = get_game_keyboard(
        product_id,
        alert_exists(
            user.id,
            product_id
        ),
        show_back,
        discount_percent is not None,
        favorite_exists(
            user.id,
            product_id
        ),
        is_dlc=is_dlc_title(game_name)
    )

    return message, keyboard


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.message:

        keyboard = None

        if ADMIN_CHAT_ID and str(update.effective_user.id) == str(ADMIN_CHAT_ID):
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🧾 سجل الطلبات",
                        callback_data="adminorders"
                    )
                ]
            ])

        await update.message.reply_text(
            "🎮 أرسل رابط لعبة من Xbox Store\n"
            "أو اكتب اسم اللعبة 🔍",
            reply_markup=keyboard
        )


# =========================================================
# ID
# =========================================================

async def my_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.message:

        await update.message.reply_text(
            f"🆔 Telegram ID مالك:\n\n"
            f"{update.effective_user.id}"
        )


# =========================================================
# سجل الطلبات - أمر الأدمن
# =========================================================

async def admin_orders_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not ADMIN_CHAT_ID or str(update.effective_user.id) != str(ADMIN_CHAT_ID):
        await update.message.reply_text(
            "❌ هذا الأمر للأدمن فقط."
        )
        return

    orders = get_orders(50)

    if not orders:
        await update.message.reply_text(
            "🧾 سجل الطلبات\n\nماكو طلبات مسجلة حالياً."
        )
        return

    lines = ["🧾 <b>سجل الطلبات</b>", ""]

    for order_id, customer_name, game_name, price, created_at in orders:
        price_text = (
            format_store_price(price)
            if price is not None
            else "غير معروف"
        )
        lines.append(
            f"<b>#{order_id}</b> 🎮 {game_name[:45]}\n"
            f"👤 {customer_name}\n"
            f"💰 {price_text} 🇮🇶\n"
            f"🕐 {created_at}"
        )
        lines.append("────────────")

    lines.append("\n📌 آخر 50 طلب فقط")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 تحديث",
                    callback_data="adminorders"
                )
            ]
        ])
    )


# =========================================================
# استقبال الرابط أو اسم اللعبة
# =========================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    text = update.message.text.strip()

    if len(text) < 2:
        return

    processing = await update.message.reply_text(
        "⏳ جاري البحث..."
    )

    try:

        # =================================================
        # رابط Xbox
        # =================================================

        if "xbox.com" in text.lower():

            (
                product_id,
                game_name,
                turkey_price,
                original_price,
                end_date
            ) = await asyncio.to_thread(
                get_game_info,
                text
            )

            message, keyboard = create_game_result(
                update,
                product_id,
                game_name,
                turkey_price,
                original_price,
                end_date,
                text
            )

            await processing.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

            return

        # =================================================
        # اسم اللعبة
        # =================================================

        results = await asyncio.to_thread(
            search_xbox_games_enhanced,
            text,
            5
        )

        if not results:

            await processing.edit_text(
                "❌ ما لكيت اللعبة.\n\n"
                "جرب تكتب الاسم بالإنجليزي "
                "أو أرسل رابط Xbox Store."
            )

            return

        # نفحص النتائج قبل عرضها، لكن نحتفظ باسم النتيجة.
        # إذا كان Product ID المباشر غير قابل للتسعير،
        # resolve_search_result يبحث عن النسخة القابلة للتسعير.
        valid_results = []

        for product_id, result_name in results:

            try:

                info = await asyncio.to_thread(
                    resolve_search_result,
                    product_id,
                    result_name
                )

                resolved_product_id = info[0]
                resolved_name = info[1]

                SEARCH_RESULT_CACHE[product_id] = info
                SEARCH_RESULT_CACHE[resolved_product_id] = info

                valid_results.append(
                    (
                        product_id,
                        result_name
                    )
                )

            except Exception as error:

                print(
                    "SEARCH RESULT SKIPPED:",
                    product_id,
                    result_name,
                    repr(error)
                )

        if not valid_results:

            await processing.edit_text(
                "❌ لكيت نتائج للعبة، لكن ماكو سعر متاح "
                "إلها حالياً.\n\n"
                "جرب اسم اللعبة مرة ثانية أو أرسل رابط Xbox Store."
            )

            return

        # =================================================
        # اقتراح تصحيح إملائي واضح
        # =================================================

        suggestion = find_search_suggestion(
            text,
            valid_results
        )

        if suggestion:
            (
                suggestion_product_id,
                suggestion_name,
                suggestion_score
            ) = suggestion

            suggestion_display_name = normalize_edition_name(
                suggestion_name
            )

            await processing.edit_text(
                "🔎 <b>هل تقصد:</b>\n\n"
                f"🎮 <b>{suggestion_display_name[:70]}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            f"🎮 {suggestion_display_name[:55]}",
                            callback_data=(
                                f"suggestsearch:{suggestion_product_id}"
                            )
                        )
                    ]
                ])
            )

            return

        # =================================================
        # نتيجة واحدة
        # =================================================

        if len(valid_results) == 1:

            product_id, result_name = valid_results[0]

            info = SEARCH_RESULT_CACHE.get(
                product_id
            )

            if not info:

                info = await asyncio.to_thread(
                    resolve_search_result,
                    product_id,
                    result_name
                )

            (
                resolved_product_id,
                game_name,
                turkey_price,
                original_price,
                end_date
            ) = info

            message, keyboard = create_game_result(
                update,
                resolved_product_id,
                game_name,
                turkey_price,
                original_price,
                end_date,
                f"xboxid:{resolved_product_id}"
            )

            await processing.edit_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

            return

        # =================================================
        # أكثر من نتيجة
        # =================================================

        # نحفظ آخر قائمة نتائج لهذا المستخدم حتى يقدر يرجع لها
        # بعد فتح أي إصدار.
        SEARCH_SELECTIONS[update.effective_user.id] = list(
            valid_results
        )

        buttons = []

        for product_id, result_name in valid_results:

            display_name = normalize_edition_name(
                result_name
            )

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"🎮 {display_name[:50]}",
                        callback_data=(
                            f"searchselect:{product_id}"
                        )
                    )
                ]
            )

        await processing.edit_text(
            "🔍 <b>لكيت أكثر من نتيجة:</b>\n\n"
            "اختار اللعبة المطلوبة 👇",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                buttons
            )
        )

    except Exception as error:

        print(
            "GAME ERROR:",
            repr(error)
        )

        await processing.edit_text(
            "❌ صار خطأ أثناء جلب معلومات اللعبة.\n\n"
            "تأكد من الاسم أو الرابط وجرب مرة ثانية."
        )


# =========================================================
# التنبيهات
# =========================================================

async def check_price_alerts(
    app
):

    alerts = get_active_alerts()

    for (
        alert_id,
        user_id,
        chat_id,
        product_id,
        game_name,
        reference,
        old_price
    ) in alerts:

        try:

            if reference.startswith(
                "xboxid:"
            ):

                (
                    new_product_id,
                    new_game_name,
                    turkey_price,
                    original_price,
                    end_date
                ) = await asyncio.to_thread(
                    get_game_info_by_product_id,
                    product_id
                )

            else:

                (
                    new_product_id,
                    new_game_name,
                    turkey_price,
                    original_price,
                    end_date
                ) = await asyncio.to_thread(
                    get_game_info,
                    reference
                )

            new_price = calculate_price(
                turkey_price
            )

            if is_dlc_title(new_game_name):
                deactivate_alert(alert_id)
                continue

            if new_price < old_price:

                message = (
                    "🚨 <b>انخفض سعر اللعبة!</b>\n\n"
                    f"🎮 <b>{new_game_name}</b>\n\n"
                    f"💰 السعر السابق: "
                    f"<b>{format_store_price(old_price)}</b> 🇮🇶\n"
                    f"🔥 السعر الجديد: "
                    f"<b>{format_store_price(new_price)}</b> 🇮🇶\n\n"
                    "🛒 تقدر تطلبها الآن"
                )

                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🛒 اطلب الآن",
                            callback_data=f"order:{product_id}"
                        )
                    ]
                ])

                await app.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )

                deactivate_alert(
                    alert_id
                )

        except Exception as error:

            print(
                "ALERT ERROR:",
                alert_id,
                repr(error)
            )


# =========================================================
# سجل الطلبات
# =========================================================

def save_order(
    user_id,
    customer_name,
    game_name,
    product_id,
    price
):

    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO orders
        (user_id, customer_name, game_name, product_id, price)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            customer_name,
            game_name,
            product_id,
            price
        )
    )

    connection.commit()
    connection.close()


def get_orders(limit=50):

    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT id, customer_name, game_name, price, created_at
        FROM orders
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    )

    rows = cursor.fetchall()
    connection.close()
    return rows


# =========================================================
# حلقة التنبيهات
# =========================================================

async def alert_loop(
    app
):

    await asyncio.sleep(
        60
    )

    while True:

        try:

            await check_price_alerts(
                app
            )

        except Exception as error:

            print(
                "ALERT LOOP ERROR:",
                repr(error)
            )

        await asyncio.sleep(
            172800
        )


# =========================================================
# الأزرار
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    user = query.from_user
    user_id = user.id

    # =====================================================
    # سجل الطلبات - للأدمن فقط
    # =====================================================

    if data == "adminorders":

        if not ADMIN_CHAT_ID or str(user_id) != str(ADMIN_CHAT_ID):
            await query.answer(
                "❌ هذا القسم للأدمن فقط",
                show_alert=True
            )
            return

        orders = get_orders(50)

        if not orders:
            await query.answer()
            await query.edit_message_text(
                "🧾 <b>سجل الطلبات</b>\n\n"
                "ماكو طلبات مسجلة حالياً.",
                parse_mode="HTML"
            )
            return

        lines = ["🧾 <b>سجل الطلبات</b>", ""]

        for order_id, customer_name, game_name, price, created_at in orders:
            price_text = (
                format_store_price(price)
                if price is not None
                else "غير معروف"
            )
            lines.append(
                f"<b>#{order_id}</b> 🎮 {game_name[:45]}\n"
                f"👤 {customer_name}\n"
                f"💰 {price_text} 🇮🇶\n"
                f"🕐 {created_at}"
            )
            lines.append("────────────")

        lines.append("\n📌 آخر 50 طلب فقط")

        await query.answer()
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔄 تحديث",
                        callback_data="adminorders"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 الرئيسية",
                        callback_data="adminhome"
                    )
                ]
            ])
        )
        return

    # =====================================================
    # الرئيسية - للأدمن
    # =====================================================

    if data == "adminhome":

        if not ADMIN_CHAT_ID or str(user_id) != str(ADMIN_CHAT_ID):
            await query.answer(
                "❌ هذا القسم للأدمن فقط",
                show_alert=True
            )
            return

        await query.answer()
        await query.edit_message_text(
            "🎮 <b>SA STORE</b>\n\n"
            "أرسل رابط لعبة من Xbox Store\n"
            "أو اكتب اسم اللعبة 🔍",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🧾 سجل الطلبات",
                        callback_data="adminorders"
                    )
                ]
            ])
        )
        return

    # =====================================================
    # اختيار نتيجة البحث
    # =====================================================

    if (
        data.startswith("searchselect:")
        or data.startswith("suggestsearch:")
    ):

        is_suggestion = data.startswith(
            "suggestsearch:"
        )

        product_id = data.split(
            ":",
            1
        )[1].upper()

        await query.answer(
            "⏳ جاري جلب السعر..."
            if not is_suggestion
            else "⏳ جاري جلب اللعبة المقترحة..."
        )

        try:

            # نستخدم الكاش أولاً، وإذا البوت أعاد التشغيل
            # نستخدم Product ID مباشرة.
            info = SEARCH_RESULT_CACHE.get(
                product_id
            )

            if info is None:

                info = await asyncio.to_thread(
                    get_game_info_by_product_id,
                    product_id
                )

                SEARCH_RESULT_CACHE[product_id] = info

            (
                resolved_product_id,
                game_name,
                turkey_price,
                original_price,
                end_date
            ) = info

            message, keyboard = create_game_result(
                query,
                resolved_product_id,
                game_name,
                turkey_price,
                original_price,
                end_date,
                f"xboxid:{resolved_product_id}",
                show_back=(
                    True
                    if not is_suggestion
                    else user_id in SEARCH_SELECTIONS
                )
            )

            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

        except Exception as error:

            print(
                "SEARCH SELECT ERROR:",
                product_id,
                repr(error)
            )

            await query.edit_message_text(
                "❌ ماكدرت أجيب سعر اللعبة، "
                "حاول مرة ثانية."
            )

        return

    # =====================================================
    # الرجوع إلى قائمة إصدارات اللعبة
    # =====================================================

    if data == "backsearch":

        results = SEARCH_SELECTIONS.get(
            user_id
        )

        if not results:

            await query.answer(
                "❌ قائمة الإصدارات غير متوفرة، ابحث عن اللعبة مرة ثانية.",
                show_alert=True
            )

            return

        buttons = []

        for result_product_id, result_name in results:

            display_name = normalize_edition_name(
                result_name
            )

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"🎮 {display_name[:50]}",
                        callback_data=(
                            f"searchselect:{result_product_id}"
                        )
                    )
                ]
            )

        await query.answer(
            "🔙 رجعناك لقائمة الإصدارات"
        )

        await query.edit_message_text(
            "🔍 <b>لكيت أكثر من نتيجة:</b>\n\n"
            "اختار اللعبة المطلوبة 👇",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                buttons
            )
        )

        return

    # =====================================================
    # نسخ السعر / معلومات اللعبة
    # =====================================================

    if data.startswith("copy:"):

        product_id = data.split(":", 1)[1]
        last_request = get_last_request(user_id, product_id)

        if not last_request:
            await query.answer(
                "❌ معلومات اللعبة غير متوفرة، ابحث عنها مرة ثانية.",
                show_alert=True
            )
            return

        game_name, url, current_price = last_request

        copy_text = (
            f"🎮 {game_name}\n"
            f"💰 السعر: {format_store_price(current_price)} 🇮🇶"
        )

        try:
            info = await asyncio.to_thread(
                get_game_info_by_product_id,
                product_id
            )

            _, _, turkey_price, original_price, _ = info

            if (
                original_price is not None
                and original_price > turkey_price
            ):
                discount_percent = round(
                    ((original_price - turkey_price) / original_price) * 100
                )
                copy_text += f"\n📉 الخصم: {discount_percent}%"
        except Exception:
            pass

        await query.answer("📋 تم تجهيز معلومات اللعبة")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=copy_text
        )
        return

    # =====================================================
    # إضافة للمفضلة
    # =====================================================

    if data.startswith("favadd:"):

        product_id = data.split(":", 1)[1]
        last_request = get_last_request(user_id, product_id)

        if not last_request:
            await query.answer(
                "❌ ابحث عن اللعبة مرة ثانية.",
                show_alert=True
            )
            return

        game_name, url, current_price = last_request
        add_favorite(user_id, product_id, game_name, url, current_price)

        has_discount = False

        try:
            info = await asyncio.to_thread(
                get_game_info_by_product_id,
                product_id
            )
            _, _, turkey_price, original_price, _ = info
            has_discount = (
                original_price is not None
                and original_price > turkey_price
            )
        except Exception:
            pass

        await query.answer("⭐ تمت إضافة اللعبة للمفضلة")

        await query.edit_message_reply_markup(
            reply_markup=get_game_keyboard(
                product_id,
                alert_exists(user_id, product_id),
                show_back=user_id in SEARCH_SELECTIONS,
                has_discount=has_discount,
                is_favorite=True,
                is_dlc=is_dlc_title(game_name)
            )
        )
        return

    # =====================================================
    # إزالة من المفضلة
    # =====================================================

    if data.startswith("favremove:"):

        product_id = data.split(":", 1)[1]
        remove_favorite(user_id, product_id)

        await query.answer("💔 تمت إزالة اللعبة من المفضلة")

        # نعيد جلب معلومات آخر طلب حتى نعرف هل عليها تخفيض أم لا.
        last_request = get_last_request(user_id, product_id)
        has_discount = False
        current_game_name = last_request[0] if last_request else ""

        if last_request:
            try:
                info = await asyncio.to_thread(
                    get_game_info_by_product_id,
                    product_id
                )
                _, current_game_name, turkey_price, original_price, _ = info
                has_discount = (
                    original_price is not None
                    and original_price > turkey_price
                )
            except Exception:
                pass

        await query.edit_message_reply_markup(
            reply_markup=get_game_keyboard(
                product_id,
                alert_exists(user_id, product_id),
                show_back=user_id in SEARCH_SELECTIONS,
                has_discount=has_discount,
                is_favorite=False,
                is_dlc=is_dlc_title(current_game_name)
            )
        )
        return

    # =====================================================
    # قائمة المفضلة
    # =====================================================

    if data == "favlist":

        favorites = get_favorites(user_id)

        if not favorites:
            await query.answer(
                "⭐ ما عندك ألعاب بالمفضلة حالياً.",
                show_alert=True
            )
            return

        buttons = []

        for product_id, game_name, url, current_price in favorites:
            buttons.append([
                InlineKeyboardButton(
                    f"⭐ {game_name[:50]}",
                    callback_data=f"favopen:{product_id}"
                )
            ])

        await query.answer()
        await query.edit_message_text(
            "⭐ <b>ألعابك المفضلة:</b>\n\n"
            "اختار لعبة حتى تشوف سعرها الحالي 👇",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # =====================================================
    # فتح لعبة من المفضلة
    # =====================================================

    if data.startswith("favopen:"):

        product_id = data.split(":", 1)[1]

        await query.answer("⏳ جاري تحديث السعر...")

        try:
            info = await asyncio.to_thread(
                get_game_info_by_product_id,
                product_id
            )

            (
                resolved_product_id,
                game_name,
                turkey_price,
                original_price,
                end_date
            ) = info

            message, keyboard = create_game_result(
                query,
                resolved_product_id,
                game_name,
                turkey_price,
                original_price,
                end_date,
                f"xboxid:{resolved_product_id}",
                show_back=False
            )

            await query.edit_message_text(
                message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

        except Exception as error:
            print("FAVORITE OPEN ERROR:", product_id, repr(error))
            await query.edit_message_text(
                "❌ ماكدرت أحدث سعر اللعبة، حاول مرة ثانية."
            )

        return

    # =====================================================
    # تفعيل التنبيه
    # =====================================================

    if data.startswith(
        "alert:"
    ):

        product_id = data.split(
            ":",
            1
        )[1]

        last_request = get_last_request(
            user_id,
            product_id
        )

        if not last_request:

            await query.answer(
                "❌ ابحث عن اللعبة مرة ثانية",
                show_alert=True
            )

            return

        (
            game_name,
            url,
            current_price
        ) = last_request

        if is_dlc_title(game_name):
            await query.answer(
                "ℹ️ تنبيهات الأسعار غير متاحة للـ DLC والإضافات.",
                show_alert=True
            )
            return

        added = add_alert(
            user_id,
            query.message.chat_id,
            product_id,
            game_name,
            url,
            current_price
        )

        if not added:

            await query.answer(
                "🔔 التنبيه مفعّل مسبقاً",
                show_alert=True
            )

            return

        await query.answer(
            "🔔 تم تفعيل التنبيه!",
            show_alert=True
        )

        await query.edit_message_reply_markup(
            reply_markup=get_game_keyboard(
                product_id,
                True,
                show_back=user_id in SEARCH_SELECTIONS,
                has_discount=False,
                is_favorite=favorite_exists(user_id, product_id),
                is_dlc=is_dlc_title(game_name)
            )
        )

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "🔔 <b>تم تفعيل تنبيه انخفاض السعر</b>\n\n"
                f"🎮 {game_name}\n"
                f"💰 السعر الحالي: "
                f"<b>{format_store_price(current_price)}</b> 🇮🇶\n\n"
                "راح أنبهك إذا نزل السعر."
            ),
            parse_mode="HTML"
        )

        return

    # =====================================================
    # إلغاء التنبيه
    # =====================================================

    if data.startswith(
        "cancel:"
    ):

        product_id = data.split(
            ":",
            1
        )[1]

        cancelled = cancel_alert(
            user_id,
            product_id
        )

        if cancelled:

            await query.answer(
                "🔕 تم إلغاء التنبيه",
                show_alert=True
            )

            cancel_request = get_last_request(user_id, product_id)
            cancel_game_name = cancel_request[0] if cancel_request else ""

            await query.edit_message_reply_markup(
                reply_markup=get_game_keyboard(
                    product_id,
                    False,
                    show_back=True,
                    has_discount=False,
                    is_favorite=favorite_exists(user_id, product_id),
                    is_dlc=is_dlc_title(cancel_game_name)
                )
            )

        else:

            await query.answer(
                "ماكو تنبيه فعال لهذه اللعبة",
                show_alert=True
            )

        return

    # =====================================================
    # الطلب
    # =====================================================

    if data.startswith(
        "order:"
    ):

        product_id = data.split(
            ":",
            1
        )[1]

        last_request = get_last_request(
            user_id,
            product_id
        )

        game_name = "لعبة Xbox"
        current_price = None

        if last_request:

            (
                game_name,
                game_url,
                current_price
            ) = last_request

        if user.username:

            customer_name = (
                f"@{user.username}"
            )

        else:

            customer_name = (
                user.full_name
                or "بدون اسم"
            )

        save_order(
            user_id,
            customer_name,
            game_name,
            product_id,
            current_price
        )

        price_text = ""

        if current_price is not None:

            price_text = (
                f"\n💰 السعر: "
                f"<b>{format_store_price(current_price)}</b> 🇮🇶"
            )

        admin_message = (
            "🛒 <b>طلب جديد!</b>\n\n"
            f"🎮 اللعبة: <b>{game_name}</b>\n"
            f"👤 الزبون: <b>{customer_name}</b>\n"
            f"🆔 ID: <code>{user_id}</code>"
            f"{price_text}"
        )

        if ADMIN_CHAT_ID:

            try:

                await context.bot.send_message(
                    chat_id=int(
                        ADMIN_CHAT_ID
                    ),
                    text=admin_message,
                    parse_mode="HTML"
                )

            except Exception as error:

                print(
                    "ADMIN ERROR:",
                    repr(error)
                )

        customer_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 تواصل مع @Sijadsa",
                    url=ORDER_URL
                )
            ]
        ])

        await query.answer(
            "🛒 تم تسجيل طلبك!",
            show_alert=True
        )

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "🛒 <b>تم تسجيل طلبك</b>\n\n"
                f"🎮 {game_name}\n\n"
                "تقدر تتواصل ويا صاحب المتجر "
                "لإكمال الطلب."
            ),
            parse_mode="HTML",
            reply_markup=customer_keyboard
        )

        return


# =========================================================
# POST INIT
# =========================================================

async def post_init(
    application: Application
):

    init_database()

    application.create_task(
        alert_loop(
            application
        )
    )

    print(
        "SA STORE BOT IS RUNNING..."
    )


# =========================================================
# MAIN
# =========================================================

def main():

    init_database()

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
            my_id
        )
    )

    application.add_handler(
        CommandHandler(
            "orders",
            admin_orders_command
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    application.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
