import os
import re
import math
import asyncio
import sqlite3
import requests
import time

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

# أقل نسبة خصم حتى تظهر اللعبة في العروض القوية
STRONG_DEAL_MIN_DISCOUNT = 50

# عدد الألعاب التي نحاول جلبها من قائمة عروض Xbox
DEALS_FETCH_COUNT = 200

# تحديث العروض كل 30 دقيقة
DEALS_UPDATE_SECONDS = 1800


if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN غير موجود في Variables"
    )


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
    "Accept-Language": (
        "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
    ),
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


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

    connection.commit()
    connection.close()


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
# تحويل السعر إلى رقم
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
# جلب منتج واحد من Microsoft
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

    products = data.get(
        "Products",
        []
    )

    if products:
        return products[0]

    product = data.get("Product")

    if product:
        return product

    raise Exception(
        "Microsoft لم يعثر على اللعبة"
    )


# =========================================================
# جلب عدة منتجات دفعة واحدة
# =========================================================

def get_products_data(product_ids):

    if not product_ids:
        return []

    url = (
        "https://displaycatalog.mp.microsoft.com/"
        "v7.0/products"
    )

    # Microsoft يقبل bigIds مفصولة بفواصل
    ids_text = ",".join(
        product_ids
    )

    params = {
        "bigIds": ids_text,
        "market": "TR",
        "languages": "tr-TR,en-US",
        "fieldsTemplate": "Details",
        "actionFilter": "Browse"
    }

    response = SESSION.get(
        url,
        params=params,
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    products = data.get(
        "Products",
        []
    )

    if isinstance(products, list):
        return products

    return []


# =========================================================
# اسم اللعبة
# =========================================================

def get_game_name(product):

    localized = product.get(
        "LocalizedProperties",
        []
    )

    for item in localized:

        title = item.get(
            "ProductTitle"
        )

        if title:
            return title

    title = product.get(
        "ProductTitle"
    )

    if title:
        return title

    return "لعبة Xbox"


# =========================================================
# استخراج الأسعار
# =========================================================

def get_prices_from_catalog(product):

    results = []

    sku_availabilities = product.get(
        "DisplaySkuAvailabilities",
        []
    )

    for sku_data in sku_availabilities:

        availabilities = sku_data.get(
            "Availabilities",
            []
        )

        for availability in availabilities:

            order_data = availability.get(
                "OrderManagementData",
                {}
            )

            price_data = order_data.get(
                "Price",
                {}
            )

            if not price_data:
                continue

            list_price = to_float(
                price_data.get(
                    "ListPrice"
                )
            )

            msrp = to_float(
                price_data.get(
                    "MSRP"
                )
            )

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

            if list_price is None:
                continue

            if list_price <= 0:
                continue

            conditions = availability.get(
                "Conditions",
                {}
            )

            end_date = conditions.get(
                "EndDate"
            )

            if (
                msrp is not None
                and msrp > list_price
            ):

                results.append(
                    (
                        list_price,
                        msrp,
                        end_date
                    )
                )

            else:

                results.append(
                    (
                        list_price,
                        None,
                        end_date
                    )
                )

    return results


# =========================================================
# اختيار أفضل سعر
# =========================================================

def determine_best_price(price_pairs):

    if not price_pairs:
        return None, None, None

    valid_pairs = []

    for item in price_pairs:

        if len(item) == 3:

            current, original, end_date = item

        else:

            current, original = item
            end_date = None

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

            if original <= current:

                original = None

            elif original > 50000:

                original = None

            else:

                discount = (
                    (original - current)
                    / original
                ) * 100

                if discount >= 99:

                    original = None

        valid_pairs.append(
            (
                current,
                original,
                end_date
            )
        )

    if not valid_pairs:
        return None, None, None

    discounted = []

    for current, original, end_date in valid_pairs:

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
            key=lambda item: item[0]
        )

        return discounted[0]

    prices = []

    for current, original, end_date in valid_pairs:

        prices.append(
            round(current, 2)
        )

    if not prices:
        return None, None, None

    counter = Counter(prices)

    best_price = counter.most_common(
        1
    )[0][0]

    return best_price, None, None


