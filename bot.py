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
# جلب بيانات اللعبة من Microsoft
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

    product = data.get(
        "Product"
    )

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
# اختيار السعر الصحيح
# =========================================================

def determine_best_price(price_pairs):

    if not price_pairs:
        return None, None, None

    valid_pairs = []

    for item in price_pairs:

        current, original, end_date = item

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

    best_price = counter.most_common(1)[0][0]

    return best_price, None, None


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

    days = total_seconds // 86400

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
# معلومات اللعبة من Product ID
# =========================================================

def get_game_info_by_product_id(product_id):

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

def extract_product_ids(value):

    ids = []

    if isinstance(value, dict):

        for key, item in value.items():

            key_lower = str(
                key
            ).lower()

            if key_lower in (
                "bigid",
                "productid",
                "product_id",
                "productfamilyid",
                "productfamily_id"
            ):

                if isinstance(
                    item,
                    str
                ):

                    ids.extend(
                        re.findall(
                            r"(?<![A-Za-z0-9])"
                            r"([A-Za-z0-9]{12})"
                            r"(?![A-Za-z0-9])",
                            item
                        )
                    )

            ids.extend(
                extract_product_ids(
                    item
                )
            )

    elif isinstance(value, list):

        for item in value:

            ids.extend(
                extract_product_ids(
                    item
                )
            )

    elif isinstance(value, str):

        ids.extend(
            re.findall(
                r"(?<![A-Za-z0-9])"
                r"([A-Za-z0-9]{12})"
                r"(?![A-Za-z0-9])",
                value
            )
        )

    return list(
        dict.fromkeys(
            x.upper()
            for x in ids
        )
    )


# =========================================================
# تنظيف نص البحث
# =========================================================

