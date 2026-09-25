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

# كاش دائم داخل تشغيل البوت لنتائج البحث
SEARCH_RESULT_CACHE = {}


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
# أزرار اللعبة
# =========================================================

def get_game_keyboard(
    product_id,
    active
):

    buttons = [
        [
            InlineKeyboardButton(
                "🛒 اطلب الآن",
                callback_data=f"order:{product_id}"
            )
        ]
    ]

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

    return InlineKeyboardMarkup(
        buttons
    )


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
    reference
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
        alert_exists(
            update.effective_user.id,
            product_id
        )
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

    if update.message:

        await update.message.reply_text(
            f"🆔 Telegram ID مالك:\n\n"
            f"{update.effective_user.id}"
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
            search_xbox_games,
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

        buttons = []

        for product_id, result_name in valid_results:

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"🎮 {result_name[:50]}",
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
    # اختيار نتيجة البحث
    # =====================================================

    if data.startswith(
        "searchselect:"
    ):

        product_id = data.split(
            ":",
            1
        )[1].upper()

        await query.answer(
            "⏳ جاري جلب السعر..."
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
                f"xboxid:{resolved_product_id}"
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
                True
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

            await query.edit_message_reply_markup(
                reply_markup=get_game_keyboard(
                    product_id,
                    False
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