# =========================================================
# نسبة الخصم
# =========================================================

def calculate_discount(
    current_price,
    original_price
):

    if (
        current_price is None
        or original_price is None
        or original_price <= current_price
    ):
        return 0

    discount = (
        (original_price - current_price)
        / original_price
    ) * 100

    return int(
        round(discount)
    )


# =========================================================
# تحليل تاريخ Microsoft
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

    except Exception as error:

        print(
            "DATE PARSE ERROR:",
            end_date,
            repr(error)
        )

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

    now = datetime.now(
        timezone.utc
    )

    if dt.tzinfo is None:

        dt = dt.replace(
            tzinfo=timezone.utc
        )

    else:

        dt = dt.astimezone(
            timezone.utc
        )

    remaining = dt - now

    if remaining.total_seconds() <= 0:
        return None

    total_seconds = int(
        remaining.total_seconds()
    )

    days = (
        total_seconds // 86400
    )

    hours = (
        total_seconds % 86400
    ) // 3600

    minutes = (
        total_seconds % 3600
    ) // 60

    if days > 1:

        text = f"متبقي: {days} يوم"

        if hours > 0:
            text += f" و{hours} ساعة"

    elif days == 1:

        text = "متبقي: يوم واحد"

        if hours > 0:
            text += f" و{hours} ساعة"

    elif hours > 0:

        text = f"متبقي: {hours} ساعة"

        if minutes > 0:
            text += f" و{minutes} دقيقة"

    else:

        text = (
            f"متبقي: "
            f"{max(minutes, 1)} دقيقة"
        )

    return (
        text,
        dt.strftime("%Y-%m-%d"),
        dt.strftime("%H:%M")
    )


# =========================================================
# معلومات لعبة من رابط
# =========================================================

def get_game_info(url):

    product_id = get_product_id(
        url
    )

    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )

    product = get_product_data(
        product_id
    )

    game_name = get_game_name(
        product
    )

    price_pairs = get_prices_from_catalog(
        product
    )

    (
        current_price,
        original_price,
        end_date
    ) = determine_best_price(
        price_pairs
    )

    if current_price is None:

        raise Exception(
            "Microsoft لم يعثر على سعر اللعبة"
        )

    return (
        product_id,
        game_name,
        current_price,
        original_price,
        end_date
    )


# =========================================================
# تنسيق السعر
# =========================================================

def format_store_price(price):

    price = int(price)

    if price % 1000 == 0:

        return f"{price // 1000} ألف"

    return (
        f"{price:,} دينار"
        .replace(",", ".")
    )


# =========================================================
# رابط Xbox
# =========================================================

def build_xbox_url(product_id):

    return (
        "https://www.xbox.com/tr-tr/"
        "games/store/-/"
        + product_id.lower()
    )


# =========================================================
# حفظ آخر طلب
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
# جلب آخر طلب
# =========================================================

def get_last_request(
    user_id,
    product_id
):

    connection = sqlite3.connect(
        DB_FILE
    )

    cursor = connection.cursor()

    cursor.execute(
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
    )

    result = cursor.fetchone()

    connection.close()

    return result


# =========================================================
# هل التنبيه موجود؟
# =========================================================

