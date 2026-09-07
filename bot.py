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
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"
}


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
    else:
        extra = price - 1000
        extra_steps = math.ceil(extra / 100)
        return 33000 + (extra_steps * 3000)


def get_product_id(url):

    url = url.split("?")[0].rstrip("/")

    matches = re.findall(
        r"(?<![A-Z0-9])([A-Z0-9]{12})(?![A-Z0-9])",
        url.upper()
    )

    if matches:
        return matches[-1]

    return None


def to_float(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):

        value = (
            value.replace("₺", "")
            .replace("TL", "")
            .replace("TRY", "")
            .replace("\xa0", "")
            .strip()
        )

        if "," in value and "." in value:
            value = value.replace(".", "").replace(",", ".")

        elif "," in value:
            value = value.replace(",", ".")

        try:
            return float(value)

        except ValueError:
            return None

    return None


def get_xbox_game(url):

    product_id = get_product_id(url)

    if not product_id:
        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )

    api_url = (
        "https://displaycatalog.mp.microsoft.com/"
        "v7.0/products"
    )

    params = {
        "bigIds": product_id,
        "market": "TR",
        "languages": "tr-TR",
        "fieldsTemplate": "details"
    }

    response = requests.get(
        api_url,
        params=params,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    products = data.get("Products", [])

    if not products:
        raise Exception(
            "ما تم العثور على اللعبة"
        )

    product = products[0]

    title = None

    localized = product.get(
        "LocalizedProperties",
        []
    )

    for item in localized:

        title = item.get("ProductTitle")

        if title:
            break

    if not title:
        title = product.get(
            "ProductTitle",
            "لعبة Xbox"
        )

    price = None

    market_properties = product.get(
        "MarketProperties",
        []
    )

    for market in market_properties:

        price_data = market.get(
            "Price",
            {}
        )

        if not isinstance(price_data, dict):
            continue

        sale_price = to_float(
            price_data.get("SalePrice")
        )

        msrp = to_float(
            price_data.get("MSRP")
            or price_data.get("ListPrice")
        )

        if (
            sale_price is not None
            and msrp is not None
            and sale_price < msrp
        ):
            price = sale_price
            break

        if sale_price is not None:
            price = sale_price

            if msrp is None:
                break

        if price is None and msrp is not None:
            price = msrp

        if price is None:

            current_price = to_float(
                price_data.get("CurrentPrice")
                or price_data.get("Price")
            )

            if current_price is not None:
                price = current_price

    if price is None:
        raise Exception(
            "تم العثور على اللعبة لكن ماكدر أطلع السعر التركي"
        )

    return title, price


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🎮 SA STORE Price Bot 🇹🇷\n\n"
        "دزلي رابط أي لعبة من Xbox Store "
        "وأحسبلك سعرها بالدينار العراقي 💰"
    )


async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    url = update.message.text.strip()

    if "xbox.com" not in url.lower():

        await update.message.reply_text(
            "❌ دزلي رابط لعبة صحيح من Xbox Store."
        )

        return

    message = await update.message.reply_text(
        "🔎 جاري فحص سعر اللعبة..."
    )

    try:

        game_name, try_price = get_xbox_game(url)

        iq_price = calculate_price(try_price)

        text = (
            f"🎮 اسم اللعبة:\n"
            f"{game_name}\n\n"
            f"💰 السعر: "
            f"{iq_price:,} دينار عراقي"
        )

        await message.edit_text(text)

    except Exception as e:

        print("ERROR:", repr(e))

        await message.edit_text(
            f"❌ صار خطأ:\n\n{str(e)}"
        )


def main():

    if not BOT_TOKEN:

        raise ValueError(
            "BOT_TOKEN غير موجود "
            "في Environment Variables"
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

    print(
        "SA STORE Bot is running..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
