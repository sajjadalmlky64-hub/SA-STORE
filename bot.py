import os
import re
import math
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)


# ==========================================
# BOT TOKEN
# ==========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")


# ==========================================
# HEADERS
# ==========================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ==========================================
# حساب سعر اللعبة بالعراقي
# ==========================================

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


# ==========================================
# استخراج Product ID من رابط Xbox
# ==========================================

def get_product_id(url):

    url = url.upper()

    matches = re.findall(
        r"(?<![A-Z0-9])([A-Z0-9]{12})(?![A-Z0-9])",
        url
    )

    if matches:
        return matches[-1]

    return None


# ==========================================
# تحويل السعر إلى رقم
# ==========================================

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
        .replace("\xa0", "")
        .replace(" ", "")
        .strip()
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

    except ValueError:
        return None


# ==========================================
# جلب بيانات اللعبة
# ==========================================

def get_product_data(product_id):

    api_url = (
        "https://displaycatalog.mp.microsoft.com/"
        f"v7.0/products/{product_id}"
    )

    params = {
        "market": "TR",
        "languages": "tr-TR,en-US",
        "fieldsTemplate": "Details"
    }

    response = requests.get(
        api_url,
        params=params,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    product = data.get("Product")

    if not product:

        products = data.get("Products", [])

        if products:
            product = products[0]

    if not product:
        raise Exception("ما تم العثور على معلومات اللعبة")

    return product


# ==========================================
# استخراج اسم اللعبة
# ==========================================

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

    raise Exception("ماكدر أطلع اسم اللعبة")


# ==========================================
# استخراج السعر من قيمة
# ==========================================

def get_price_value(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        return to_float(value)

    if isinstance(value, dict):

        possible_keys = [
            "Amount",
            "amount",
            "Value",
            "value",
            "Price",
            "price"
        ]

        for key in possible_keys:

            if key in value:

                result = get_price_value(value[key])

                if result is not None:
                    return result

    return None


# ==========================================
# استخراج أزواج الأسعار بشكل صحيح
# ==========================================

def find_price_pairs(data, results=None):

    if results is None:
        results = []

    if isinstance(data, dict):

        # أسماء السعر الحالي
        current_keys = [
            "SalePrice",
            "salePrice",
            "DiscountPrice",
            "discountPrice",
            "UnitPrice",
            "unitPrice"
        ]

        # أسماء السعر الأصلي
        original_keys = [
            "ListPrice",
            "listPrice",
            "MSRP",
            "msrp",
            "OriginalPrice",
            "originalPrice"
        ]

        current_price = None
        original_price = None


        # البحث عن السعر الحالي
        for key in current_keys:

            if key in data:

                value = get_price_value(data[key])

                if value and value > 0:
                    current_price = value
                    break


        # البحث عن السعر الأصلي
        for key in original_keys:

            if key in data:

                value = get_price_value(data[key])

                if value and value > 0:
                    original_price = value
                    break


        # إذا وجدنا سعرين
        if (
            current_price
            and original_price
            and original_price >= current_price
        ):

            results.append(
                (
                    current_price,
                    original_price
                )
            )


        # إذا وجدنا السعر الحالي فقط
        elif current_price:

            results.append(
                (
                    current_price,
                    None
                )
            )


        # البحث داخل البيانات
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


# ==========================================
# جلب الأسعار من Microsoft API
# ==========================================

def get_prices_from_api(product_id):

    api_url = (
        "https://purchase.mp.microsoft.com/"
        "v9.0/users/me/availability"
    )

    params = {
        "market": "TR",
        "languages": "tr-TR",
        "productIds": product_id
    }

    response = requests.get(
        api_url,
        params=params,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    return find_price_pairs(data)


# ==========================================
# استخراج الأسعار من Product Data
# ==========================================

def get_prices_from_product(product):

    return find_price_pairs(product)


# ==========================================
# اختيار أفضل سعر
# ==========================================

def determine_best_price(price_pairs):

    if not price_pairs:
        return None, None


    # إزالة الأسعار غير المنطقية
    cleaned = []

    for current, original in price_pairs:

        if not current:
            continue

        if current <= 0:
            continue

        # أسعار ألعاب Xbox التركية المنطقية
        if current > 100000:
            continue

        if original and original > 100000:
            original = None

        cleaned.append(
            (
                current,
                original
            )
        )


    if not cleaned:
        return None, None


    # نفضل الزوج الذي يحتوي على سعر أصلي وسعر حالي
    discounted = []

    for current, original in cleaned:

        if (
            original
            and original > current
        ):

            discounted.append(
                (
                    current,
                    original
                )
            )


    # إذا اللعبة عليها تخفيض
    if discounted:

        # اختيار زوج أسعار منطقي
        discounted.sort(
            key=lambda x: x[1],
            reverse=True
        )

        return discounted[0]


    # بدون تخفيض
    current_prices = []

    for current, original in cleaned:

        current_prices.append(current)


    if current_prices:

        # أكثر سعر منطقي يظهر بالبيانات
        current_prices.sort()

        return current_prices[-1], None


    return None, None


# ==========================================
# جلب كل معلومات اللعبة
# ==========================================

def get_game_info(url):

    product_id = get_product_id(url)

    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )


    # جلب بيانات اللعبة
    product = get_product_data(
        product_id
    )


    # اسم اللعبة
    game_name = get_game_name(
        product
    )


    price_pairs = []


    # ======================================
    # Microsoft Purchase API
    # ======================================

    try:

        api_pairs = get_prices_from_api(
            product_id
        )

        price_pairs.extend(
            api_pairs
        )

    except Exception as error:

        print(
            "API PRICE ERROR:",
            repr(error)
        )


    # ======================================
    # Product Data
    # ======================================

    try:

        product_pairs = get_prices_from_product(
            product
        )

        price_pairs.extend(
            product_pairs
        )

    except Exception as error:

        print(
            "PRODUCT PRICE ERROR:",
            repr(error)
        )


    # ======================================
    # تحديد السعر
    # ======================================

    current_price, original_price = (
        determine_best_price(
            price_pairs
        )
    )


    if not current_price:

        raise Exception(
            "ماكدر أطلع سعر اللعبة"
        )


    return (
        game_name,
        current_price,
        original_price
    )


# ==========================================
# تنسيق السعر العراقي
# ==========================================

def format_game_price(price):

    price = int(price)

    thousands = price // 1000

    if price % 1000 == 0:

        return f"{thousands} ألف"

    return (
        f"{price:,} دينار"
        .replace(",", ".")
    )


# ==========================================
# أمر START
# ==========================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "يرجى إرسال رابط اللعبة"
    )


# ==========================================
# استقبال الرابط
# ==========================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()


    # التأكد من الرابط
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
            game_name,
            turkey_price,
            original_price
        ) = get_game_info(text)


        # حساب السعر العراقي
        game_price = calculate_price(
            turkey_price
        )


        game_price_text = format_game_price(
            game_price
        )


        # ==================================
        # اللعبة عليها تخفيض
        # ==================================

        if (
            original_price
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
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 سعر اللعبة: "
                f"{game_price_text} 🇮🇶"
            )


        # ==================================
        # اللعبة بدون تخفيض
        # ==================================

        else:

            result = (
                f"🎮 {game_name}\n\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 سعر اللعبة: "
                f"{game_price_text} 🇮🇶"
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


# ==========================================
# تشغيل البوت
# ==========================================

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


    # أمر Start
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


    print(
        "Bot is running..."
    )


    app.run_polling()


# ==========================================
# تشغيل البرنامج
# ==========================================

if __name__ == "__main__":
    main()
