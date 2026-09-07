
import os
import re
import math
import json
import requests

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


BOT_TOKEN = os.getenv("BOT_TOKEN")

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def calculate_price(price):
    if price <= 25:
        return 3000

    if price <= 50:
        return 4000

    return math.ceil(price / 100) * 6000


def get_product_id(url):
    match = re.search(r"/([A-Z0-9]{12})(?:[/?]|$)", url.upper())

    if match:
        return match.group(1)

    return None


def find_price(data):
    if isinstance(data, dict):
        # البحث عن السعر الحالي أولاً
        for key in [
            "Price",
            "price",
            "CurrentPrice",
            "currentPrice",
            "SalePrice",
            "salePrice"
        ]:
            value = data.get(key)

            if isinstance(value, (int, float)):
                return float(value)

            if isinstance(value, str):
                cleaned = value.replace("₺", "").replace("TL", "").strip()
                cleaned = cleaned.replace(".", "").replace(",", ".")

                try:
                    return float(cleaned)
                except:
                    pass

        for value in data.values():
            result = find_price(value)

            if result is not None:
                return result

    elif isinstance(data, list):
        for item in data:
            result = find_price(item)

            if result is not None:
                return result

    return None


def get_title(data):
    if isinstance(data, dict):

        for key in [
            "ProductTitle",
            "productTitle",
            "Title",
            "title",
            "Name",
            "name"
        ]:
            value = data.get(key)

            if isinstance(value, str) and len(value) > 1:
                return value

        for value in data.values():
            result = get_title(value)

            if result:
                return result

    elif isinstance(data, list):
        for item in data:
            result = get_title(item)

            if result:
                return result

    return None


def get_xbox_game(url):

    product_id = get_product_id(url)

    if not product_id:
        raise Exception("ماكدر أطلع ID اللعبة من الرابط")

    api_url = (
        "https://displaycatalog.mp.microsoft.com/v7.0/products"
        f"?bigIds={product_id}"
        "&market=TR"
        "&languages=tr-tr"
        "&MS-CV=DGU1mcuYo0WMMp"
    )

    response = requests.get(
        api_url,
        headers=HEADERS,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    products = data.get("Products", [])

    if not products:
        raise Exception("اللعبة غير موجودة")

    product = products[0]

    title = (
        product.get("LocalizedProperties", [{}])[0]
        .get("ProductTitle")
    )

    price = None
    original_price = None
    discount = 0

    market_properties = product.get("MarketProperties", [])

    if market_properties:

        market = market_properties[0]

        price_data = market.get("Price", {})

        current_price = price_data.get("MSRP")

        if current_price is not None:
            price = float(current_price)

        sale_price = price_data.get("SalePrice")

        if sale_price is not None:
            sale_price = float(sale_price)

            if sale_price > 0 and sale_price < price:
                original_price = price
                price = sale_price

                discount = price_data.get(
                    "DiscountPercentage",
                    0
                )

    if price is None:
        raise Exception("ماكدر أطلع سعر اللعبة")

    return title, price, original_price, discount


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🎮 SA STORE Price Bot 🇹🇷\n\n"
        "دزلي رابط أي لعبة من Xbox التركي."
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):

    url = update.message.text.strip()

    if "xbox.com" not in url.lower():

        await update.message.reply_text(
            "❌ دزلي رابط لعبة من Xbox Store."
        )

        return

    message = await update.message.reply_text(
        "🔎 جاري فحص اللعبة والسعر الحالي..."
    )

    try:

        game_name, try_price, original_price, discount = get_xbox_game(url)

        iq_price = calculate_price(try_price)

        text = (
            f"🎮 {game_name}\n\n"
            f"🇹🇷 السعر الحالي: ₺{try_price:.2f}\n"
        )

        if original_price:
            text += (
                f"🏷️ السعر الأصلي: ₺{original_price:.2f}\n"
                f"🔥 التخفيض: %{discount}\n"
            )

        text += (
            f"\n💰 سعر SA STORE: {iq_price:,} دينار عراقي"
        )

        await message.edit_text(text)

    except Exception as e:

        print("ERROR:", e)

        await message.edit_text(
            "❌ صار خطأ أثناء جلب معلومات اللعبة.\n"
            "تأكد من أن الرابط رابط لعبة صحيح من Xbox Store."
        )


def main():

    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN غير موجود في Environment Variables"
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        CommandHandler("start", start)
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
