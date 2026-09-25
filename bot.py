import os
import re
import math
import asyncio
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

# نسبة الخصم المطلوبة حتى تظهر اللعبة في "العروض القوية"
STRONG_DEAL_MIN_DISCOUNT = 50

# عدد الألعاب التي يتم فحصها من قائمة عروض Xbox
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

    extra_steps = math.ceil(
        extra / 100
    )

    return 33000 + (
        extra_steps * 3000
    )


# =========================================================
# استخراج Product ID من رابط
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
# جلب بيانات لعبة من Microsoft
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

    if not products:

        product = data.get(
            "Product"
        )

        if product:
            return product

        raise Exception(
            "Microsoft لم يعثر على اللعبة"
        )

    return products[0]


# =========================================================
# استخراج اسم اللعبة
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
# استخراج الأسعار + تاريخ نهاية التخفيض
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
# حساب نسبة الخصم
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

    return int(round(discount))


# =========================================================
# تحويل تاريخ Microsoft إلى datetime
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

        remaining_text = (
            f"متبقي: {days} يوم"
        )

        if hours > 0:

            remaining_text += (
                f" و{hours} ساعة"
            )

    elif days == 1:

        remaining_text = (
            "متبقي: يوم واحد"
        )

        if hours > 0:

            remaining_text += (
                f" و{hours} ساعة"
            )

    elif hours > 0:

        remaining_text = (
            f"متبقي: {hours} ساعة"
        )

        if minutes > 0:

            remaining_text += (
                f" و{minutes} دقيقة"
            )

    else:

        remaining_text = (
            f"متبقي: {max(minutes, 1)} دقيقة"
        )

    date_text = dt.strftime(
        "%Y-%m-%d"
    )

    time_text = dt.strftime(
        "%H:%M"
    )

    return (
        remaining_text,
        date_text,
        time_text
    )


# =========================================================
# معلومات اللعبة
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
# تنسيق السعر العراقي
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
# رابط Xbox للعبة
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
# جلب آخر لعبة
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
# هل يوجد تنبيه؟
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
# إيقاف التنبيه
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
#                 🔥 العروض القوية
# =========================================================
# =========================================================


STRONG_DEALS_CACHE = []

STRONG_DEALS_UPDATED_AT = None

STRONG_DEALS_LOCK = asyncio.Lock()


# =========================================================
# جلب قائمة Product IDs الخاصة بالعروض
# =========================================================

def get_deal_product_ids():

    url = (
        "https://reco-public.rec.mp.microsoft.com/"
        "channels/Reco/V8.0/Lists/api/list/"
        "Computed/Deal"
    )

    params = {
        "market": "TR",
        "language": "tr-TR",
        "itemType": "Game",
        "deviceFamily": "Windows.Xbox",
        "count": DEALS_FETCH_COUNT,
        "skipItems": 0
    }

    response = SESSION.get(
        url,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    ids = []

    # =====================================================
    # محاولة استخراج العناصر من أكثر من شكل محتمل
    # =====================================================

    possible_lists = []

    if isinstance(data, list):
        possible_lists.append(data)

    for key in (
        "Items",
        "items",
        "Products",
        "products",
        "Results",
        "results",
        "Recommendations",
        "recommendations"
    ):

        value = data.get(key)

        if isinstance(value, list):

            possible_lists.append(
                value
            )

    # =====================================================
    # استخراج IDs
    # =====================================================

    for items in possible_lists:

        for item in items:

            if isinstance(item, str):

                value = item.strip()

                if re.fullmatch(
                    r"[A-Za-z0-9]{12}",
                    value
                ):

                    ids.append(
                        value.upper()
                    )

                continue

            if not isinstance(
                item,
                dict
            ):
                continue

            candidates = [
                item.get("Id"),
                item.get("ID"),
                item.get("id"),
                item.get("ProductId"),
                item.get("ProductID"),
                item.get("productId"),
                item.get("BigId"),
                item.get("BigID"),
                item.get("bigId"),
                item.get("StoreId"),
                item.get("storeId")
            ]

            for candidate in candidates:

                if not candidate:
                    continue

                value = str(
                    candidate
                ).strip()

                if re.fullmatch(
                    r"[A-Za-z0-9]{12}",
                    value
                ):

                    ids.append(
                        value.upper()
                    )

                    break

    # =====================================================
    # إزالة التكرار
    # =====================================================

    unique_ids = []

    seen = set()

    for product_id in ids:

        if product_id in seen:
            continue

        seen.add(
            product_id
        )

        unique_ids.append(
            product_id
        )

    return unique_ids


# =========================================================
# فحص لعبة للعروض القوية
# =========================================================

def inspect_deal_product(
    product_id
):

    try:

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

        # لا نريد أسعار غير منطقية
        if iraqi_price <= 0:
            return None

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
            product_id,
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
        "🔥 بدء تحديث العروض القوية..."
    )

    try:

        product_ids = get_deal_product_ids()

        print(
            "🔥 عدد معرفات العروض:",
            len(product_ids)
        )

        deals = []

        # =================================================
        # فحص عدد محدود حتى لا نضغط على Microsoft
        # =================================================

        for index, product_id in enumerate(
            product_ids[:DEALS_FETCH_COUNT],
            start=1
        ):

            deal = inspect_deal_product(
                product_id
            )

            if deal:

                deals.append(
                    deal
                )

            # فاصل بسيط
            if index % 10 == 0:

                time_to_wait = 0.2

                # هذه الدالة synchronous
                # لذلك نستخدم sleep صغير
                import time

                time.sleep(
                    time_to_wait
                )

        # =================================================
        # ترتيب حسب نسبة الخصم
        # =================================================

        deals.sort(
            key=lambda item: (
                -item["discount"],
                item["iraqi_price"]
            )
        )

        # =================================================
        # نخلي أول 30 عرض فقط
        # =================================================

        STRONG_DEALS_CACHE = deals[:30]

        STRONG_DEALS_UPDATED_AT = (
            datetime.now(
                timezone.utc
            )
        )

        print(
            "🔥 العروض القوية:",
            len(STRONG_DEALS_CACHE)
        )

        return True

    except Exception as error:

        print(
            "STRONG DEALS UPDATE ERROR:",
            repr(error)
        )

        return False


