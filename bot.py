import os
import re
import math
import json
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)


# ==================================================
# BOT TOKEN
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")


# ==================================================
# HEADERS
# ==================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ==================================================
# SESSION
# ==================================================

session = requests.Session()
session.headers.update(HEADERS)


# ==================================================
# حساب السعر العراقي
# ==================================================

def calculate_price(price):

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


# ==================================================
# تنسيق السعر العراقي
# ==================================================

def format_game_price(price):

    price = int(price)

    if price % 1000 == 0:

        return f"{price // 1000} ألف"

    return f"{price:,} دينار".replace(",", ".")


# ==================================================
# استخراج Product ID
# ==================================================

def get_product_id(url):

    url = url.upper()

    # Product IDs الخاصة بـ Microsoft/Xbox
    matches = re.findall(
        r"(?<![A-Z0-9])([A-Z0-9]{12})(?![A-Z0-9])",
        url
    )

    if matches:
        return matches[-1]

    return None


# ==================================================
# تحويل السعر إلى رقم
# ==================================================

def to_float(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    value = str(value)

    value = (
        value.replace("₺", "")
        .replace("TRY", "")
        .replace("TL", "")
        .replace("&nbsp;", "")
        .replace("\xa0", "")
        .strip()
    )

    # إزالة الفراغات
    value = value.replace(" ", "")

    # 2.999,00
    if "," in value and "." in value:

        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "")
            value = value.replace(",", ".")

        else:
            value = value.replace(",", "")

    # 449,85
    elif "," in value:

        value = value.replace(",", ".")

    try:
        return float(value)

    except Exception:
        return None


# ==================================================
# جلب بيانات المنتج
# ==================================================

def get_product_data(product_id):

    url = (
        "https://displaycatalog.mp.microsoft.com/"
        f"v7.0/products/{product_id}"
    )

    params = {
        "market": "TR",
        "languages": "tr-TR,en-US",
        "fieldsTemplate": "Details"
    }

    response = session.get(
        url,
        params=params,
        timeout=25
    )

    response.raise_for_status()

    data = response.json()

    product = data.get("Product")

    if not product:

        products = data.get("Products", [])

        if products:
            product = products[0]

    if not product:
        raise Exception("لم يتم العثور على اللعبة")

    return product


# ==================================================
# استخراج اسم اللعبة
# ==================================================

def get_game_name(product):

    localized = product.get(
        "LocalizedProperties",
        []
    )

    if isinstance(localized, list):

        for item in localized:

            if not isinstance(item, dict):
                continue

            title = item.get("ProductTitle")

            if title:
                return title

    title = product.get("ProductTitle")

    if title:
        return title

    raise Exception("تعذر استخراج اسم اللعبة")


# ==================================================
# استخراج رقم من كائن السعر
# ==================================================

