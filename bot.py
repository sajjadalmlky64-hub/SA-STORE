import os
import re
import math
import asyncio
import requests

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
# REQUEST SESSION
# =========================================================

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# =========================================================
# حساب سعر SA STORE
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
# استخراج Product ID من رابط Xbox
# =========================================================

def get_product_id(url):

    url = url.upper()

    matches = re.findall(
        r"(?<![A-Z0-9])([A-Z0-9]{12})(?![A-Z0-9])",
        url
    )

    if matches:
        return matches[-1]

    return None


# =========================================================
# تحويل النص إلى رقم
# =========================================================

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

    # مثال:
    # 1.299,00
    if "," in value and "." in value:

        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "")
            value = value.replace(",", ".")

        else:
            value = value.replace(",", "")

    # مثال:
    # 299,00
    elif "," in value:
        value = value.replace(",", ".")

    try:
        return float(value)

    except ValueError:
        return None


# =========================================================
# استخراج قيمة السعر من أي شكل
# =========================================================

def extract_price_value(value):

    if value is None:
        return None

    if isinstance(value, (int, float, str)):
        return to_float(value)

    if isinstance(value, dict):

        priority_keys = [
            "Amount",
            "amount",
            "Value",
            "value",
            "Price",
            "price"
        ]

        for key in priority_keys:

            if key in value:

                result = extract_price_value(
                    value[key]
                )

                if result is not None:
                    return result

    return None


# =========================================================
# أسماء السعر الحالي
# =========================================================

CURRENT_PRICE_KEYS = [
    "SalePrice",
    "salePrice",

    "DiscountPrice",
    "discountPrice",

    "CurrentPrice",
    "currentPrice",

    "UnitPrice",
    "unitPrice",

    "SellingPrice",
    "sellingPrice",

    "Price",
    "price"
]


# =========================================================
# أسماء السعر الأصلي
# =========================================================

ORIGINAL_PRICE_KEYS = [
    "ListPrice",
    "listPrice",

    "MSRP",
    "msrp",

    "OriginalPrice",
    "originalPrice",

    "RegularPrice",
    "regularPrice",

    "BasePrice",
    "basePrice"
]


# =========================================================
# البحث عن أزواج الأسعار
# =========================================================