def alert_exists(
    user_id,
    product_id
):

    connection = sqlite3.connect(
        DB_FILE
    )

    cursor = connection.cursor()

    cursor.execute(
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
    )

    result = cursor.fetchone()

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

    cursor = connection.cursor()

    cursor.execute(
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
    )

    existing = cursor.fetchone()

    if existing:

        connection.close()
        return False

    cursor.execute(
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
# إلغاء تنبيه
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
# جلب التنبيهات
# =========================================================

def get_active_alerts():

    connection = sqlite3.connect(
        DB_FILE
    )

    cursor = connection.cursor()

    cursor.execute(
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
    )

    rows = cursor.fetchall()

    connection.close()

    return rows


# =========================================================
# تعطيل تنبيه
# =========================================================

def deactivate_alert(
    alert_id
):

    connection = sqlite3.connect(
        DB_FILE
    )

    cursor = connection.cursor()

    cursor.execute(
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
# =========================================================
#              🔥 العروض القوية
# =========================================================
# =========================================================

STRONG_DEALS_CACHE = []

STRONG_DEALS_UPDATED_AT = None

STRONG_DEALS_LOCK = asyncio.Lock()


# =========================================================
# استخراج Product IDs من أي JSON
# =========================================================

def extract_product_ids(value):

    found = []

    def walk(obj):

        if isinstance(obj, dict):

            for key, val in obj.items():

                key_lower = str(
                    key
                ).lower()

                # مفاتيح نركز عليها أولاً
                if key_lower in (
                    "productid",
                    "product_id",
                    "product",
                    "bigid",
                    "big_id",
                    "storeid",
                    "store_id",
                    "id"
                ):

                    if isinstance(
                        val,
                        str
                    ):

                        candidate = val.strip()

                        if re.fullmatch(
                            r"[A-Za-z0-9]{12}",
                            candidate
                        ):

                            found.append(
                                candidate.upper()
                            )

                walk(val)

        elif isinstance(obj, list):

            for item in obj:
                walk(item)

        elif isinstance(obj, str):

            candidate = obj.strip()

            if re.fullmatch(
                r"[A-Za-z0-9]{12}",
                candidate
            ):

                found.append(
                    candidate.upper()
                )

    walk(value)

    # إزالة التكرار
    unique = []

    seen = set()

    for product_id in found:

        if product_id in seen:
            continue

        seen.add(
            product_id
        )

        unique.append(
            product_id
        )

    return unique


# =========================================================
# جلب قائمة العروض من Microsoft
# =========================================================

def get_deal_product_ids():

    # Microsoft لديه أكثر من صيغة مستخدمة
    # حسب نسخة Recommendations API.
    endpoints = [

        (
            "https://reco-public.rec.mp.microsoft.com/"
            "channels/Reco/V8.0/Lists/Computed/Deal"
        ),

        (
            "https://reco-public.rec.mp.microsoft.com/"
            "channels/Reco/V8.0/Lists/api/list/"
            "Computed/Deal"
        )
    ]

    params = {
        "Market": "TR",
        "Language": "tr-TR",
        "ItemTypes": "Game",
        "itemType": "Game",
        "deviceFamily": "Windows.Xbox",
        "count": str(DEALS_FETCH_COUNT),
        "skipItems": "0"
    }

    last_error = None

    for endpoint in endpoints:

        try:

            print(
                "🔥 محاولة جلب العروض من:",
                endpoint
            )

            response = SESSION.get(
                endpoint,
                params=params,
                timeout=30
            )

            print(
                "🔥 Deal API status:",
                response.status_code
            )

            response.raise_for_status()

            data = response.json()

            ids = extract_product_ids(
                data
            )

            print(
                "🔥 Product IDs found:",
                len(ids)
            )

            if ids:

                return ids[
                    :DEALS_FETCH_COUNT
                ]

        except Exception as error:

            last_error = error

            print(
                "DEAL ENDPOINT ERROR:",
                repr(error)
            )

    if last_error:

        raise last_error

    return []


# =========================================================
# فحص منتج لمعرفة إذا عليه تخفيض قوي
# =========================================================

def inspect_deal_product(
    product
):

    try:

        # Product ID
        product_id = (
            product.get("ProductId")
            or product.get("Id")
            or product.get("ProductID")
        )

        if not product_id:

            return None

        product_id = str(
            product_id
        ).upper()

        if not re.fullmatch(
            r"[A-Za-z0-9]{12}",
            product_id
        ):

            return None

        game_name = get_game_name(
            product
        )

        price_pairs = get_prices_from_catalog(
            product
        )

        (
            current_price,
            original_price,
            end_date
        ) = determine_best_price(
            price_pairs
        )

        if (
            current_price is None
            or original_price is None
        ):

            return None

        discount = calculate_discount(
            current_price,
            original_price
        )

        if discount < STRONG_DEAL_MIN_DISCOUNT:
            return None

        iraqi_price = calculate_price(
            current_price
        )

        original_iraqi_price = calculate_price(
            original_price
        )

        return {
            "product_id": product_id,
            "game_name": game_name,
            "current_price": current_price,
            "original_price": original_price,
            "discount": discount,
            "iraqi_price": iraqi_price,
            "original_iraqi_price": original_iraqi_price,
            "end_date": end_date,
            "url": build_xbox_url(
                product_id
            )
        }

    except Exception as error:

        print(
            "DEAL PRODUCT ERROR:",
            repr(error)
        )

        return None


# =========================================================
# تحديث العروض القوية
# =========================================================

def refresh_strong_deals():

    global STRONG_DEALS_CACHE
    global STRONG_DEALS_UPDATED_AT

    print(
        "======================================"
    )

    print(
        "🔥 بدء تحديث العروض القوية..."
    )

    try:

        product_ids = get_deal_product_ids()

        print(
            "🔥 عدد IDs المستلمة:",
            len(product_ids)
        )

        if not product_ids:

            print(
                "⚠️ Microsoft رجع قائمة فارغة"
            )

            return False

        deals = []

        # =================================================
        # نقسم IDs إلى دفعات
        # =================================================

        batch_size = 25

        for start in range(
            0,
            len(product_ids),
            batch_size
        ):

            batch = product_ids[
                start:start + batch_size
            ]

            try:

                products = get_products_data(
                    batch
                )

                print(
                    "🔥 Batch:",
                    start,
                    "Products:",
                    len(products)
                )

                for product in products:

                    deal = inspect_deal_product(
                        product
                    )

                    if deal:

                        deals.append(
                            deal
                        )

            except Exception as error:

                print(
                    "BATCH ERROR:",
                    repr(error)
                )

            time.sleep(
                0.2
            )

        # =================================================
        # إزالة التكرار
        # =================================================

        unique_deals = []

        seen = set()

        for deal in deals:

            product_id = deal[
                "product_id"
            ]

            if product_id in seen:
                continue

            seen.add(
                product_id
            )

            unique_deals.append(
                deal
            )

        # =================================================
        # ترتيب الخصم
        # =================================================

        unique_deals.sort(
            key=lambda item: (
                -item["discount"],
                item["iraqi_price"]
            )
        )

        # =================================================
        # مهم:
        # إذا فشل التحديث ولم نجد شيء
        # لا نمسح الكاش القديم
        # =================================================

        if not unique_deals:

            print(
                "⚠️ لم نجد عروض قوية."
            )

            print(
                "⚠️ سيتم الاحتفاظ بالعروض القديمة."
            )

            return False

        STRONG_DEALS_CACHE = (
            unique_deals[:30]
        )

        STRONG_DEALS_UPDATED_AT = (
            datetime.now(
                timezone.utc
            )
        )

        print(
            "✅ Strong deals:",
            len(STRONG_DEALS_CACHE)
        )

        print(
            "======================================"
        )

        return True

    except Exception as error:

        print(
            "❌ STRONG DEALS UPDATE ERROR:",
            repr(error)
        )

        print(
            "⚠️ العروض القديمة بقيت محفوظة."
        )

        return False


# =========================================================
# حلقة تحديث العروض
# =========================================================

async def strong_deals_loop():

    # أول تحديث بعد تشغيل البوت بـ10 ثواني
    await asyncio.sleep(
        10
    )

    while True:

        try:

            async with STRONG_DEALS_LOCK:

                await asyncio.to_thread(
                    refresh_strong_deals
                )

        except Exception as error:

            print(
                "STRONG DEAL LOOP ERROR:",
                repr(error)
            )

        # كل 30 دقيقة
        await asyncio.sleep(
            DEALS_UPDATE_SECONDS
        )


# =========================================================
# آخر تحديث
# =========================================================

def get_deals_update_text():

    if not STRONG_DEALS_UPDATED_AT:

        return "لم يتم التحديث بعد"

    return STRONG_DEALS_UPDATED_AT.strftime(
        "%Y-%m-%d %H:%M"
    )


# =========================================================
# رسالة العروض
# =========================================================

def build_strong_deals_message():

    if not STRONG_DEALS_CACHE:

        return (
            "🔥 <b>العروض القوية</b>\n\n"
            "حالياً ماكو عروض قوية متاحة.\n\n"
            "🔄 يتم تحديث القسم تلقائياً كل 30 دقيقة."
        )

    lines = [
        "🔥 <b>العروض القوية</b>",
        "",
        f"📉 تخفيض {STRONG_DEAL_MIN_DISCOUNT}% أو أكثر",
        ""
    ]

    for index, deal in enumerate(
        STRONG_DEALS_CACHE,
        start=1
    ):

        name = deal[
            "game_name"
        ]

        discount = deal[
            "discount"
        ]

        price = format_store_price(
            deal["iraqi_price"]
        )

        old_price = format_store_price(
            deal["original_iraqi_price"]
        )

        lines.append(
            f"<b>{index}. {name}</b>"
        )

        lines.append(
            f"🔥 الخصم: {discount}%"
        )

        lines.append(
            f"💰 السعر: {price} 🇮🇶"
        )

        lines.append(
            f"💵 قبل الخصم: {old_price} 🇮🇶"
        )

        remaining = get_remaining_text(
            deal.get("end_date")
        )

        if remaining:

            (
                remaining_text,
                date_text,
                time_text
            ) = remaining

            lines.append(
                f"⏳ {remaining_text}"
            )

            lines.append(
                f"📅 ينتهي: "
                f"{date_text} الساعة {time_text}"
            )

        lines.append("")

    lines.append(
        f"🔄 آخر تحديث: "
        f"{get_deals_update_text()}"
    )

    return "\n".join(
        lines
    )


# =========================================================
# أزرار العروض
# =========================================================

def build_deals_keyboard():

    buttons = []

    for index, deal in enumerate(
        STRONG_DEALS_CACHE[:10]
    ):

        product_id = deal[
            "product_id"
        ]

        name = deal[
            "game_name"
        ]

        short_name = name[:32]

        buttons.append([
            InlineKeyboardButton(
                f"🛒 {index + 1}. {short_name}",
                callback_data=(
                    f"deal:{product_id}"
                )
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔄 تحديث العروض",
            callback_data="refresh_deals"
        )
    ])

    buttons.append([
        InlineKeyboardButton(
            "📩 تواصل مع @Sijadsa",
            url=ORDER_URL
        )
    ])

    return InlineKeyboardMarkup(
        buttons
    )


# =========================================================
# /deals
# =========================================================

async def strong_deals(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = await update.message.reply_text(
        "⏳ جاري جلب العروض القوية..."
    )

    if not STRONG_DEALS_CACHE:

        await asyncio.to_thread(
            refresh_strong_deals
        )

    text = build_strong_deals_message()

    await message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=build_deals_keyboard()
    )


# =========================================================
# فحص تنبيهات الأسعار
# =========================================================

async def check_price_alerts(
    application
):

    alerts = get_active_alerts()

    print(
        "🔔 فحص التنبيهات:",
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
            old_price
        ) = alert

        try:

            (
                current_product_id,
                current_game_name,
                current_price_try,
                original_price_try,
                end_date
            ) = await asyncio.to_thread(
                get_game_info,
                url
            )

            new_price = calculate_price(
                current_price_try
            )

            if new_price < old_price:

                old_price_text = format_store_price(
                    old_price
                )

                new_price_text = format_store_price(
                    new_price
                )

                text = (
                    "🔔 <b>تنبيه انخفاض السعر!</b>\n\n"
                    f"🎮 {current_game_name}\n\n"
                    f"💰 السعر السابق: "
                    f"{old_price_text} 🇮🇶\n"
                    f"🔥 السعر الجديد: "
                    f"{new_price_text} 🇮🇶\n\n"
                    "السعر نزل، تگدر تطلب اللعبة هسه."
                )

                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🛒 اطلب الآن",
                            url=ORDER_URL
                        )
                    ]
                ])

                try:

                    await application.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=keyboard
                    )

                except Exception as error:

                    print(
                        "SEND ALERT ERROR:",
                        repr(error)
                    )

                deactivate_alert(
                    alert_id
                )

        except Exception as error:

            print(
                "ALERT CHECK ERROR:",
                product_id,
                repr(error)
            )