# =========================================================
# تشغيل تحديث العروض بالخلفية
# =========================================================

async def strong_deals_loop():

    await asyncio.sleep(
        10
    )

    while True:

        try:

            async with STRONG_DEALS_LOCK:

                # requests مكتوبة بشكل synchronous
                # لذلك نشغلها خارج event loop
                await asyncio.to_thread(
                    refresh_strong_deals
                )

        except Exception as error:

            print(
                "STRONG DEAL LOOP ERROR:",
                repr(error)
            )

        await asyncio.sleep(
            DEALS_UPDATE_SECONDS
        )


# =========================================================
# تنسيق وقت تحديث العروض
# =========================================================

def get_deals_update_text():

    if not STRONG_DEALS_UPDATED_AT:
        return "لم يتم التحديث بعد"

    value = STRONG_DEALS_UPDATED_AT.strftime(
        "%Y-%m-%d %H:%M"
    )

    return value


# =========================================================
# رسالة العروض القوية
# =========================================================

def build_strong_deals_message():

    if not STRONG_DEALS_CACHE:

        return (
            "🔥 العروض القوية\n\n"
            "حالياً ماكو عروض قوية متاحة.\n\n"
            "🔄 يتم تحديث القسم تلقائياً كل 30 دقيقة."
        )

    lines = []

    lines.append(
        "🔥 <b>العروض القوية</b>"
    )

    lines.append(
        f"📉 تخفيض {STRONG_DEAL_MIN_DISCOUNT}% أو أكثر"
    )

    lines.append("")

    for index, deal in enumerate(
        STRONG_DEALS_CACHE,
        start=1
    ):

        game_name = deal[
            "game_name"
        ]

        discount = deal[
            "discount"
        ]

        iraqi_price = format_store_price(
            deal["iraqi_price"]
        )

        original_iraqi_price = format_store_price(
            deal["original_iraqi_price"]
        )

        lines.append(
            f"<b>{index}. {game_name}</b>"
        )

        lines.append(
            f"🔥 الخصم: {discount}%"
        )

        lines.append(
            f"💰 السعر: {iraqi_price} 🇮🇶"
        )

        lines.append(
            f"💵 قبل الخصم: {original_iraqi_price} 🇮🇶"
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
                f"📅 ينتهي: {date_text} الساعة {time_text}"
            )

        lines.append("")

    lines.append(
        "🔄 آخر تحديث: "
        + get_deals_update_text()
    )

    return "\n".join(
        lines
    )


# =========================================================
# أزرار العروض القوية
# =========================================================

