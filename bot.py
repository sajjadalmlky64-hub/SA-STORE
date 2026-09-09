import os
import re
import math
import requests
import html as html_lib

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)


BOT_TOKEN = os.getenv("BOT_TOKEN")


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
# حساب سعر SA STORE
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

    # من 201 إلى 249
    elif price <= 249:
        return 11000

    # من 250 إلى 260
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
# تحويل القيمة إلى رقم
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

    except ValueError:
        return None


# ==========================================
# جلب معلومات اللعبة من Microsoft
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
# البحث عن الأسعار داخل البيانات
# ==========================================

def find_all_prices(data, prices=None):

    if prices is None:
        prices = []

    if isinstance(data, dict):

        price_keys = [
            "ListPrice",
            "MSRP",
            "OriginalPrice",
            "UnitPrice",
            "Price",
            "SalePrice",
            "DiscountPrice"
        ]

        for key, value in data.items():

            if key in price_keys:

                if isinstance(value, (int, float)):

                    if value > 0:
                        prices.append(float(value))

                elif isinstance(value, str):

                    number = to_float(value)

                    if number is not None and number > 0:
                        prices.append(number)

                elif isinstance(value, dict):

                    find_all_prices(
                        value,
                        prices
                    )

            elif isinstance(value, (dict, list)):

                find_all_prices(
                    value,
                    prices
                )

    elif isinstance(data, list):

        for item in data:

            find_all_prices(
                item,
                prices
            )

    return prices


# ==========================================
# استخراج الأسعار من Microsoft Purchase API
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

    prices = find_all_prices(data)

    return sorted(
        list(set(prices))
    )


# ==========================================
# جلب صفحة Xbox
# هذه فقط لتاريخ انتهاء التخفيض
# ولا نستخدمها لاستخراج الأسعار
# ==========================================

def get_store_page(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    return response.text


# ==========================================
# استخراج مدة انتهاء التخفيض
# ==========================================

def get_discount_end_time(url):

    try:

        page = get_store_page(url)

        # تحويل HTML entities
        page = html_lib.unescape(page)

        # تحويل Unicode escapes الموجودة داخل الصفحة
        try:

            page = bytes(
                page,
                "utf-8"
            ).decode(
                "unicode_escape"
            )

        except Exception:
            pass

        # إزالة HTML tags
        text = re.sub(
            r"<[^>]+>",
            " ",
            page
        )

        # تنظيف المسافات
        text = re.sub(
            r"\s+",
            " ",
            text
        )

        # ----------------------------------
        # الأيام
        # مثال:
        # 1 gün içinde sona eriyor
        # ----------------------------------

        day_patterns = [

            r"(\d+)\s*gün\s*içinde\s*sona\s*eriyor",

            r"(\d+)\s*gun\s*icinde\s*sona\s*eriyor",

            r"(\d+)\s*gün.*?sona\s*eriyor",

            r"(\d+)\s*gun.*?sona\s*eriyor",
        ]

        for pattern in day_patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match:

                days = int(
                    match.group(1)
                )

                if days == 0:

                    return (
                        "ينتهي التخفيض اليوم ⏳"
                    )

                elif days == 1:

                    return (
                        "ينتهي التخفيض خلال يوم واحد ⏳"
                    )

                else:

                    return (
                        f"ينتهي التخفيض خلال "
                        f"{days} أيام ⏳"
                    )


        # ----------------------------------
        # الساعات
        # ----------------------------------

        hour_patterns = [

            r"(\d+)\s*saat\s*içinde\s*sona\s*eriyor",

            r"(\d+)\s*saat.*?sona\s*eriyor",
        ]

        for pattern in hour_patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE
            )

            if match:

                hours = int(
                    match.group(1)
                )

                if hours == 1:

                    return (
                        "ينتهي التخفيض خلال ساعة واحدة ⏳"
                    )

                return (
                    f"ينتهي التخفيض خلال "
                    f"{hours} ساعة ⏳"
                )


        return None


    except Exception as error:

        print(
            "DISCOUNT END ERROR:",
            repr(error)
        )

        return None


# ==========================================
# تحديد السعر الحالي والسعر الأصلي
# ==========================================

