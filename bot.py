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
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}


# =========================================================
# SESSION
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
        value.replace("₺", "")
        .replace("TRY", "")
        .replace("TL", "")
        .replace("\xa0", "")
        .replace(" ", "")
        .strip()
    )


    # مثال:
    # 1.999,00

    if "," in value and "." in value:

        if value.rfind(",") > value.rfind("."):

            value = value.replace(".", "")
            value = value.replace(",", ".")

        else:

            value = value.replace(",", "")


    # مثال:
    # 999,00

    elif "," in value:

        value = value.replace(",", ".")


    try:
        return float(value)

    except Exception:
        return None


# =========================================================
# استخراج رقم من قيمة
# =========================================================

def extract_number(value):

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
            "price",

            "FormattedPrice",
            "formattedPrice"
        ]


        for key in priority_keys:

            if key in value:

                result = extract_number(
                    value[key]
                )

                if result is not None:

                    return result


    return None


# =========================================================
# جلب بيانات المنتج من Microsoft
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
            "لم يتم العثور على معلومات اللعبة"
        )


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


    return "لعبة"


# =========================================================
# جلب بيانات الأسعار من Microsoft Purchase API
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


    print(
        "PURCHASE STATUS:",
        response.status_code
    )


    response.raise_for_status()


    return response.json()


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

    "PurchasePrice",
    "purchasePrice"
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
# فحص هل البيانات تركية
# =========================================================

def is_turkish_currency(data):

    if not isinstance(data, dict):
        return True


    currency_keys = [

        "CurrencyCode",
        "currencyCode",

        "Currency",
        "currency"
    ]


    for key in currency_keys:

        if key in data:

            value = data[key]


            if isinstance(value, str):

                value = value.upper().strip()


                if value in [
                    "TRY",
                    "TL",
                    "₺"
                ]:

                    return True


                # إذا كانت عملة ثانية نرفضها
                if len(value) == 3:

                    return False


    return True


# =========================================================
# استخراج السعر الحالي والأصلي من نفس الـ object
# =========================================================

def extract_price_pair_from_object(data):

    if not isinstance(data, dict):

        return None


    # ==========================================
    # إذا العملة واضحة وليست تركية
    # ==========================================

    if not is_turkish_currency(data):

        return None


    current = None
    original = None


    # ==========================================
    # السعر الحالي
    # ==========================================

    for key in CURRENT_PRICE_KEYS:

        if key in data:

            value = extract_number(
                data[key]
            )


            if value is not None and value > 0:

                current = value
                break


    # ==========================================
    # السعر الأصلي
    # ==========================================

    for key in ORIGINAL_PRICE_KEYS:

        if key in data:

            value = extract_number(
                data[key]
            )


            if value is not None and value > 0:

                original = value
                break


    # ==========================================
    # بعض Microsoft objects تحتوي Price object
    # ==========================================

    if current is None and "Price" in data:

        price_data = data["Price"]


        if isinstance(price_data, dict):

            for key in CURRENT_PRICE_KEYS:

                if key in price_data:

                    value = extract_number(
                        price_data[key]
                    )


                    if value is not None and value > 0:

                        current = value
                        break


            for key in ORIGINAL_PRICE_KEYS:

                if key in price_data:

                    value = extract_number(
                        price_data[key]
                    )


                    if value is not None and value > 0:

                        original = value
                        break


    # ==========================================
    # بعض البيانات تستخدم UnitPrice فقط
    # ==========================================

    if current is None:

        simple_keys = [

            "Price",
            "price",

            "Amount",
            "amount"
        ]


        for key in simple_keys:

            if key in data:

                value = extract_number(
                    data[key]
                )


                if value is not None and value > 0:

                    current = value
                    break


    if current is None:

        return None


    return (
        current,
        original
    )


# =========================================================
# البحث داخل بيانات Microsoft
# =========================================================

def find_price_pairs(data, results=None):

    if results is None:

        results = []


    if isinstance(data, dict):


        pair = extract_price_pair_from_object(
            data
        )


        if pair:

            results.append(pair)


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


