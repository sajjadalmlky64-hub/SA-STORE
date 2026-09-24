import os
import re
import math
import asyncio
import sqlite3
import requests

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
# BOT TOKEN
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN غير موجود في Variables")


# =========================================================
# ADMIN CHAT ID
# =========================================================

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")


# =========================================================
# HEADERS
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


# =========================================================
# SESSION
# =========================================================

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# =========================================================
# DATABASE
# =========================================================

DB_FILE = "price_alerts.db"


def init_database():

    connection = sqlite3.connect(DB_FILE)

    cursor = connection.cursor()

    # تنبيهات الأسعار
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

    # آخر لعبة أرسلها كل مستخدم
    # حتى نعرف الرابط الأصلي عند الضغط على الأزرار
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
# حساب السعر بالعراقي
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
# استخراج Product ID
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
        value.replace("₺", "")
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
# استخراج قيمة السعر
# =========================================================

def extract_price(value):

    if value is None:
        return None

    if isinstance(value, (int, float, str)):
        return to_float(value)

    if isinstance(value, dict):

        keys = [
            "Amount",
            "amount",
            "Value",
            "value",
            "Price",
            "price",
            "FormattedPrice",
            "formattedPrice"
        ]

        for key in keys:

            if key in value:

                result = extract_price(
                    value[key]
                )

                if result is not None:
                    return result

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

    products = data.get(
        "Products",
        []
    )

    if not products:

        product = data.get("Product")

        if product:
            return product

        raise Exception(
            "Microsoft لم يعثر على اللعبة"
        )

    return products[0]


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

                if currency.upper() not in [
                    "TRY",
                    "TL"
                ]:

                    continue

            if list_price is None:
                continue

            if list_price <= 0:
                continue

            if (
                msrp is not None
                and msrp > list_price
            ):

                results.append(
                    (
                        list_price,
                        msrp
                    )
                )

            else:

                results.append(
                    (
                        list_price,
                        None
                    )
                )

    return results


# =========================================================
# اختيار السعر الصحيح
# =========================================================

def determine_best_price(price_pairs):

    if not price_pairs:
        return None, None

    valid_pairs = []

    for current, original in price_pairs:

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
                original
            )
        )

    if not valid_pairs:
        return None, None

    discounted = []

    for current, original in valid_pairs:

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
                        round(original, 2)
                    )
                )

    if discounted:

        unique = list(
            set(discounted)
        )

        unique.sort(
            key=lambda x: x[0]
        )

        return unique[0]

    prices = []

    for current, original in valid_pairs:

        prices.append(
            round(current, 2)
        )

    if not prices:
        return None, None

    counter = Counter(prices)

    best_price = counter.most_common(1)[0][0]

    return best_price, None


# =========================================================
# جلب معلومات اللعبة
# =========================================================

