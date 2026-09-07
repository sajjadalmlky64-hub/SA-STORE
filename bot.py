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
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}


PROFIT_IQD = 3000


def get_exchange_rate():

    url = "https://api.frankfurter.dev/v2/rate/TRY/IQD"

    response = requests.get(
        url,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    rate = data.get("rate")

    if rate is None:
        raise Exception("ماكدر أجيب سعر صرف الليرة التركية")

    return float(rate)


def calculate_price(price):

    exchange_rate = get_exchange_rate()

    game_price_iqd = price * exchange_rate

    final_price = game_price_iqd + PROFIT_IQD

    return math.ceil(final_price / 1000) * 1000


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


def get_title(product):

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

    return "لعبة Xbox"


def parse_price_object(price_data):

    if not isinstance(price_data, dict):
        return None, None, 0

    current = None
    original = None
    discount = 0

    for key in [
        "SalePrice",
        "Price",
        "RetailPrice",
        "FormattedPrice"
    ]:

        value = to_float(price_data.get(key))

        if value is not None:
            current = value
            break

    for key in [
        "MSRP",
        "ListPrice",
        "BasePrice",
        "OriginalPrice"
    ]:

        value = to_float(price_data.get(key))

        if value is not None:
            original = value
            break

    value = price_data.get(
        "DiscountPercentage"
    )

    if value is not None:

        try:
            discount = float(value)
        except:
            discount = 0

    if (
        current is not None
        and original is not None
        and current < original
    ):

        if discount == 0:

            discount = (
                (original - current)
                / original
            ) * 100

        return current, original, discount

    if current is None and original is not None:
        return original, None, 0

    if current is not None:
        return current, original, discount

    return None, None, 0


def find_prices(data):

    found_prices = []

    if isinstance(data, dict):

        if "Price" in data:

            price, original, discount = (
                parse_price_object(data["Price"])
            )

            if price is not None:

                found_prices.append(
                    (
                        price,
                        original,
                        discount
                    )
                )

        price, original, discount = (
            parse_price_object(data)
        )

        if price is not None:

            found_prices.append(
                (
                    price,
                    original,
                    discount
                )
            )

        for value in data.values():

            found_prices.extend(
                find_prices(value)
            )

    elif isinstance(data, list):

        for item in data:

            found_prices.extend(
                find_prices(item)
            )

    return found_prices


def choose_price(prices):

    valid = []

    for price, original, discount in prices:

        if price is None or price <= 0:
            continue

        valid.append(
            (
                price,
                original,
                discount
            )
        )

    if not valid:
        return None, None, 0

    discounted = [
        item for item in valid
        if item[1] is not None
        and item[0] < item[1]
    ]

    if discounted:
        return discounted[0]

    return valid[0]


def fetch_product(product_id):

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

    if "Product" in data:
        return data["Product"]

    products = data.get("Products", [])

    if products:
        return products[0]

    raise Exception(
        "ما تم العثور على المنتج في Xbox Catalog"
    )


def get_xbox_game(url):

    product_id = get_product_id(url)

    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )

    product = fetch_product(product_id)

    title = get_title(product)

    prices = find_prices(product)

    price, original_price, discount = (
        choose_price(prices)
    )

    if price is None:

        raise Exception(
            "تم العثور على اللعبة لكن ماكو سعر تركي"
        )

    return (
        title,
        price,
        original_price,
        discount
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🎮 SA STORE Price Bot 🇹🇷\n\n"
        "دزلي رابط أي لعبة من Xbox Store "
        "وأجيبلك السعر التركي وسعر SA STORE."
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
        "🔎 جاري فحص اللعبة والسعر..."
    )


    try:

        (
            game_name,
            try_price,
            original_price,
            discount
        ) = get_xbox_game(url)


        exchange_rate = get_exchange_rate()

        iq_price = calculate_price(
            try_price
        )


        text = (
            f"🎮 اسم اللعبة:\n"
            f"{game_name}\n\n"
            f"🇹🇷 السعر الحالي: "
            f"₺{try_price:,.2f}\n"
        )


        if original_price is not None:

            text += (
                f"🏷️ السعر الأصلي: "
                f"₺{original_price:,.2f}\n"
            )


            if discount > 0:

                text += (
                    f"🔥 التخفيض: "
                    f"%{discount:.0f}\n"
                )


        text += (
            f"\n💱 سعر الصرف: "
            f"1₺ = {exchange_rate:,.2f} د.ع\n"
        )

        text += (
            f"➕ ربح SA STORE: "
            f"{PROFIT_IQD:,} د.ع\n"
        )

        text += (
            f"\n━━━━━━━━━━━━━━\n\n"
            f"💰 سعر SA STORE: "
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