# =========================================================
# تنظيف الأسعار
# =========================================================

def clean_price_pairs(pairs):

    cleaned = []


    for current, original in pairs:


        try:

            current = float(current)

        except Exception:

            continue


        # ==========================================
        # تجاهل الأسعار غير المنطقية
        # ==========================================

        if current <= 0:

            continue


        if current > 50000:

            continue


        # منع أسعار التجربة الوهمية
        # مثل 0 أو قيم صغيرة جداً
        #
        # ملاحظة: ما نرفض أقل من 5
        # لأن بعض الألعاب فعلاً رخيصة


        # ==========================================
        # السعر الأصلي
        # ==========================================

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


                # ==================================
                # منع خصم 99% و 100% الوهمي
                # ==================================

                if discount >= 99:

                    original = None


        cleaned.append(
            (
                round(current, 2),
                round(original, 2)
                if original is not None
                else None
            )
        )


    return cleaned


# =========================================================
# اختيار أفضل زوج أسعار
# =========================================================

def determine_best_price(pairs):

    pairs = clean_price_pairs(
        pairs
    )


    if not pairs:

        return None, None


    # =====================================================
    # 1 - نبحث عن التخفيضات الحقيقية
    # =====================================================

    discounted_pairs = []


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


                discounted_pairs.append(
                    (
                        current,
                        original
                    )
                )


    # =====================================================
    # إذا وجدنا تخفيضات
    # =====================================================

    if discounted_pairs:


        counter = Counter(
            discounted_pairs
        )


        # الأكثر تكراراً
        best_pair = counter.most_common(
            1
        )[0][0]


        return (
            best_pair[0],
            best_pair[1]
        )


    # =====================================================
    # 2 - بدون تخفيض
    # =====================================================

    normal_prices = []


    for current, original in pairs:

        if current is not None:

            normal_prices.append(
                current
            )


    if not normal_prices:

        return None, None


    counter = Counter(
        normal_prices
    )


    # الأكثر تكراراً
    best_price = counter.most_common(
        1
    )[0][0]


    return (
        best_price,
        None
    )


# =========================================================
# جلب السعر من الصفحة التركية كـ Fallback
# =========================================================

def get_price_from_turkish_page(product_id):

    url = (
        "https://www.xbox.com/tr-tr/games/store/"
        f"{product_id}"
    )


    response = SESSION.get(
        url,
        timeout=30,
        allow_redirects=True
    )


    if response.status_code != 200:

        print(
            "PAGE STATUS:",
            response.status_code
        )

        return []


    html = response.text


    pairs = []


    # =====================================================
    # البحث عن السعر التركي فقط
    # =====================================================

    prices = re.findall(
        r'([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{2})?)\s*₺',
        html
    )


    converted = []


    for price_text in prices:

        price = to_float(
            price_text
        )


        if price is not None:

            if (
                price > 0
                and price < 50000
            ):

                converted.append(
                    round(price, 2)
                )


    # إزالة التكرار
    converted = list(
        dict.fromkeys(converted)
    )


    # إذا لقينا سعر واحد
    if len(converted) == 1:

        pairs.append(
            (
                converted[0],
                None
            )
        )


    # إذا لقينا سعرين، الأصغر غالباً الحالي
    elif len(converted) == 2:


        low = min(converted)
        high = max(converted)


        discount = (
            (high - low)
            / high
        ) * 100


        if discount < 99:

            pairs.append(
                (
                    low,
                    high
                )
            )


    return pairs


# =========================================================
# جلب معلومات اللعبة كاملة
# =========================================================

