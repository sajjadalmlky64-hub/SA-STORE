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
# حساب السعر بالعراقي
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
# استخراج Product ID
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

    if not value:
        return None

    # مثال:
    # 1.999,00
    # 1,999.00

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
# استخراج قيمة السعر من أي شكل
# ==========================================

def extract_number(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):

        number = float(value)

        if number > 0:
            return number

        return None

    if isinstance(value, str):

        number = to_float(value)

        if number and number > 0:
            return number

        return None

    if isinstance(value, dict):

        possible_keys = [

            "Amount",
            "amount",

            "Value",
            "value",

            "Price",
            "price",

            "DisplayPrice",
            "displayPrice",

            "FormattedPrice",
            "formattedPrice"
        ]

        for key in possible_keys:

            if key in value:

                number = extract_number(
                    value[key]
                )

                if number:
                    return number

    return None


# ==========================================
# التحقق من السعر المنطقي
# ==========================================

def is_valid_price(price):

    if price is None:
        return False

    if price <= 0:
        return False

    # يمنع الأرقام الغريبة من البيانات
    if price > 10000:
        return False

    return True


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

        raise Exception(
            "ما تم العثور على معلومات اللعبة"
        )

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

    raise Exception(
        "ماكدر أطلع اسم اللعبة"
    )


# ==========================================
# استخراج أزواج الأسعار المرتبطة
# ==========================================

def find_price_pairs(data, results=None):

    if results is None:
        results = []

    if isinstance(data, dict):

        current_price = None
        original_price = None


        # ==================================
        # السعر الحالي
        # ==================================

        current_keys = [

            "SalePrice",
            "salePrice",

            "DiscountPrice",
            "discountPrice",

            "CurrentPrice",
            "currentPrice",

            "UnitPrice",
            "unitPrice"
        ]


        for key in current_keys:

            if key in data:

                price = extract_number(
                    data[key]
                )

                if is_valid_price(price):

                    current_price = price
                    break


        # ==================================
        # السعر الأصلي
        # ==================================

        original_keys = [

            "ListPrice",
            "listPrice",

            "OriginalPrice",
            "originalPrice",

            "MSRP",
            "msrp"
        ]


        for key in original_keys:

            if key in data:

                price = extract_number(
                    data[key]
                )

                if is_valid_price(price):

                    original_price = price
                    break


        # ==================================
        # زوج خصم صحيح
        # ==================================

        if (
            current_price
            and original_price
            and original_price > current_price
        ):

            # يمنع الخصومات الوهمية 100%
            if current_price >= 1:

                results.append({
                    "current": current_price,
                    "original": original_price,
                    "discounted": True
                })


        # ==================================
        # سعر عادي بدون خصم
        # ==================================

        elif current_price:

            results.append({
                "current": current_price,
                "original": None,
                "discounted": False
            })


        # ==================================
        # بعض بيانات Microsoft تستخدم Price
        # ==================================

        if (
            "Price" in data
            and not current_price
        ):

            price = extract_number(
                data["Price"]
            )

            if is_valid_price(price):

                results.append({
                    "current": price,
                    "original": None,
                    "discounted": False
                })


        if (
            "price" in data
            and not current_price
        ):

            price = extract_number(
                data["price"]
            )

            if is_valid_price(price):

                results.append({
                    "current": price,
                    "original": None,
                    "discounted": False
                })


        # ==================================
        # البحث داخل البيانات
        # ==================================

        for value in data.values():

            if isinstance(
                value,
                (dict, list)
            ):

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
# جلب الأسعار من Microsoft Purchase API
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

def determine_best_price(price_data):

    if not price_data:

        return None, None


    discounted = []
    normal = []


    for item in price_data:

        current = item.get("current")
        original = item.get("original")
        is_discounted = item.get("discounted")


        if not is_valid_price(current):
            continue


        # ==================================
        # التخفيض الحقيقي فقط
        # ==================================

        if (
            is_discounted
            and original
            and original > current
        ):

            discount_percent = (
                (original - current)
                / original
            ) * 100


            # تجاهل الخصومات غير المنطقية
            if (
                discount_percent > 0
                and discount_percent < 100
            ):

                discounted.append(
                    (
                        current,
                        original,
                        discount_percent
                    )
                )


        else:

            normal.append(current)


    # ======================================
    # إذا وجدنا تخفيضًا حقيقيًا
    # ======================================

    if discounted:

        # اختيار الزوج الأكثر تكراراً
        frequency = {}

        for current, original, percent in discounted:

            key = (
                round(current, 2),
                round(original, 2)
            )

            frequency[key] = (
                frequency.get(key, 0) + 1
            )


        best_pair = max(
            frequency.items(),
            key=lambda x: x[1]
        )[0]


        return (
            best_pair[0],
            best_pair[1]
        )


    # ======================================
    # بدون تخفيض
    # ======================================

    if normal:

        frequency = {}

        for price in normal:

            key = round(price, 2)

            frequency[key] = (
                frequency.get(key, 0) + 1
            )


        best_price = max(
            frequency.items(),
            key=lambda x: x[1]
        )[0]


        return (
            best_price,
            None
        )


    return None, None


# ==========================================
# جلب معلومات اللعبة كاملة
# ==========================================

def get_game_info(url):

    product_id = get_product_id(url)

    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )


    # بيانات اللعبة
    product = get_product_data(
        product_id
    )


    # اسم اللعبة
    game_name = get_game_name(
        product
    )


    all_price_data = []


    # ======================================
    # Microsoft Purchase API
    # ======================================

    try:

        api_prices = get_prices_from_api(
            product_id
        )

        all_price_data.extend(
            api_prices
        )


    except Exception as error:

        print(
            "PURCHASE API ERROR:",
            repr(error)
        )


    # ======================================
    # Product Catalog
    # ======================================

    try:

        product_prices = (
            get_prices_from_product(
                product
            )
        )

        all_price_data.extend(
            product_prices
        )


    except Exception as error:

        print(
            "PRODUCT DATA ERROR:",
            repr(error)
        )


    # ======================================
    # تحديد السعر النهائي
    # ======================================

    current_price, original_price = (
        determine_best_price(
            all_price_data
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
# استقبال رابط Xbox
# ==========================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:

        return


    text = (
        update.message.text or ""
    ).strip()


    # ======================================
    # التأكد من الرابط
    # ======================================

    if "xbox.com" not in text.lower():

        await update.message.reply_text(
            "يرجى إرسال رابط اللعبة"
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
        ) = get_game_info(
            text
        )


        # ==================================
        # حساب السعر العراقي
        # ==================================

        game_price = calculate_price(
            turkey_price
        )


        game_price_text = (
            format_game_price(
                game_price
            )
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


            # حماية إضافية
            if (
                discount_percent > 0
                and discount_percent < 100
            ):

                result = (
                    f"🎮 {game_name}\n\n"
                    f"🔥 اللعبة عليها تخفيض!\n\n"
                    f"📉 نسبة الخصم: "
                    f"{discount_percent}%\n\n"
                    f"━━━━━━━━━━━━━━\n\n"
                    f"💰 سعر اللعبة: "
                    f"{game_price_text} 🇮🇶"
                )

            else:

                result = (
                    f"🎮 {game_name}\n\n"
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


    # START
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    # الروابط
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


    app.run_polling(
        drop_pending_updates=True
    )


# ==========================================
# تشغيل البرنامج
# ==========================================

if __name__ == "__main__":
    main()