def determine_prices(prices):

    if not prices:
        return None, None

    prices = sorted(
        list(set(prices))
    )

    # سعر واحد فقط
    if len(prices) == 1:

        return prices[0], None


    current_price = prices[0]

    original_price = prices[-1]


    if original_price > current_price:

        return (
            current_price,
            original_price
        )


    return current_price, None


# ==========================================
# جلب كل معلومات اللعبة
# ==========================================

def get_game_info(url):

    product_id = get_product_id(url)

    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )


    # --------------------------------------
    # معلومات اللعبة
    # --------------------------------------

    product = get_product_data(
        product_id
    )

    game_name = get_game_name(
        product
    )


    prices = []


    # --------------------------------------
    # أولاً Microsoft Purchase API
    # --------------------------------------

    try:

        api_prices = get_prices_from_api(
            product_id
        )

        prices.extend(
            api_prices
        )

    except Exception as error:

        print(
            "API PRICE ERROR:",
            repr(error)
        )


    # --------------------------------------
    # ثانياً Product Data
    # --------------------------------------

    try:

        product_prices = find_all_prices(
            product
        )

        prices.extend(
            product_prices
        )

    except Exception as error:

        print(
            "PRODUCT PRICE ERROR:",
            repr(error)
        )


    # ======================================
    # مهم جداً:
    # لا نستخرج أسعار من HTML
    # لأن HTML كان يجيب أرقام خاطئة
    # مثل 3 ₺ و 64.755 ₺
    # ======================================


    prices = [

        price
        for price in prices
        if price is not None
        and price > 0

    ]


    prices = sorted(
        list(set(prices))
    )


    current_price, original_price = (
        determine_prices(prices)
    )


    if current_price is None:

        raise Exception(
            "ماكدر أطلع سعر اللعبة"
        )


    # --------------------------------------
    # استخراج انتهاء التخفيض فقط
    # --------------------------------------

    discount_end = None


    if (
        original_price is not None
        and original_price > current_price
    ):

        discount_end = get_discount_end_time(
            url
        )


    return (
        game_name,
        current_price,
        original_price,
        discount_end
    )


# ==========================================
# تنسيق السعر التركي
# ==========================================

def format_turkish_price(price):

    return (
        f"{price:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


# ==========================================
# تنسيق سعر SA STORE
# ==========================================

def format_store_price(price):

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

    message = (
        "🎮 SA STORE Price Bot 🇹🇷\n\n"
        "دزلي رابط أي لعبة من Xbox Store 🎮\n\n"
        "وأطلعلك:\n"
        "💰 سعر اللعبة\n"
        "🔥 نسبة التخفيض إذا موجودة\n"
        "⏳ وقت انتهاء التخفيض إذا متوفر\n"
        "🇮🇶 وسعر SA STORE"
    )

    await update.message.reply_text(
        message
    )


# ==========================================
# استقبال رابط Xbox
# ==========================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()


    if "xbox.com" not in text.lower():

        await update.message.reply_text(
            "❌ خطأ\n\n"
            "دزلي رابط لعبة من Xbox Store."
        )

        return


    processing_message = (
        await update.message.reply_text(
            "⏳ جاري البحث عن اللعبة..."
        )
    )


    try:

        (
            game_name,
            turkey_price,
            original_price,
            discount_end

        ) = get_game_info(
            text
        )


        # ----------------------------------
        # حساب سعر SA STORE
        # ----------------------------------

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


        # ==================================
        # اللعبة عليها تخفيض
        # ==================================

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

                f"❌ السعر الأصلي: "
                f"{original_price_text} ₺\n"

                f"🇹🇷 السعر الحالي: "
                f"{turkey_price_text} ₺\n"

            )


            # ------------------------------
            # انتهاء التخفيض
            # ------------------------------

            if discount_end:

                result += (
                    f"\n⌛ {discount_end}\n"
                )


            result += (

                f"\n━━━━━━━━━━━━━━\n\n"

                f"💰 سعر SA STORE: "
                f"{store_price_text} 🇮🇶"

            )


        # ==================================
        # بدون تخفيض
        # ==================================

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
            "ERROR:",
            repr(error)
        )


        await processing_message.edit_text(

            "❌ صار خطأ أثناء جلب معلومات اللعبة.\n\n"
            "تأكد أن الرابط صحيح وجرب مرة ثانية."

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


    app.add_handler(

        CommandHandler(
            "start",
            start
        )

    )


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


if __name__ == "__main__":
    main()