def extract_number(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        return to_float(value)

    if isinstance(value, dict):

        keys = [
            "Amount",
            "amount",
            "Value",
            "value",
            "Price",
            "price",
            "PriceValue",
            "priceValue",
            "FormattedPrice"
        ]

        for key in keys:

            if key in value:

                result = extract_number(value[key])

                if result is not None:
                    return result

    return None


# ==================================================
# استخراج السعر الحالي والأصلي من نفس الكائن
# ==================================================

def extract_price_pair_from_dict(data):

    if not isinstance(data, dict):
        return None

    current_keys = [
        "SalePrice",
        "salePrice",
        "DiscountPrice",
        "discountPrice",
        "CurrentPrice",
        "currentPrice",
        "UnitPrice",
        "unitPrice",
        "Price",
        "price"
    ]

    original_keys = [
        "ListPrice",
        "listPrice",
        "OriginalPrice",
        "originalPrice",
        "MSRP",
        "msrp"
    ]

    current_price = None
    original_price = None


    # السعر الحالي
    for key in current_keys:

        if key in data:

            value = extract_number(data[key])

            if value is not None and value > 0:

                current_price = value
                break


    # السعر الأصلي
    for key in original_keys:

        if key in data:

            value = extract_number(data[key])

            if value is not None and value > 0:

                original_price = value
                break


    # بعض بيانات Microsoft تكون داخل Price object
    if current_price is None:

        price_data = data.get("Price")

        if isinstance(price_data, dict):

            for key in current_keys:

                if key in price_data:

                    value = extract_number(
                        price_data[key]
                    )

                    if value is not None and value > 0:

                        current_price = value
                        break


    if original_price is None:

        price_data = data.get("Price")

        if isinstance(price_data, dict):

            for key in original_keys:

                if key in price_data:

                    value = extract_number(
                        price_data[key]
                    )

                    if value is not None and value > 0:

                        original_price = value
                        break


    if current_price is not None:

        return (
            current_price,
            original_price
        )

    return None


# ==================================================
# البحث عن أزواج الأسعار داخل البيانات
# ==================================================

def find_price_pairs(data, results=None):

    if results is None:
        results = []

    if isinstance(data, dict):

        pair = extract_price_pair_from_dict(data)

        if pair:

            results.append(pair)

        for value in data.values():

            if isinstance(value, (dict, list)):

                find_price_pairs(
                    value,
                    results
                )


    elif isinstance(data, list):

        for item in data:

            find_price_pairs(
                item,
                results
            )

    return results


# ==================================================
# Microsoft Purchase API
# ==================================================

def get_purchase_data(product_id):

    url = (
        "https://purchase.mp.microsoft.com/"
        "v9.0/users/me/availability"
    )

    params = {
        "market": "TR",
        "languages": "tr-TR",
        "productIds": product_id
    }

    response = session.get(
        url,
        params=params,
        timeout=25
    )

    response.raise_for_status()

    return response.json()


# ==================================================
# استخراج الأسعار من صفحة Xbox
# ==================================================

def get_prices_from_page(url):

    response = session.get(
        url,
        timeout=25
    )

    response.raise_for_status()

    html = response.text

    pairs = []

    # ==============================================
    # محاولة استخراج السعر الحالي والأصلي من JSON
    # ==============================================

    patterns = [

        r'"salePrice"\s*:\s*"([^"]+)"',

        r'"SalePrice"\s*:\s*"([^"]+)"',

        r'"discountPrice"\s*:\s*"([^"]+)"',

        r'"currentPrice"\s*:\s*"([^"]+)"',
    ]


    original_patterns = [

        r'"listPrice"\s*:\s*"([^"]+)"',

        r'"ListPrice"\s*:\s*"([^"]+)"',

        r'"originalPrice"\s*:\s*"([^"]+)"',

        r'"MSRP"\s*:\s*"([^"]+)"',
    ]


    current_prices = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE
        )

        for match in matches:

            price = to_float(match)

            if price and price > 0:

                current_prices.append(price)


    original_prices = []

    for pattern in original_patterns:

        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE
        )

        for match in matches:

            price = to_float(match)

            if price and price > 0:

                original_prices.append(price)


    # نستخدم الصفحة فقط كخيار احتياطي
    if current_prices:

        current = min(current_prices)

        original = None

        possible_originals = [
            price
            for price in original_prices
            if price > current
        ]

        if possible_originals:

            original = min(possible_originals)

        pairs.append(
            (
                current,
                original
            )
        )


    return pairs


# ==================================================
# تنظيف واختيار أفضل سعر
# ==================================================

def determine_best_price(price_pairs):

    valid_pairs = []

    for current, original in price_pairs:

        try:
            current = float(current)
        except Exception:
            continue


        # تجاهل المجاني والقيم الغريبة
        if current <= 0:
            continue

        if current > 10000:
            continue


        # تنظيف السعر الأصلي
        if original is not None:

            try:
                original = float(original)
            except Exception:
                original = None


        if original is not None:

            if original <= current:
                original = None

            elif original > 10000:
                original = None


        valid_pairs.append(
            (
                current,
                original
            )
        )


    if not valid_pairs:
        return None, None


    # ==============================================
    # البحث عن تخفيض صحيح
    # ==============================================

    discounted = []

    for current, original in valid_pairs:

        if original is not None and original > current:

            percent = (
                (original - current)
                / original
            ) * 100


            # تجاهل الخصومات غير المنطقية
            if 1 <= percent <= 99:

                discounted.append(
                    (
                        current,
                        original,
                        percent
                    )
                )


    if discounted:

        # نختار الزوج الذي يظهر أكثر من مرة
        # لأن السعر المتكرر غالباً هو السعر الصحيح
        pair_count = {}

        for current, original, percent in discounted:

            key = (
                round(current, 2),
                round(original, 2)
            )

            pair_count[key] = (
                pair_count.get(key, 0) + 1
            )


        discounted.sort(
            key=lambda x: (
                pair_count.get(
                    (
                        round(x[0], 2),
                        round(x[1], 2)
                    ),
                    0
                ),
                x[1]
            ),
            reverse=True
        )


        current, original, percent = discounted[0]

        return current, original


    # ==============================================
    # بدون تخفيض
    # ==============================================

    prices = [
        current
        for current, original in valid_pairs
    ]


    if not prices:
        return None, None


    # نختار السعر الأكثر تكراراً
    price_count = {}

    for price in prices:

        key = round(price, 2)

        price_count[key] = (
            price_count.get(key, 0) + 1
        )


    prices.sort(
        key=lambda x: (
            price_count.get(
                round(x, 2),
                0
            ),
            x
        ),
        reverse=True
    )


    return prices[0], None