def get_game_info(url):

    product_id = get_product_id(url)

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

    current_price, original_price = (
        determine_best_price(
            price_pairs
        )
    )

    if current_price is None:

        raise Exception(
            "Microsoft لم يعثر على سعر اللعبة"
        )

    return (
        product_id,
        game_name,
        current_price,
        original_price
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
# رابط التواصل
# =========================================================

ORDER_URL = "https://t.me/Sijadsa"


# =========================================================
# حفظ آخر طلب/لعبة للمستخدم
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
# أزرار اللعبة
# =========================================================

def get_game_keyboard(
    product_id,
    alert_is_active=False
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
# فحص هل التنبيه موجود
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
# جلب التنبيهات الفعالة
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
# إيقاف تنبيه
# =========================================================

def deactivate_alert(alert_id):

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
# فحص جميع التنبيهات
# =========================================================

async def check_price_alerts(app):

    print("Checking price alerts...")

    alerts = get_active_alerts()

    if not alerts:

        print("No active alerts.")

        return

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
                new_product_id,
                new_game_name,
                turkey_price,
                original_price
            ) = await asyncio.to_thread(
                get_game_info,
                url
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

                await app.bot.send_me
        unique.sort(
            key=lambda x: x[0]
        )

        return unique[0]

    # =====================================================
    # بدون تخفيض
    # =====================================================

    prices = []

    for current, original in valid_pairs:

        prices.append(
            round(current, 2)
        )

    if not prices:
        return None, None

    counter = Counter(prices)

    best_price = counter.most_common(1)[0][0]

    return best_price, None


# =========================================================
# جلب معلومات اللعبة
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

    current_price, original_price = (
        determine_best_price(
            price_pairs
        )
    )

    if current_price is None:

        raise Exception(
            "Microsoft لم يعثر على سعر اللعبة"
        )

    return (
        product_id,
        game_name,
        current_price,
        original_price
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
# رابط الطلب
# =========================================================

ORDER_URL = "https://t.me/Sijadsa"


# =========================================================
# أزرار اللعبة
# =========================================================

def get_game_keyboard(
    product_id,
    alert_exists=False
):

    buttons = [
        [
            InlineKeyboardButton(
                "🛒 اطلب الآن",
                url=ORDER_URL
            )
        ]
    ]

    if alert_exists:

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
# فحص هل التنبيه موجود
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
# جلب التنبيهات الفعالة
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
# إيقاف تنبيه
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
# فحص جميع التنبيهات
# =========================================================

async def check_price_alerts(
    context: ContextTypes.DEFAULT_TYPE
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
            url,
            old_price
        ) = alert

        try:

            (
                new_product_id,
                new_game_name,
                turkey_price,
                original_price
            ) = await asyncio.to_thread(
                get_game_info,
                url
            )

            new_store_price = calculate_price(
                turkey_price
            )

            # =================================================
            # السعر انخفض
            # =================================================

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
                            url=ORDER_URL
                        )
                    ]
                ])

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    reply_markup=keyboard
                )

                # إيقاف التنبيه بعد الإرسال
                deactivate_alert(
                    alert_id
                )

                print(
                    "PRICE DROP:",
                    new_game_name,
                    old_price,
                    "->",
                    new_store_price
                )

        except Exception as error:

            print(
                "ALERT ERROR:",
                alert_id,
                repr(error)
            )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "يرجى إرسال رابط اللعبة"
    )


# =========================================================
# استقبال الرابط
# =========================================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    text = update.message.text.strip()

    if "xbox.com" not in text.lower():

        await update.message.reply_text(
            "يرجى إرسال رابط لعبة من Xbox Store"
        )

        return

    processing_message = await update.message.reply_text(
        "⏳ جاري البحث..."
    )

    try:

        (
            product_id,
            game_name,
            turkey_price,
            original_price
        ) = await asyncio.to_thread(
            get_game_info,
            text
        )

        store_price = calculate_price(
            turkey_price
        )

        store_price_text = format_store_price(
            store_price
        )

        user_id = update.effective_user.id

        has_alert = alert_exists(
            user_id,
            product_id
        )

        # =================================================
        # عليها تخفيض
        # =================================================

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
                )
                * 100
            )

            result = (
                f"🎮 {game_name}\n\n"
                f"🔥 اللعبة عليها تخفيض!\n\n"
                f"📉 نسبة الخصم: "
                f"{discount_percent}%\n\n"
                f"💰 سعر اللعبة: "
                f"{store_price_text} 🇮🇶"
            )

        # =================================================
        # بدون تخفيض
        # =================================================

        else:

            result = (
                f"🎮 {game_name}\n\n"
                f"💰 سعر اللعبة: "
                f"{store_price_text} 🇮🇶"
            )

        keyboard = get_game_keyboard(
            product_id,
            has_alert
        )

        await processing_message.edit_text(
            result,
            reply_markup=keyboard
        )

    except Exception as error:

        print(
            "ERROR:",
            repr(error)
        )

        await processing_message.edit_text(
            "❌ صار خطأ أثناء جلب معلومات اللعبة.\n\n"
            "تأكد من الرابط وجرب مرة ثانية."
        )


