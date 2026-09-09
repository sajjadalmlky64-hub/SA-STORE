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

    except ValueError:
        return None


# ==========================================
# جلب بيانات اللعبة من Microsoft
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
        raise Exception("لم يتم العثور على اللعبة")

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

    raise Exception("تعذر استخراج اسم اللعبة")


# ==========================================
# استخراج رقم السعر من أي قيمة
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
            "price",
            "PriceValue",
            "priceValue"
        ]

        for key in possible_keys:

            if key in value:

                result = get_price_value(
                    value[key]
                )

                if result is not None:
                    return result

    return None


# ==========================================
# استخراج أزواج الأسعار
# السعر الحالي + السعر الأصلي
# ==========================================

def find_price_pairs(data, results=None):

    if results is None:
        results = []

    if isinstance(data, dict):

        current_keys = [
            "SalePrice",
            "salePrice",
            "DiscountPrice",
            "discountPrice",
            "UnitPrice",
            "unitPrice",
            "CurrentPrice",
            "currentPrice"
        ]

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

                value = get_price_value(
                    data[key]
                )

                if value is not None and value > 0:

                    current_price = value
                    break


        # البحث عن السعر الأصلي
        for key in original_keys:

            if key in data:

                value = get_price_value(
                    data[key]
                )

                if value is not None and value > 0:

                    original_price = value
                    break


        # إضافة الزوج فقط إذا وجد سعر حالي
        if current_price is not None:

            results.append(
                (
                    current_price,
                    original_price
                )
            )


        # البحث داخل جميع البيانات
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
# Microsoft Purchase API
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
# اختيار السعر الصحيح
# ==========================================

def determine_best_price(price_pairs):

    if not price_pairs:
        return None, None


    valid_pairs = []


    for current, original in price_pairs:

        try:
            current = float(current)
        except:
            continue


        # تجاهل الأسعار غير المنطقية
        if current <= 0:
            continue

        if current > 10000:
            continue


        # إذا لا يوجد سعر أصلي
        if original is None:

            valid_pairs.append(
                (
                    current,
                    None
                )
            )

            continue


        try:
            original = float(original)
        except:

            valid_pairs.append(
                (
                    current,
                    None
                )
            )

            continue


        # التحقق من السعر الأصلي
        if original <= 0:

            valid_pairs.append(
                (
                    current,
                    None
                )
            )

            continue


        if original > 10000:

            valid_pairs.append(
                (
                    current,
                    None
                )
            )

            continue


        # السعر الأصلي يجب أن يكون أعلى
        if original > current:

            discount_percent = (
                (
                    original - current
                )
                / original
            ) * 100


            # نتأكد من أن الخصم منطقي
            if 1 <= discount_percent <= 99:

                valid_pairs.append(
                    (
                        current,
                        original
                    )
                )

            else:

                valid_pairs.append(
                    (
                        current,
                        None
                    )
                )

        else:

            valid_pairs.append(
                (
                    current,
                    None
                )
            )


    if not valid_pairs:
        return None, None


    # ======================================
    # البحث عن التخفيض الحقيقي
    # ======================================

    discounted_pairs = []


    for current, original in valid_pairs:

        if (
            original is not None
            and original > current
        ):

            discount_percent = (
                (
                    original - current
                )
                / original
            ) * 100


            discounted_pairs.append(
                (
                    current,
                    original,
                    discount_percent
                )
            )


    # إذا توجد لعبة عليها تخفيض
    if discounted_pairs:

        # نرتب حسب السعر الأصلي
        discounted_pairs.sort(
            key=lambda x: x[1],
            reverse=True
        )


        current, original, discount = (
            discounted_pairs[0]
        )


        return current, original


    # ======================================
    # بدون تخفيض
    # ======================================

    normal_prices = []

    for current, original in valid_pairs:

        if current >= 1:

            normal_prices.append(
                current
            )


    if normal_prices:

        # نختار أعلى سعر منطقي
        return max(normal_prices), None


    return None, None


# ==========================================
# جلب جميع معلومات اللعبة
# ==========================================

def get_game_info(url):

    product_id = get_product_id(url)

    if not product_id:

        raise Exception(
            "تعذر استخراج Product ID"
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
    # محاولة جلب السعر من Purchase API
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
            "API ERROR:",
            repr(error)
        )


    # ======================================
    # جلب الأسعار من بيانات المنتج
    # ======================================

    try:

        product_pairs = find_price_pairs(
            product
        )

        price_pairs.extend(
            product_pairs
        )

    except Exception as error:

        print(
            "PRODUCT ERROR:",
            repr(error)
        )


    # ======================================
    # تحديد السعر النهائي
    # ======================================

    current_price, original_price = (
        determine_best_price(
            price_pairs
        )
    )


    if current_price is None:

        raise Exception(
            "تعذر استخراج السعر"
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
# استقبال رابط اللعبة
# ==========================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()


    # التأكد من أنه رابط Xbox
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


        # حساب السعر العراقي
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


    # استقبال الرسائل والروابط
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
