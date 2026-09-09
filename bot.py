import os
import re
import math
import asyncio
import requests

from collections import Counter

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)


# =========================================================
# BOT TOKEN
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")


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

    # مثال: 2.099,00
    if "," in value and "." in value:

        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "")
            value = value.replace(",", ".")

        else:
            value = value.replace(",", "")

    # مثال: 524,75
    elif "," in value:

        value = value.replace(",", ".")

    try:
        return float(value)

    except Exception:
        return None


# =========================================================
# استخراج قيمة سعر من dict أو نص
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

                result = extract_price(value[key])

                if result is not None:
                    return result

    return None


# =========================================================
# جلب بيانات المنتج
# =========================================================

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

    response = SESSION.get(
        url,
        params=params,
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


# =========================================================
# استخراج اسم اللعبة
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

    return "لعبة"


# =========================================================
# أسماء مفاتيح الأسعار
# =========================================================

CURRENT_KEYS = [
    "SalePrice",
    "salePrice",

    "DiscountPrice",
    "discountPrice",

    "CurrentPrice",
    "currentPrice",

    "UnitPrice",
    "unitPrice",

    "SellingPrice",
    "sellingPrice"
]


ORIGINAL_KEYS = [
    "ListPrice",
    "listPrice",

    "MSRP",
    "msrp",

    "OriginalPrice",
    "originalPrice",

    "RegularPrice",
    "regularPrice"
]


# =========================================================
# استخراج أزواج الأسعار
# مهم: السعر الحالي والأصلي من نفس الـ object
# =========================================================

def find_price_pairs(data, results=None):

    if results is None:
        results = []

    if isinstance(data, dict):

        current = None
        original = None


        # ---------------------------------------------
        # السعر الحالي
        # ---------------------------------------------

        for key in CURRENT_KEYS:

            if key in data:

                current = extract_price(
                    data[key]
                )

                if current is not None:
                    break


        # ---------------------------------------------
        # السعر الأصلي
        # ---------------------------------------------

        for key in ORIGINAL_KEYS:

            if key in data:

                original = extract_price(
                    data[key]
                )

                if original is not None:
                    break


        # ---------------------------------------------
        # إضافة زوج صحيح فقط
        # ---------------------------------------------

        if current is not None:

            if current > 0:

                if (
                    original is not None
                    and original > current
                ):

                    results.append(
                        (current, original)
                    )

                else:

                    results.append(
                        (current, None)
                    )


        # البحث داخل العناصر
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


# =========================================================
# تنظيف الأسعار
# =========================================================

def clean_pairs(pairs):

    cleaned = []

    for current, original in pairs:

        try:

            current = float(current)

        except Exception:

            continue


        # تجاهل الأسعار الغريبة
        if current <= 0 or current > 50000:
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


                # تجاهل خصومات غير منطقية
                if discount >= 99:
                    original = None


        cleaned.append(
            (current, original)
        )

    return cleaned


# =========================================================
# اختيار أفضل سعر
# =========================================================

def determine_price(pairs):

    pairs = clean_pairs(pairs)

    if not pairs:
        return None, None


    # ==============================================
    # أولاً: نبحث عن تخفيضات حقيقية
    # ==============================================

    discounted = []

    for current, original in pairs:

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

        # الأكثر تكراراً هو غالباً السعر الصحيح
        counter = Counter(discounted)

        best_pair = counter.most_common(1)[0][0]

        return best_pair[0], best_pair[1]


    # ==============================================
    # بدون تخفيض
    # ==============================================

    prices = []

    for current, original in pairs:

        if current is not None:

            prices.append(
                round(current, 2)
            )


    if not prices:
        return None, None


    # السعر الأكثر تكراراً
    counter = Counter(prices)

    best_price = counter.most_common(1)[0][0]

    return best_price, None


# =========================================================
# جلب الأسعار من صفحة Xbox التركية
# =========================================================

def get_page_prices(product_id):

    url = (
        "https://www.xbox.com/tr-tr/games/store/"
        f"x/{product_id}"
    )

    response = SESSION.get(
        url,
        timeout=30,
        allow_redirects=True
    )

    if response.status_code != 200:
        return []

    html = response.text

    pairs = []


    # JSON patterns
    patterns = [

        (
            r'"salePrice"\s*:\s*"([0-9.,]+)"'
            r'.{0,500}'
            r'"(?:listPrice|originalPrice)"\s*:\s*"([0-9.,]+)"'
        ),

        (
            r'"currentPrice"\s*:\s*"([0-9.,]+)"'
            r'.{0,500}'
            r'"(?:listPrice|originalPrice)"\s*:\s*"([0-9.,]+)"'
        )
    ]


    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE | re.DOTALL
        )

        for current_text, original_text in matches:

            current = to_float(current_text)
            original = to_float(original_text)

            if (
                current is not None
                and original is not None
                and original > current
            ):

                pairs.append(
                    (current, original)
                )


    return pairs


# =========================================================
# جلب كل معلومات اللعبة
# =========================================================

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


    all_pairs = []


    # ==============================================
    # 1. بيانات المنتج
    # ==============================================

    try:

        product_pairs = find_price_pairs(
            product
        )

        all_pairs.extend(
            product_pairs
        )

    except Exception as error:

        print(
            "PRODUCT ERROR:",
            repr(error)
        )


    # ==============================================
    # 2. صفحة Xbox التركية
    # ==============================================

    try:

        page_pairs = get_page_prices(
            product_id
        )

        all_pairs.extend(
            page_pairs
        )

    except Exception as error:

        print(
            "PAGE ERROR:",
            repr(error)
        )


    # ==============================================
    # اختيار السعر
    # ==============================================

    current_price, original_price = (
        determine_price(
            all_pairs
        )
    )


    if current_price is None:

        raise Exception(
            "ماكدر أطلع سعر اللعبة"
        )


    return (
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
        ) = await asyncio.to_thread(
            get_game_info,
            text
        )


        # حساب السعر العراقي
        store_price = calculate_price(
            turkey_price
        )


        store_price_text = format_store_price(
            store_price
        )


        # ==========================================
        # اللعبة عليها تخفيض
        # ==========================================

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


            result = (
                f"🎮 {game_name}\n\n"
                f"🔥 اللعبة عليها تخفيض!\n\n"
                f"📉 نسبة الخصم: "
                f"{discount_percent}%\n\n"
                f"💰 سعر اللعبة: "
                f"{store_price_text} 🇮🇶"
            )


        # ==========================================
        # بدون تخفيض
        # ==========================================

        else:

            result = (
                f"🎮 {game_name}\n\n"
                f"💰 سعر اللعبة: "
                f"{store_price_text} 🇮🇶"
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


# =========================================================
# تشغيل البوت
# =========================================================

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


    app.run_polling()


# =========================================================
# تشغيل البرنامج
# =========================================================

if __name__ == "__main__":
    main()