# =========================================================
# معالجة الأزرار
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    data = query.data

    # =====================================================
    # إضافة تنبيه
    # =====================================================

    if data.startswith("alert:"):

        product_id = data.split(
            ":",
            1
        )[1]

        try:

            (
                real_product_id,
                game_name,
                turkey_price,
                original_price
            ) = await asyncio.to_thread(
                get_game_info,
                query.message.text
            )

        except Exception:

            # إذا ما قدرنا نستخدم نص الرسالة كرابط
            # نطلب من المستخدم إرسال الرابط مرة ثانية
            await query.answer(
                "أرسل رابط اللعبة مرة ثانية حتى أفعل التنبيه.",
                show_alert=True
            )

            return

        store_price = calculate_price(
            turkey_price
        )

        added = add_alert(
            user_id=user_id,
            chat_id=query.message.chat_id,
            product_id=product_id,
            game_name=game_name,
            url="",
            old_price=store_price
        )

        if added:

            await query.edit_message_reply_markup(
                reply_markup=get_game_keyboard(
                    product_id,
                    True
                )
            )

            await query.answer(
                "🔔 تم تفعيل التنبيه!",
                show_alert=True
            )

        else:

            await query.answer(
                "🔔 التنبيه مفعل مسبقًا.",
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
            user_id,
            product_id
        )

        if cancelled:

            await query.edit_message_reply_markup(
                reply_markup=get_game_keyboard(
                    product_id,
                    False
                )
            )

            await query.answer(
                "🔕 تم إلغاء التنبيه.",
                show_alert=True
            )

        else:

            await query.answer(
                "ماكو تنبيه فعال لهذه اللعبة.",
                show_alert=True
            )


# =========================================================
# أمر التنبيهات
# =========================================================

async def my_alerts(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    connection = sqlite3.connect(
        DB_FILE
    )

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT game_name, old_price
        FROM alerts
        WHERE user_id = ?
        AND active = 1
        """,
        (
            user_id,
        )
    )

    rows = cursor.fetchall()

    connection.close()

    if not rows:

        await update.message.reply_text(
            "🔔 ما عندك أي تنبيهات مفعلة."
        )

        return

    message = (
        "🔔 <b>ألعابك التي تتابع أسعارها:</b>\n\n"
    )

    for index, (
        game_name,
        old_price
    ) in enumerate(rows, 1):

        price_text = format_store_price(
            old_price
        )

        message += (
            f"{index}. 🎮 {game_name}\n"
            f"   💰 السعر عند المتابعة: "
            f"{price_text} 🇮🇶\n\n"
        )

    await update.message.reply_text(
        message,
        parse_mode="HTML"
    )


# =========================================================
# تشغيل البوت
# =========================================================

def main():

    if not BOT_TOKEN:

        raise ValueError(
            "BOT_TOKEN غير موجود في Variables"
        )

    init_database()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # =====================================================
    # Commands
    # =====================================================

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "alerts",
            my_alerts
        )
    )

    # =====================================================
    # Buttons
    # =====================================================

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # =====================================================
    # روابط Xbox
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_link
        )
    )

    # =====================================================
    # فحص الأسعار كل ساعة
    # =====================================================

    if app.job_queue:

        app.job_queue.run_repeating(
            check_price_alerts,
            interval=3600,
            first=60
        )

        print(
            "Price alert checker enabled."
        )

    else:

        print(
            "WARNING: JobQueue غير متوفر."
        )

        print(
            "ثبت python-telegram-bot[job-queue]"
        )

    print(
        "SA STORE Bot is running..."
    )

    app.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# تشغيل
# =========================================================

if __name__ == "__main__":

    main()