def get_game_info(url):


    # =====================================================
    # استخراج Product ID
    # =====================================================

    product_id = get_product_id(
        url
    )


    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )


    print(
        "PRODUCT ID:",
        product_id
    )


    # =====================================================
    # بيانات اللعبة
    # =====================================================

    product = get_product_data(
        product_id
    )


    # =====================================================
    # الاسم
    # =====================================================

    game_name = get_game_name(
        product
    )


    print(
        "GAME:",
        game_name
    )


    all_pairs = []


    # =====================================================
    # 1 - Purchase API
    # المصدر الرئيسي للسعر
    # =====================================================

    try:


        purchase_data = get_purchase_data(
            product_id
        )


        purchase_pairs = find_price_pairs(
            purchase_data
        )


        print(
            "PURCHASE PAIRS:",
            purchase_pairs
        )


        all_pairs.extend(
            purchase_pairs
        )


    except Exception as error:


        print(
            "PURCHASE ERROR:",
            repr(error)
        )


    # =====================================================
    # 2 - صفحة Xbox التركية
    # Fallback فقط
    # =====================================================

    if not all_pairs:


        try:


            page_pairs = get_price_from_turkish_page(
                product_id
            )


            print(
                "PAGE PAIRS:",
                page_pairs
            )


            all_pairs.extend(
                page_pairs
            )


        except Exception as error:


            print(
                "PAGE ERROR:",
                repr(error)
            )


    # =====================================================
    # اختيار السعر النهائي
    # =====================================================

    current_price, original_price = (
        determine_best_price(
            all_pairs
        )
    )


    if current_price is None:

        raise Exception(
            "ماكدر أطلع سعر اللعبة من Microsoft"
        )


    print(
        "FINAL PRICE:",
        current_price
    )


    print(
        "ORIGINAL PRICE:",
        original_price
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

        "🎮 SA STORE Price Bot 🇹🇷\n\n"
        "دزلي رابط أي لعبة من Xbox Store "
        "وأطلعلك سعرها وسعر SA STORE 💰"
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
    # التأكد من الرابط
    # =====================================================

    if "xbox.com" not in text.lower():

        await update.message.reply_text(

            "❌ دزلي رابط لعبة من Xbox Store فقط."
        )

        return


    # =====================================================
    # رسالة الانتظار
    # =====================================================

    processing_message = (
        await update.message.reply_text(

            "⏳ جاري البحث عن اللعبة..."
        )
    )


    try:


        # =================================================
        # تشغيل requests خارج Event Loop
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


        turkey_price_text = (
            format_turkish_price(
                turkey_price
            )
        )


        store_price_text = (
            format_store_price(
                store_price
            )
        )


        # =================================================
        # اللعبة عليها تخفيض
        # =================================================

        if (
            original_price is not None
            and original_price > turkey_price
        ):


            original_price_text = (
                format_turkish_price(
                    original_price
                )
            )


            discount_percent = round(

                (
                    original_price
                    - turkey_price
                )
                / original_price
                * 100
            )


            result = (

                f"🎮 {game_name}\n\n"

                f"🔥 اللعبة عليها تخفيض!\n\n"

                f"📉 نسبة الخصم: "
                f"{discount_percent}%\n\n"

                f"❌ السعر الأصلي: "
                f"{original_price_text} ₺\n"

                f"🇹🇷 السعر الحالي: "
                f"{turkey_price_text} ₺\n\n"

                f"━━━━━━━━━━━━━━\n\n"

                f"💰 سعر SA STORE: "
                f"{store_price_text} 🇮🇶"
            )


        # =================================================
        # بدون تخفيض
        # =================================================

        else:


            result = (

                f"🎮 {game_name}\n\n"

                f"🇹🇷 السعر الحالي: "
                f"{turkey_price_text} ₺\n\n"

                f"━━━━━━━━━━━━━━\n\n"

                f"💰 سعر SA STORE: "
                f"{store_price_text} 🇮🇶"
            )


        await processing_message.edit_text(
            result
        )


    except Exception as error:


        print(
            "\n========== ERROR =========="
        )


        print(
            repr(error)
        )


        print(
            "===========================\n"
        )


        await processing_message.edit_text(

            "❌ صار خطأ أثناء جلب معلومات اللعبة.\n\n"

            "جرب رابط ثاني، وإذا تكرر الخطأ "
            "دزلي صورة من الـ Console."
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