# ==================================================
# جلب معلومات اللعبة كاملة
# ==================================================

def get_game_info(url):

    product_id = get_product_id(url)

    if not product_id:

        raise Exception(
            "تعذر استخراج رقم اللعبة من الرابط"
        )


    # ==============================================
    # بيانات اللعبة
    # ==============================================

    product = get_product_data(product_id)

    game_name = get_game_name(product)


    all_pairs = []


    # ==============================================
    # Purchase API
    # ==============================================

    try:

        purchase_data = get_purchase_data(
            product_id
        )

        pairs = find_price_pairs(
            purchase_data
        )

        all_pairs.extend(pairs)

    except Exception as error:

        print(
            "PURCHASE API ERROR:",
            repr(error)
        )


    # ==============================================
    # Product API
    # ==============================================

    try:

        pairs = find_price_pairs(product)

        all_pairs.extend(pairs)

    except Exception as error:

        print(
            "PRODUCT DATA ERROR:",
            repr(error)
        )


    # ==============================================
    # صفحة Xbox كاحتياط
    # ==============================================

    try:

        pairs = get_prices_from_page(url)

        all_pairs.extend(pairs)

    except Exception as error:

        print(
            "PAGE ERROR:",
            repr(error)
        )


    # ==============================================
    # اختيار السعر النهائي
    # ==============================================

    current_price, original_price = (
        determine_best_price(all_pairs)
    )


    if current_price is None:

        raise Exception(
            "تعذر العثور على سعر اللعبة"
        )


    return (
        game_name,
        current_price,
        original_price
    )


# ==================================================
# START
# ==================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "يرجى إرسال رابط اللعبة"
    )


# ==================================================
# استقبال الرابط
# ==================================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    text = (
        update.message.text or ""
    ).strip()


    # التأكد من الرابط
    if "xbox.com" not in text.lower():

        await update.message.reply_text(
            "يرجى إرسال رابط لعبة من Xbox Store"
        )

        return


    processing_message = (
        await update.message.reply_text(
            "⏳ جاري البحث..."
        )
    )


    try:

        (
            game_name,
            turkey_price,
            original_price
        ) = get_game_info(text)


        # السعر العراقي
        iraq_price = calculate_price(
            turkey_price
        )

        iraq_price_text = format_game_price(
            iraq_price
        )


        # ==============================================
        # إذا يوجد تخفيض
        # ==============================================

        if (
            original_price is not None
            and original_price > turkey_price
        ):

            discount_percent = round(
                (
                    original_price - turkey_price
                )
                / original_price
                * 100
            )


            # حماية إضافية
            if 1 <= discount_percent <= 99:

                result = (
                    f"🎮 {game_name}\n\n"
                    f"🔥 اللعبة عليها تخفيض!\n\n"
                    f"📉 نسبة الخصم: "
                    f"{discount_percent}%\n\n"
                    f"━━━━━━━━━━━━━━\n\n"
                    f"💰 سعر اللعبة: "
                    f"{iraq_price_text} 🇮🇶"
                )

            else:

                result = (
                    f"🎮 {game_name}\n\n"
                    f"━━━━━━━━━━━━━━\n\n"
                    f"💰 سعر اللعبة: "
                    f"{iraq_price_text} 🇮🇶"
                )


        # ==============================================
        # بدون تخفيض
        # ==============================================

        else:

            result = (
                f"🎮 {game_name}\n\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 سعر اللعبة: "
                f"{iraq_price_text} 🇮🇶"
            )


        await processing_message.edit_text(
            result
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


# ==================================================
# MAIN
# ==================================================

def main():

    if not BOT_TOKEN:

        raise ValueError(
            "BOT_TOKEN غير موجود في Variables"
        )


    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )


    # START
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    # استقبال الروابط
    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_link
        )
    )


    print("Bot is running...")


    app.run_polling(
        drop_pending_updates=True
    )


# ==================================================
# تشغيل البوت
# ==================================================

if __name__ == "__main__":
    main()