def normalize_search_text(text):

    text = str(
        text
    ).lower().strip()

    text = re.sub(
        r"[^a-z0-9\u0600-\u06ff]+",
        " ",
        text
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


# =========================================================
# البحث في Xbox
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
        "platformdependencyname": "Xbox",
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

    product_ids = extract_product_ids(
        data
    )

    if not product_ids:
        return []

    query_normalized = normalize_search_text(
        query
    )

    query_words = set(
        query_normalized.split()
    )

    results = []

    for product_id in product_ids[:10]:

        try:

            product = get_product_data(
                product_id
            )

            name = get_game_name(
                product
            )

            name_normalized = normalize_search_text(
                name
            )

            name_words = set(
                name_normalized.split()
            )

            score = 0

            if name_normalized == query_normalized:

                score += 1000

            if (
                query_normalized
                and query_normalized
                in name_normalized
            ):

                score += 300

            score += (
                len(
                    query_words
                    & name_words
                ) * 50
            )

            results.append(
                (
                    score,
                    product_id,
                    name
                )
            )

        except Exception as error:

            print(
                "SEARCH PRODUCT ERROR:",
                product_id,
                repr(error)
            )

    results.sort(
        key=lambda item: (
            -item[0],
            item[2].lower()
        )
    )

    return results[:top]


# =========================================================
# تنسيق السعر
# =========================================================

def format_store_price(price):

    price = int(
        price
    )

    if price % 1000 == 0:

        return (
            f"{price // 1000} ألف"
        )

    return (
        f"{price:,} دينار"
        .replace(",", ".")
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
# فحص التنبيه
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
# أزرار اللعبة
# =========================================================

def get_game_keyboard(
    product_id,
    alert_is_active
):

    buttons = [
        [
            InlineKeyboardButton(
                "🛒 اطلب الآن",
                callback_data=f"order:{product_id}"
            )
        ]
    ]

    if alert_is_active:

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

    return InlineKeyboardMarkup(
        buttons
    )


# =========================================================
# معرفة نوع المرجع
# =========================================================

def get_game_info_from_reference(
    reference
):

    if reference.startswith(
        "xboxid:"
    ):

        product_id = reference.split(
            ":",
            1
        )[1]

        return get_game_info_by_product_id(
            product_id
        )

    return get_game_info(
        reference
    )


# =========================================================
# فحص انخفاض الأسعار
# =========================================================

async def check_price_alerts(
    app
):

    print(
        "Checking price alerts..."
    )

    alerts = get_active_alerts()

    if not alerts:

        print(
            "No active alerts."
        )

        return

    for alert in alerts:

        (
            alert_id,
            user_id,
            chat_id,
            product_id,
            game_name,
            reference,
            old_price
        ) = alert

        try:

            (
                new_product_id,
                new_game_name,
                turkey_price,
                original_price,
                end_date
            ) = await asyncio.to_thread(
                get_game_info_from_reference,
                reference
            )

            new_store_price = calculate_price(
                turkey_price
            )

            if new_store_price < old_price:

                old_price_text = format_store_price(
                    old_price
                )

                new_price_text = format_store_price(
                    new_store_price
                )

                message = (
                    "🚨 <b>انخفض سعر اللعبة!</b>\n\n"
                    f"🎮 <b>{new_game_name}</b>\n\n"
                    f"💰 السعر السابق: "
                    f"<b>{old_price_text}</b> 🇮🇶\n"
                    f"🔥 السعر الجديد: "
                    f"<b>{new_price_text}</b> 🇮🇶\n\n"
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
            3600
        )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.message:

        await update.message.reply_text(
            "🎮 أرسل رابط لعبة من Xbox Store\n"
            "أو اكتب اسم اللعبة 🔍"
        )


# =========================================================
# ID
# =========================================================

async def my_id(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    user = update.effective_user

    await update.message.reply_text(
        f"🆔 Telegram ID مالك:\n\n{user.id}"
    )


# =========================================================
# إرسال نتيجة اللعبة
# =========================================================

async def process_game(
    update,
    product_id,
    game_name,
    turkey_price,
    original_price,
    end_date,
    reference,
    processing_message
):

    store_price = calculate_price(
        turkey_price
    )

    save_last_request(
        update.effective_user.id,
        product_id,
        game_name,
        reference,
        store_price
    )

    user_id = update.effective_user.id

    has_alert = alert_exists(
        user_id,
        product_id
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

        remaining_info = get_remaining_text(
            end_date
        )

        if remaining_info:

            (
                remaining_text,
                date_text,
                time_text
            ) = remaining_info

            expiry_text = (
                f"\n⏳ <b>ينتهي التخفيض:</b> "
                f"{date_text} الساعة {time_text}\n"
                f"📅 <b>{remaining_text}</b>\n"
            )

    price_text = format_store_price(
        store_price
    )

    if discount_percent is not None:

        message = (
            f"🎮 <b>{game_name}</b>\n\n"
            "🔥 <b>اللعبة عليها تخفيض!</b>\n\n"
            f"📉 نسبة الخصم: "
            f"<b>{discount_percent}%</b>\n"
            f"{expiry_text}\n"
            f"💰 سعر اللعبة: "
            f"<b>{price_text}</b> 🇮🇶"
        )

    else:

        message = (
            f"🎮 <b>{game_name}</b>\n\n"
            f"💰 سعر اللعبة: "
            f"<b>{price_text}</b> 🇮🇶"
        )

    keyboard = get_game_keyboard(
        product_id,
        has_alert
    )

    await processing_message.edit_text(
        text=message,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# استقبال الرابط أو اسم اللعبة
# =========================================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    text = update.message.text.strip()

    if len(text) < 2:
        return

    processing_message = (
        await update.message.reply_text(
            "⏳ جاري البحث..."
        )
    )

    try:

        # =================================================
        # إذا المستخدم أرسل رابط Xbox
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

            await process_game(
                update,
                product_id,
                game_name,
                turkey_price,
                original_price,
                end_date,
                text,
                processing_message
            )

            return

        # =================================================
        # إذا المستخدم كتب اسم اللعبة
        # =================================================

        results = await asyncio.to_thread(
            search_xbox_games,
            text,
            5
        )

        if not results:

            await processing_message.edit_text(
                "❌ ما لكيت اللعبة.\n\n"
                "جرب تكتب الاسم بالإنجليزي "
                "أو أرسل رابط Xbox Store."
            )

            return

        # =================================================
        # نتيجة واحدة
        # =================================================

        if len(results) == 1:

            (
                score,
                product_id,
                result_name
            ) = results[0]

            (
                product_id,
                game_name,
                turkey_price,
                original_price,
                end_date
            ) = await asyncio.to_thread(
                get_game_info_by_product_id,
                product_id
            )

            await process_game(
                update,
                product_id,
                game_name,
                turkey_price,
                original_price,
                end_date,
                f"xboxid:{product_id}",
                processing_message
            )

            return

        # =================================================
        # أكثر من نتيجة
        # =================================================

        buttons = []

        for (
            score,
            product_id,
            name
        ) in results:

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"🎮 {name[:45]}",
                        callback_data=(
                            f"searchselect:{product_id}"
                        )
                    )
                ]
            )

        await processing_message.edit_text(
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

        await processing_message.edit_text(
            "❌ صار خطأ أثناء جلب معلومات اللعبة.\n\n"
            "تأكد من الاسم أو الرابط "
            "وجرب مرة ثانية."
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
    # اختيار نتيجة البحث بالاسم
    # =====================================================

    if data.startswith(
        "searchselect:"
    ):

        product_id = data.split(
            ":",
            1
        )[1]

        await query.answer(
            "⏳ جاري جلب السعر..."
        )

        try:

            (
                product_id,
                game_name,
                turkey_price,
                original_price,
                end_date
            ) = await asyncio.to_thread(
                get_game_info_by_product_id,
                product_id
            )

            await process_game(
                update,
                product_id,
                game_name,
                turkey_price,
                original_price,
                end_date,
                f"xboxid:{product_id}",
                query.message
            )

        except Exception as error:

            print(
                "SEARCH SELECT ERROR:",
                repr(error)
            )

            await query.edit_message_text(
                "❌ ماكدرت أجيب سعر اللعبة، "
                "حاول مرة ثانية."
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

        added = add_alert(
            user_id=user_id,
            chat_id=query.message.chat_id,
            product_id=product_id,
            game_name=game_name,
            url=url,
            old_price=current_price
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

        keyboard = get_game_keyboard(
            product_id,
            True
        )

        try:

            await query.edit_message_reply_markup(
                reply_markup=keyboard
            )

        except Exception as error:

            print(
                "KEYBOARD ERROR:",
                repr(error)
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

            keyboard = get_game_keyboard(
                product_id,
                False
            )

            try:

                await query.edit_message_reply_markup(
                    reply_markup=keyboard
                )

            except Exception as error:

                print(
                    "KEYBOARD ERROR:",
                    repr(error)
                )

        else:

            await query.answer(
                "ماكو تنبيه فعال لهذه اللعبة",
                show_alert=True
            )

        return

    # =====================================================
    # طلب اللعبة
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

        customer_id = user.id

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
            f"🆔 ID: <code>{customer_id}</code>"
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
                    "ADMIN NOTIFICATION ERROR:",
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

    print(
        "Database initialized."
    )

    application.create_task(
        alert_loop(
            application
        )
    )

    print(
        "Price alert system started."
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
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_link
        )
    )

    print(
        "SA STORE BOT IS RUNNING..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
