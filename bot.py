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

    # من 201 إلى 249 = 11 ألف
    elif price <= 249:
        return 11000

    # من 250 إلى 260 = 12 ألف
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

    if "," in value and "." in value:

        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")

        else:
            value = value.replace(",", "")

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

                    if number and number > 0:
                        prices.append(number)

                elif isinstance(value, dict):

                    find_all_prices(value, prices)

            elif isinstance(value, (dict, list)):
                find_all_prices(value, prices)

    elif isinstance(data, list):

        for item in data:
            find_all_prices(item, prices)

    return prices


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

    prices = find_all_prices(data)

    return sorted(
        list(set(prices))
    )


# ==========================================
# جلب صفحة Xbox
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
# استخراج الأسعار من صفحة Xbox
# ==========================================

def get_prices_from_store_page(url):

    html = get_store_page(url)

    prices = []

    patterns = [

        r'"price"\s*:\s*"([0-9.,]+)"',

        r'"listPrice"\s*:\s*"([0-9.,]+)"',

        r'"salePrice"\s*:\s*"([0-9.,]+)"',

        r'"originalPrice"\s*:\s*"([0-9.,]+)"',

        r'"ListPrice"\s*:\s*"?([0-9.,]+)"?',

        r'"MSRP"\s*:\s*"?([0-9.,]+)"?',

        r'([0-9]{1,6}(?:[.,][0-9]{1,2})?)\s*₺',

        r'₺\s*([0-9]{1,6}(?:[.,][0-9]{1,2})?)'
    ]

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE
        )

        for match in matches:

            price = to_float(match)

            if price and price > 0:
                prices.append(price)

    return sorted(
        list(set(prices))
    )


# ==========================================
# تحديد السعر الحالي والسعر الأصلي
# ==========================================

def determine_prices(prices):

    if not prices:
        return None, None

    prices = sorted(prices)

    if len(prices) == 1:
        return prices[0], None

    current_price = prices[0]
    original_price = prices[-1]

    if original_price > current_price:
        return current_price, original_price

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

    product = get_product_data(product_id)

    game_name = get_game_name(product)

    prices = []


    # Microsoft Purchase API
    try:

        api_prices = get_prices_from_api(
            product_id
        )

        prices.extend(api_prices)

    except Exception as error:

        print(
            "API PRICE ERROR:",
            error
        )


    # Product Data
    try:

        product_prices = find_all_prices(
            product
        )

        prices.extend(product_prices)

    except Exception as error:

        print(
            "PRODUCT PRICE ERROR:",
            error
        )


    # صفحة Xbox
    try:

        page_prices = get_prices_from_store_page(
            url
        )

        prices.extend(page_prices)

    except Exception as error:

        print(
            "PAGE PRICE ERROR:",
            error
        )


    # تنظيف الأسعار
    prices = [
        price
        for price in prices
        if price and price > 0
    ]

    prices = sorted(
        list(set(prices))
    )


    current_price, original_price = (
        determine_prices(prices)
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

    thousands = price // 1000

    if price % 1000 == 0:
        return f"{thousands} ألف"

    return (
        f"{price:,} دينار"
        .replace(",", ".")
    )


# ==========================================
# أمر Start
# ==========================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = (
        "🎮 بوت أسعار الألعاب\n\n"
        "دزلي رابط أي لعبة من Xbox Store "
        "وأجيبلك اسم اللعبة وسعرها 💰"
    )

    await update.message.reply_text(message)


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


    processing_message = await update.message.reply_text(
        "⏳ جاري البحث عن اللعبة..."
    )


    try:

        (
            game_name,
            turkey_price,
            original_price
        ) = get_game_info(text)


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
        "Bot is running..."
    )


    app.run_polling()


if __name__ == "__main__":
    main()