def find_price_pairs(data, results=None):

    if results is None:
        results = []

    if isinstance(data, dict):

        current_price = None
        original_price = None


        # -----------------------------------------
        # السعر الحالي
        # -----------------------------------------

        for key in CURRENT_PRICE_KEYS:

            if key in data:

                value = extract_price_value(
                    data[key]
                )

                if value is not None and value > 0:
                    current_price = value
                    break


        # -----------------------------------------
        # السعر الأصلي
        # -----------------------------------------

        for key in ORIGINAL_PRICE_KEYS:

            if key in data:

                value = extract_price_value(
                    data[key]
                )

                if value is not None and value > 0:
                    original_price = value
                    break


        # -----------------------------------------
        # إضافة الزوج فقط إذا كان منطقي
        # -----------------------------------------

        if current_price:

            if original_price:

                if original_price >= current_price:

                    results.append(
                        (
                            current_price,
                            original_price
                        )
                    )

            else:

                results.append(
                    (
                        current_price,
                        None
                    )
                )


        # -----------------------------------------
        # البحث داخل البيانات
        # -----------------------------------------

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
# جلب بيانات اللعبة من Microsoft Display Catalog
# =========================================================

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

    response = SESSION.get(
        api_url,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()


    product = data.get("Product")


    if not product:

        products = data.get(
            "Products",
            []
        )

        if products:
            product = products[0]


    if not product:

        raise Exception(
            "ما تم العثور على معلومات اللعبة"
        )


    return product


# =========================================================
# جلب الأسعار من Microsoft Purchase API
# =========================================================

def get_purchase_data(product_id):

    api_url = (
        "https://purchase.mp.microsoft.com/"
        "v9.0/users/me/availability"
    )

    params = {
        "market": "TR",
        "languages": "tr-TR",
        "productIds": product_id
    }

    response = SESSION.get(
        api_url,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# استخراج اسم اللعبة
# =========================================================

def get_game_name(product):

    localized = product.get(
        "LocalizedProperties",
        []
    )


    # نحاول التركي أولاً
    for item in localized:

        title = item.get(
            "ProductTitle"
        )

        if title:
            return title


    # بديل
    title = product.get(
        "ProductTitle"
    )

    if title:
        return title


    raise Exception(
        "ماكدر أطلع اسم اللعبة"
    )


# =========================================================
# تنظيف الأسعار غير المنطقية
# =========================================================

def clean_price_pairs(price_pairs):

    cleaned = []

    for current, original in price_pairs:

        if current is None:
            continue

        try:

            current = float(current)

        except Exception:
            continue


        # سعر غير منطقي
        if current <= 0:
            continue


        # أسعار Xbox التركية ما لازم تكون أرقام خرافية
        if current > 20000:
            continue


        if original is not None:

            try:

                original = float(original)

            except Exception:

                original = None


        if original is not None:

            if original <= 0:
                original = None

            elif original > 20000:
                original = None


        # -----------------------------------------
        # إذا السعر الأصلي أصغر من الحالي
        # نخليه بدون تخفيض
        # -----------------------------------------

        if (
            original is not None
            and original < current
        ):

            original = None


        # -----------------------------------------
        # منع حالات الخصم الوهمية
        # -----------------------------------------

        if (
            original is not None
            and original > current
        ):

            discount = (
                (original - current)
                / original
            ) * 100


            # خصم 100% أو قريب جدًا غالباً بيانات خاطئة
            if discount >= 99:
                original = None


        cleaned.append(
            (
                current,
                original
            )
        )


    return cleaned


# =========================================================
# اختيار السعر الصحيح
# =========================================================

def determine_best_price(price_pairs):

    price_pairs = clean_price_pairs(
        price_pairs
    )


    if not price_pairs:

        return None, None


    # =====================================================
    # 1 - البحث عن زوج تخفيض حقيقي
    # =====================================================

    discounted = []


    for current, original in price_pairs:

        if (
            original is not None
            and original > current
        ):

            discount_percent = (
                (original - current)
                / original
            ) * 100


            # خصم منطقي فقط
            if 1 <= discount_percent < 99:

                discounted.append(
                    (
                        current,
                        original,
                        discount_percent
                    )
                )


    # =====================================================
    # إذا وجدنا تخفيض
    # =====================================================

    if discounted:

        # إزالة التكرار
        unique = {}

        for current, original, discount in discounted:

            key = (
                round(current, 2),
                round(original, 2)
            )

            unique[key] = (
                current,
                original,
                discount
            )


        discounted = list(
            unique.values()
        )


        # نختار الزوج الأكثر تكراراً منطقياً:
        # الأفضل يكون السعر الأصلي أكبر من الحالي
        #
        # الترتيب حسب السعر الأصلي
        # لأن السعر الأصلي الحقيقي غالباً هو MSRP للعبة

        discounted.sort(
            key=lambda x: (
                x[1],
                x[0]
            ),
            reverse=True
        )


        current, original, _ = discounted[0]

        return current, original


    # =====================================================
    # 2 - بدون تخفيض
    # =====================================================

    current_prices = []


    for current, original in price_pairs:

        if current is not None:

            current_prices.append(
                current
            )


    if not current_prices:

        return None, None


    # إزالة التكرار
    current_prices = sorted(
        set(
            round(price, 2)
            for price in current_prices
        )
    )


    # نختار السعر الأكثر ظهوراً
    # وإذا ما نكدر نعرف التكرار نأخذ الأعلى
    # لأن الأسعار الصغيرة جداً غالباً DLC أو عناصر داخل اللعبة

    return current_prices[-1], None


# =========================================================
# جلب كل معلومات اللعبة
# =========================================================

def get_game_info(url):


    # =====================================================
    # Product ID
    # =====================================================

    product_id = get_product_id(
        url
    )


    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )


    # =====================================================
    # بيانات اللعبة
    # =====================================================

    product = get_product_data(
        product_id
    )


    game_name = get_game_name(
        product
    )


    all_price_pairs = []


    # =====================================================
    # 1 - Purchase API
    # =====================================================

    try:

        purchase_data = get_purchase_data(
            product_id
        )


        purchase_pairs = find_price_pairs(
            purchase_data
        )


        all_price_pairs.extend(
            purchase_pairs
        )


    except Exception as error:

        print(
            "PURCHASE API ERROR:",
            repr(error)
        )


    # =====================================================
    # 2 - Display Catalog
    # =====================================================

    try:

        product_pairs = find_price_pairs(
            product
        )


        all_price_pairs.extend(
            product_pairs
        )


    except Exception as error:

        print(
            "PRODUCT DATA ERROR:",
            repr(error)
        )


    # =====================================================
    # تحديد السعر
    # =====================================================

    current_price, original_price = (
        determine_best_price(
            all_price_pairs
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
# تنسيق السعر التركي
# =========================================================

def format_turkish_price(price):

    return (
        f"{price:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


# =========================================================
# تنسيق سعر SA STORE
# =========================================================

def format_store_price(price):

    price = int(price)

    thousands = price // 1000


    if price % 1000 == 0:

        return f"{thousands} ألف"


    return (
        f"{price:,} دينار"
        .replace(",", ".")
    )


# =========================================================
# أمر START
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


    # =====================================================
    # التأكد من Xbox
    # =====================================================

    if "xbox.com" not in text.lower():

        await update.message.reply_text(
            "يرجى إرسال رابط لعبة من Xbox Store"
        )

        return


    # =====================================================
    # رسالة الانتظار
    # =====================================================

    processing_message = await update.message.reply_text(
        "⏳ جاري البحث عن اللعبة..."
    )


    try:


        # =================================================
        # تشغيل requests خارج الـ event loop
        # حتى البوت ما يوقف أثناء البحث
        # =================================================

        (
            game_name,
            turkey_price,
            original_price
        ) = await asyncio.to_thread(
            get_game_info,
            text
        )


        # =================================================
        # حساب سعر SA STORE
        # =================================================

        store_price = calculate_price(
            turkey_price
        )


        store_price_text = format_store_price(
            store_price
        )


        # =================================================
        # اللعبة عليها تخفيض
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
                f"💰 سعر SA STORE: "
                f"{store_price_text} 🇮🇶"
            )


        # =================================================
        # بدون تخفيض
        # =================================================

        else:


            result = (
                f"🎮 {game_name}\n\n"
                f"💰 سعر SA STORE: "
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
            "تأكد أن الرابط صحيح وجرب مرة ثانية."
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


    # =====================================================
    # START
    # =====================================================

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    # =====================================================
    # استقبال الروابط
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_link
        )
    )


    print(
        "SA STORE Bot is running..."
    )


    app.run_polling()


# =========================================================
# تشغيل البرنامج
# =========================================================

if __name__ == "__main__":

    main()
