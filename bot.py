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
# جلب معلومات اللعبة من Microsoft
# ==========================================

def get_product_data(product_id):

    api_url = (
        f"https://displaycatalog.mp.microsoft.com/"
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
# تحويل القيمة إلى رقم
# ==========================================

def to_float(value):

    if value is None:
        return None

    try:
        return float(value)

    except (ValueError, TypeError):
        pass

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
# استخراج السعر بشكل متكرر
# ==========================================

def find_price_recursive(data):

    if isinstance(data, dict):

        priority_keys = [
            "ListPrice",
            "MSRP",
            "OriginalPrice",
            "UnitPrice",
            "Price"
        ]

        for key in priority_keys:

            if key in data:

                value = data[key]

                if isinstance(value, (int, float)):

                    if value > 0:
                        return float(value)

                elif isinstance(value, str):

                    number = to_float(value)

                    if number and number > 0:
                        return number

                elif isinstance(value, dict):

                    result = find_price_recursive(value)

                    if result:
                        return result

        for value in data.values():

            result = find_price_recursive(value)

            if result:
                return result

    elif isinstance(data, list):

        for item in data:

            result = find_price_recursive(item)

            if result:
                return result

    return None


# ==========================================
# جلب سعر اللعبة من Microsoft Store API
# ==========================================

def get_product_price(product_id):

    api_url = "https://purchase.mp.microsoft.com/v9.0/users/me/availability"

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

    if response.status_code == 200:

        try:
            data = response.json()

            price = find_price_recursive(data)

            if price:
                return price

        except Exception:
            pass

    return None


# ==========================================
# استخراج السعر من صفحة Xbox
# ==========================================

def get_price_from_store_page(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    html = response.text

    patterns = [

        r'"price"\s*:\s*"([0-9.,]+)"',

        r'"listPrice"\s*:\s*"([0-9.,]+)"',

        r'"ListPrice"\s*:\s*([0-9.,]+)',

        r'([0-9]{1,5}(?:[.,][0-9]{1,2})?)\s*₺',

        r'₺\s*([0-9]{1,5}(?:[.,][0-9]{1,2})?)'
    ]

    prices = []

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

    if prices:
        return min(prices)

    return None


# ==========================================
# جلب كل معلومات اللعبة
# ==========================================

def get_game_info(url):

    product_id = get_product_id(url)

    if not product_id:
        raise Exception("ماكدر أطلع Product ID من الرابط")

    product = get_product_data(product_id)

    game_name = get_game_name(product)

    price = get_product_price(product_id)

    if not price:
        price = find_price_recursive(product)

    if not price:
        price = get_price_from_store_page(url)

    if not price:
        raise Exception("ماكدر أطلع سعر اللعبة")

    return game_name, price


# ==========================================
# أمر Start
# ==========================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = (
        "🎮 SA STORE Price Bot 🇹🇷\n\n"
        "دزلي رابط أي لعبة من Xbox Store "
        "وأجيبلك السعر التركي الحالي.\n\n"
        "بعدها أحسبلك سعر SA STORE 💰"
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
        "⏳ جاري البحث عن اللعبة والسعر..."
    )

    try:

        game_name, turkey_price = get_game_info(text)

        store_price = calculate_price(turkey_price)

        turkey_price_text = (
            f"{turkey_price:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

        store_price_text = (
            f"{store_price:,}"
            .replace(",", ".")
        )

        result = (
            f"🎮 {game_name}\n\n"
            f"🇹🇷 السعر التركي: {turkey_price_text} ₺\n"
            f"💰 سعر SA STORE: {store_price_text} دينار عراقي"
        )

        await processing_message.edit_text(result)

    except Exception as error:

        print("ERROR:", error)

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
            filters.TEXT & ~filters.COMMAND,
            handle_link
        )
    )

    print("SA STORE Bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()
