import os
import re
import math
import requests

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


BOT_TOKEN = os.getenv("BOT_TOKEN")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; Mobile) "
        "AppleWebKit/537.36 Chrome/120 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"
}


def calculate_price(price):
    if price <= 25:
        return 3000

    if price <= 50:
        return 4000

    return math.ceil(price / 100) * 6000


def get_product_id(url):
    url = url.split("?")[0].rstrip("/")

    # روابط Xbox الحديثة تحتوي على Product ID من 12 حرف
    match = re.search(r"/([A-Z0-9]{12})(?:/|$)", url.upper())

    if match:
        return match.group(1)

    return None


def to_float(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        value = value.strip()

        value = (
            value.replace("₺", "")
            .replace("TL", "")
            .replace("TRY", "")
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
        raise Exception("ماكدر أطلع Product ID من الرابط")

    api_url = "https://displaycatalog.mp.microsoft.com/v7.0/products"

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

    print("STATUS:", response.status_code)
    print("URL:", response.url)

    response.raise_for_status()

    data = response.json()

    print("DATA RECEIVED")

    products = data.get("Products", [])

    if not products:
        raise Exception(
            f"اللعبة غير موجودة في Xbox Catalog. ID: {product_id}"
        )

    product = products[0]

    # اسم اللعبة
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
        title = product.get("ProductTitle")

    if not title:
        title = "لعبة Xbox"

    # السعر
    price = None
    original_price = None
    discount = 0

    market_properties = product.get(
        "MarketProperties",
        []
    )

    print("MARKETS FOUND:", len(market_properties))

    for market in market_properties:

        price_data = market.get("Price", {})

        if not isinstance(price_data, dict):
            continue

        msrp = to_float(
            price_data.get("MSRP")
            or price_data.get("ListPrice")
        )

        sale_price = to_float(
            price_data.get("SalePrice")
        )

        current_discount = price_data.get(
            "DiscountPercentage",
            0
        )

        try:
            current_discount = float(current_discount)
        except:
            current_discount = 0

        if (
            sale_price is not None
            and msrp is not None
            and sale_price < msrp
        ):
            price = sale_price
            original_price = msrp
            discount = current_discount
            break

        elif msrp is not None:
            price = msrp
            break

        elif sale_price is not None:
            price = sale_price
            break

    if price is None:
        raise Exception(
            "تم العثور على اللعبة لكن ماكو سعر تركي متوفر"
        )

    return title, price, original_price, discount


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🎮 SA STORE Price Bot 🇹🇷\n\n"
        "دزلي رابط أي لعبة من Xbox Store التركي "
        "وأحسبلك سعرها الحالي تلقائياً."
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
        "🔎 جاري فحص اللعبة والسعر الحالي..."
    )

    try:

        game_name, try_price, original_price, discount = (
            get_xbox_game(url)
        )

        iq_price = calculate_price(try_price)

        text = (
            f"🎮 اسم اللعبة:\n{game_name}\n\n"
            f"🇹🇷 السعر الحالي: ₺{try_price:.2f}\n"
        )

        if original_price is not None:

            text += (
                f"🏷️ السعر الأصلي: ₺{original_price:.2f}\n"
            )

            if discount > 0:
                text += (
                    f"🔥 التخفيض: %{discount:.0f}\n"
                )

        text += (
            f"\n💰 سعر SA STORE: "
            f"{iq_price:,} دينار عراقي"
        )

        await message.edit_text(text)

    except Exception as e:

        print("ERROR:", repr(e))

        await message.edit_text(
            f"❌ الخطأ:\n\n{str(e)}"
        )


def main():

    if not BOT_TOKEN:
        raise ValueError(
            "BOT_TOKEN غير موجود في Environment Variables"
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

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