# =========================================================
# حلقة التنبيهات
# =========================================================

async def alert_loop(
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

        except Exception as error:

            print(
                "ALERT LOOP ERROR:",
                repr(error)
            )

        await asyncio.sleep(
            3600
        )


# =========================================================
# /start
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔥 العروض القوية",
                callback_data="show_deals"
            )
        ],
        [
            InlineKeyboardButton(
                "📩 تواصل مع @Sijadsa",
                url=ORDER_URL
            )
        ]
    ])

    await update.message.reply_text(
        "يرجى إرسال رابط اللعبة\n\n"
        "أو اضغط على 🔥 العروض القوية "
        "لمشاهدة التخفيضات القوية.",
        reply_markup=keyboard
    )


# =========================================================
# /id
# =========================================================

async def my_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🆔 Telegram ID الخاص بك:\n"
        f"{update.effective_user.id}"
    )


# =========================================================
# معالجة رابط اللعبة
# =========================================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    url = (
        update.message.text
        or ""
    ).strip()

    if (
        "xbox.com" not in url.lower()
        or not get_product_id(url)
    ):

        await update.message.reply_text(
            "يرجى إرسال رابط لعبة من Xbox Store"
        )

        return

    processing_message = (
        await update.message.reply_text(
            "⏳ جاري جلب معلومات اللعبة..."
        )
    )

    try:

        (
            product_id,
            game_name,
            current_price_try,
            original_price_try,
            end_date
        ) = await asyncio.to_thread(
            get_game_info,
            url
        )

        iraqi_price = calculate_price(
            current_price_try
        )

        store_price_text = format_store_price(
            iraqi_price
        )

        save_last_request(
            update.effective_user.id,
            product_id,
            game_name,
            url,
            iraqi_price
        )

        # =================================================
        # إذا عليها تخفيض
        # =================================================

        if (
            original_price_try is not None
            and original_price_try > current_price_try
        ):

            discount_percent = calculate_discount(
                current_price_try,
                original_price_try
            )

            lines = [
                f"🎮 {game_name}",
                "",
                "🔥 اللعبة عليها تخفيض!",
                "",
                f"📉 نسبة الخصم: {discount_percent}%"
            ]

            remaining = get_remaining_text(
                end_date
            )

            if remaining:

                (
                    remaining_text,
                    date_text,
                    time_text
                ) = remaining

                lines.append(
                    f"⏳ {remaining_text}"
                )

                lines.append(
                    f"📅 ينتهي التخفيض: "
                    f"{date_text} الساعة {time_text}"
                )

            lines.extend([
                "",
                f"💰 سعر اللعبة: "
                f"{store_price_text} 🇮🇶"
            ])

            result = "\n".join(
                lines
            )

        else:

            result = (
                f"🎮 {game_name}\n\n"
                f"💰 سعر اللعبة: "
                f"{store_price_text} 🇮🇶"
            )

        # =================================================
        # زر التنبيه
        # =================================================

        if alert_exists(
            update.effective_user.id,
            product_id
        ):

            alert_button = InlineKeyboardButton(
                "🔕 إلغاء التنبيه",
                callback_data=(
                    f"cancel:{product_id}"
                )
            )

        else:

            alert_button = InlineKeyboardButton(
                "🔔 نبهني إذا نزل السعر",
                callback_data=(
                    f"alert:{product_id}"
                )
            )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🛒 اطلب الآن",
                    callback_data=(
                        f"order:{product_id}"
                    )
                )
            ],
            [
                alert_button
            ],
            [
                InlineKeyboardButton(
                    "🔥 العروض القوية",
                    callback_data="show_deals"
                )
            ]
        ])

        await processing_message.edit_text(
            result,
            reply_markup=keyboard
        )

    except Exception as error:

        print(
            "GAME ERROR:",
            repr(error)
        )

        await processing_message.edit_text(
            "❌ حدث خطأ أثناء جلب معلومات اللعبة.\n"
            "تأكد من أن الرابط صحيح وحاول مرة أخرى."
        )


