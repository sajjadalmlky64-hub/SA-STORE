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

    sale_price = to_float(
        price_data.get("SalePrice")
    )

    msrp = to_float(
        price_data.get("MSRP")
        or price_data.get("ListPrice")
        or price_data.get("BasePrice")
        or price_data.get("OriginalPrice")
    )

    if (
        sale_price is not None
        and msrp is not None
        and sale_price < msrp
    ):

        discount = (
            (msrp - sale_price)
            / msrp
        ) * 100

        return sale_price, msrp, discount

    for key in [
        "Price",
        "RetailPrice",
        "FormattedPrice"
    ]:

        value = to_float(
            price_data.get(key)
        )

        if value is not None:

            current = value
            break

    if current is None and msrp is not None:
        current = msrp

    return current, None, 0


def find_prices(data):

    found_prices = []

    if isinstance(data, dict):

        if "Price" in data:

            price, original, discount = (
                parse_price_object(
                    data["Price"]
                )
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

        return min(
            discounted,
            key=lambda x: x[0]
        )

    return min(
        valid,
        key=lambda x: x[0]
    )


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

    products = data.get(
        "Products",
        []
    )

    if products:

        return products[0]

    raise Exception(
        "ما تم العثور على اللعبة في Xbox Catalog"
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