def build_deals_keyboard():

    buttons = []

    for index, deal in enumerate(
        STRONG_DEALS_CACHE[:10]
    ):

        product_id = deal[
            "product_id"
        ]

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🛒 {index + 1}. "
                    f"{deal['game_name'][:35]}",
                    callback_data=(
                        f"deal:{product_id}"
                    )
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "🔄 تحديث العروض",
                callback_data="refresh_deals"
            )
        ]
    )

    buttons.append(
        [
            InlineKeyboardButton(
                "📩 تواصل مع @Sijadsa",
                url=ORDER_URL
            )
        ]
    )

    return InlineKeyboardMarkup(
        buttons
    )


# =========================================================
# أمر العروض
# =========================================================

async def strong_deals(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = await update.message.reply_text(
        "⏳ جاري فتح العروض القوية..."
    )

    # إذا لم يتم تحديثها بعد
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
        f"🆔 Telegram ID الخاص بك:\n"
        f"{update.effective_user.id}"
    )


# =========================================================
# التعامل مع رابط اللعبة
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
        # التخفيض
        # =================================================

        if (
            original_price_try is not None
            and original_price_try
            > current_price_try
        ):

            discount_percent = calculate_discount(
                current_price_try,
                original_price_try
            )

            result_lines = [
                f"🎮 {game_name}",
                "",
                "🔥 اللعبة عليها تخفيض!",
                "",
                f"📉 نسبة الخصم: {discount_percent}%",
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

                result_lines.append(
                    f"⏳ {remaining_text}"
                )

                result_lines.append(
                    f"📅 ينتهي التخفيض: "
                    f"{date_text} الساعة {time_text}"
                )

            result_lines.extend([
                "",
                f"💰 سعر اللعبة: "
                f"{store_price_text} 🇮🇶"
            ])

            result = "\n".join(
                result_lines
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
    # تحديث العروض يدويًا
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
    # اختيار لعبة من العروض
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

        lines.extend([
            "",
            "👇 للطلب أو تفعيل التنبيه:"
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
    # زر الطلب
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

        # إذا ما موجود بآخر الطلبات
        # نحاول البحث داخل العروض
        if not last_request:

            deal = None

            for item in STRONG_DEALS_CACHE:

                if item["product_id"] == product_id:

                    deal = item
                    break

            if deal:

                game_name = deal[
                    "game_name"
                ]

                url = deal[
                    "url"
                ]

                iraqi_price = deal[
                    "iraqi_price"
                ]

                save_last_request(
                    update.effective_user.id,
                    product_id,
                    game_name,
                    url,
                    iraqi_price
                )

                last_request = (
                    game_name,
                    url,
                    iraqi_price
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

        user = (
            update.effective_user
        )

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

        # إذا كانت اللعبة من العروض
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

            new_keyboard = []

            # نحافظ على زر الطلب
            new_keyboard.append([
                InlineKeyboardButton(
                    "🛒 اطلب الآن",
                    callback_data=(
                        f"order:{product_id}"
                    )
                )
            ])

            new_keyboard.append([
                InlineKeyboardButton(
                    "🔕 إلغاء التنبيه",
                    callback_data=(
                        f"cancel:{product_id}"
                    )
                )
            ])

            new_keyboard.append([
                InlineKeyboardButton(
                    "🔥 العروض القوية",
                    callback_data="show_deals"
                )
            ])

            try:

                await query.edit_message_reply_markup(
                    reply_markup=InlineKeyboardMarkup(
                        new_keyboard
                    )
                )

            except Exception as error:

                print(
                    "EDIT ALERT BUTTON ERROR:",
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

            new_keyboard = InlineKeyboardMarkup([
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
                    reply_markup=new_keyboard
                )

            except Exception as error:

                print(
                    "EDIT CANCEL BUTTON ERROR:",
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

    # =====================================================
    # حلقة تنبيهات الأسعار
    # =====================================================

    application.create_task(
        alert_loop(
            application
        )
    )

    # =====================================================
    # حلقة تحديث العروض كل 30 دقيقة
    # =====================================================

    application.create_task(
        strong_deals_loop()
    )

    print(
        "✅ قاعدة البيانات جاهزة"
    )

    print(
        "✅ Price Alert Loop started"
    )

    print(
        "🔥 Strong Deals Loop started"
    )


# =========================================================
# تشغيل البوت
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
    # الأوامر
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
    # الأزرار
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # =====================================================
    # الرسائل النصية
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