# =========================================================
# التعامل مع الأزرار
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    data = query.data

    # =====================================================
    # عرض العروض
    # =====================================================

    if data == "show_deals":

        await query.edit_message_text(
            "⏳ جاري فتح العروض القوية..."
        )

        if not STRONG_DEALS_CACHE:

            await asyncio.to_thread(
                refresh_strong_deals
            )

        text = build_strong_deals_message()

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=build_deals_keyboard()
        )

        return

    # =====================================================
    # تحديث يدوي
    # =====================================================

    if data == "refresh_deals":

        await query.edit_message_text(
            "⏳ جاري تحديث العروض..."
        )

        async with STRONG_DEALS_LOCK:

            await asyncio.to_thread(
                refresh_strong_deals
            )

        text = build_strong_deals_message()

        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=build_deals_keyboard()
        )

        return

    # =====================================================
    # فتح لعبة من العروض
    # =====================================================

    if data.startswith("deal:"):

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
                "العرض غير متوفر حالياً",
                show_alert=True
            )

            return

        game_name = deal[
            "game_name"
        ]

        discount = deal[
            "discount"
        ]

        price_text = format_store_price(
            deal["iraqi_price"]
        )

        original_price_text = format_store_price(
            deal["original_iraqi_price"]
        )

        lines = [
            f"🎮 <b>{game_name}</b>",
            "",
            f"🔥 الخصم: {discount}%",
            "",
            f"💰 السعر: {price_text} 🇮🇶",
            f"💵 قبل الخصم: {original_price_text} 🇮🇶"
        ]

        remaining = get_remaining_text(
            deal.get("end_date")
        )

        if remaining:

            (
                remaining_text,
                date_text,
                time_text
            ) = remaining

            lines.extend([
                "",
                f"⏳ {remaining_text}",
                f"📅 ينتهي: "
                f"{date_text} الساعة {time_text}"
            ])

        if alert_exists(
            update.effective_user.id,
            product_id
        ):

            alert_button = InlineKeyboardButton(
                "🔕 إلغاء التنبيه",
                callback_data=(
                    f"cancel:{product_id}"
                )
            )

        else:

            alert_button = InlineKeyboardButton(
                "🔔 نبهني إذا نزل السعر",
                callback_data=(
                    f"alert:{product_id}"
                )
            )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🛒 اطلب الآن",
                    callback_data=(
                        f"order:{product_id}"
                    )
                )
            ],
            [
                alert_button
            ],
            [
                InlineKeyboardButton(
                    "🔙 رجوع للعروض",
                    callback_data="show_deals"
                )
            ]
        ])

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=keyboard
        )

        return

    # =====================================================
    # طلب
    # =====================================================

    if data.startswith("order:"):

        product_id = data.split(
            ":",
            1
        )[1]

        last_request = get_last_request(
            update.effective_user.id,
            product_id
        )

        # إذا جاء الطلب من قسم العروض
        if not last_request:

            deal = None

            for item in STRONG_DEALS_CACHE:

                if item["product_id"] == product_id:

                    deal = item
                    break

            if deal:

                save_last_request(
                    update.effective_user.id,
                    product_id,
                    deal["game_name"],
                    deal["url"],
                    deal["iraqi_price"]
                )

                last_request = (
                    deal["game_name"],
                    deal["url"],
                    deal["iraqi_price"]
                )

        if not last_request:

            await query.answer(
                "اضغط على اللعبة من جديد",
                show_alert=True
            )

            return

        (
            game_name,
            url,
            current_price
        ) = last_request

        user = update.effective_user

        username = (
            f"@{user.username}"
            if user.username
            else "بدون Username"
        )

        full_name = (
            user.full_name
            or "بدون اسم"
        )

        price_text = format_store_price(
            current_price
        )

        # =================================================
        # إرسال الطلب للمالك
        # =================================================

        if ADMIN_CHAT_ID:

            admin_text = (
                "🛒 <b>طلب جديد!</b>\n\n"
                f"🎮 اللعبة: {game_name}\n"
                f"💰 السعر: {price_text} 🇮🇶\n\n"
                f"👤 العميل: {full_name}\n"
                f"📱 Username: {username}\n"
                f"🆔 ID: {user.id}\n\n"
                f"🔗 الرابط:\n{url}"
            )

            try:

                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=admin_text,
                    parse_mode="HTML"
                )

            except Exception as error:

                print(
                    "ADMIN ORDER ERROR:",
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

        await query.edit_message_text(
            "✅ تم إرسال طلبك بنجاح!\n\n"
            f"🎮 {game_name}\n"
            f"💰 السعر: {price_text} 🇮🇶\n\n"
            "تواصل مع صاحب المتجر لإكمال الطلب.",
            reply_markup=customer_keyboard
        )

        return

    # =====================================================
    # إضافة تنبيه
    # =====================================================

    if data.startswith("alert:"):

        product_id = data.split(
            ":",
            1
        )[1]

        last_request = get_last_request(
            update.effective_user.id,
            product_id
        )

        if not last_request:

            for deal in STRONG_DEALS_CACHE:

                if deal["product_id"] == product_id:

                    save_last_request(
                        update.effective_user.id,
                        product_id,
                        deal["game_name"],
                        deal["url"],
                        deal["iraqi_price"]
                    )

                    last_request = (
                        deal["game_name"],
                        deal["url"],
                        deal["iraqi_price"]
                    )

                    break

        if not last_request:

            await query.answer(
                "اضغط على اللعبة من جديد",
                show_alert=True
            )

            return

        (
            game_name,
            url,
            current_price
        ) = last_request

        added = add_alert(
            update.effective_user.id,
            update.effective_chat.id,
            product_id,
            game_name,
            url,
            current_price
        )

        if added:

            await query.answer(
                "🔔 تم تفعيل التنبيه",
                show_alert=True
            )

            keyboard = InlineKeyboardMarkup([
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
                ],
                [
                    InlineKeyboardButton(
                        "🔥 العروض القوية",
                        callback_data="show_deals"
                    )
                ]
            ])

            try:

                await query.edit_message_reply_markup(
                    reply_markup=keyboard
                )

            except Exception as error:

                print(
                    "EDIT ALERT ERROR:",
                    repr(error)
                )

        else:

            await query.answer(
                "🔔 التنبيه مفعّل مسبقاً",
                show_alert=True
            )

        return

    # =====================================================
    # إلغاء التنبيه
    # =====================================================

    if data.startswith("cancel:"):

        product_id = data.split(
            ":",
            1
        )[1]

        cancelled = cancel_alert(
            update.effective_user.id,
            product_id
        )

        if cancelled:

            await query.answer(
                "🔕 تم إلغاء التنبيه",
                show_alert=True
            )

            keyboard = InlineKeyboardMarkup([
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
                ],
                [
                    InlineKeyboardButton(
                        "🔥 العروض القوية",
                        callback_data="show_deals"
                    )
                ]
            ])

            try:

                await query.edit_message_reply_markup(
                    reply_markup=keyboard
                )

            except Exception as error:

                print(
                    "EDIT CANCEL ERROR:",
                    repr(error)
                )

        else:

            await query.answer(
                "ماكو تنبيه فعال",
                show_alert=True
            )

        return


# =========================================================
# تشغيل المهام الخلفية
# =========================================================

async def post_init(
    application
):

    init_database()

    # تنبيهات انخفاض السعر
    application.create_task(
        alert_loop(
            application
        )
    )

    # العروض القوية كل 30 دقيقة
    application.create_task(
        strong_deals_loop()
    )

    print(
        "✅ Database ready"
    )

    print(
        "🔔 Price Alert Loop started"
    )

    print(
        "🔥 Strong Deals Loop started"
    )


# =========================================================
# Main
# =========================================================

def main():

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # =====================================================
    # Commands
    # =====================================================

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
            "deals",
            strong_deals
        )
    )

    # =====================================================
    # Buttons
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # =====================================================
    # Text messages
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_link
        )
    )

    print(
        "🤖 SA STORE BOT STARTED"
    )

    application.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
