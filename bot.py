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

    match = re.search(
        r"/([A-Z0-9]{12})(?:[/?]|$)",
        url.upper()
    )

    if match:
        return match.group(1)

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


def get_game_price(product):

    prices = []

    sku_availabilities = product.get(
        "DisplaySkuAvailabilities",
        []
    )

    for sku_data in sku_availabilities:

        availabilities = sku_data.get(
            "Availabilities",
            []
        )

        for availability in availabilities:

            actions = availability.get(
                "Actions",
                []
            )

            if actions and "Purchase" not in actions:
                continue

            order_data = availability.get(
                "OrderManagementData",
                {}
            )

            price_data = order_data.get(
                "Price",
                {}
            )

            if not isinstance(price_data, dict):
                continue

            currency = price_data.get(
                "CurrencyCode",
                ""
            )

            if currency and currency != "TRY":
                continue

            list_price = to_float(
                price_data.get("ListPrice")
            )

            msrp = to_float(
                price_data.get("MSRP")
            )

            if list_price is None:
                continue

            prices.append({
                "current": list_price,
                "original": msrp
            })

    if not prices:
        raise Exception(
            "ماكدر ألقى سعر اللعبة داخل بيانات Xbox"
        )

    prices.sort(
        key=lambda x: x["current"]
    )

    selected = prices[0]

    current_price = selected["current"]
    original_price = selected["original"]

    discount = 0

    if (
        original_price is not None
        and original_price > current_price
        and original_price > 0
    ):
        discount = round(
            ((original_price - current_price)
             / original_price) * 100
        )
    else:
        original_price = None

    return (
        current_price,
        original_price,
        discount
    )


def get_xbox_game(url):

    product_id = get_product_id(url)

    if not product_id:
        raise Exception(
            "ماكدر أطلع ID اللعبة من الرابط"
        )

    api_url = (
        "https://displaycatalog.mp.microsoft.com"
        "/v7.0/products"
    )

    params = {
        "bigIds": product_id,
        "market": "TR",
        "languages": "tr-TR",
        "fieldsTemplate": "Details",
        "actionFilter": "Browse"
    }

    response = requests.get(
        api_url,
        params=params,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    products = data.get(
        "Products",
        []
    )

    if not products:
        raise Exception(
            "اللعبة غير موجودة في Xbox Catalog"
        )

    product = products[0]

    title = None

    localized = product.get(
        "LocalizedProperties",
        []
    )

    for item in localized:

        title = item.get(
            "ProductTitle"
        )

        if title:
            break

    if not title:
        title = product.get(
            "ProductTitle"
        )

    if not title:
        title = "لعبة Xbox"

    price, original_price, discount = (
        get_game_price(product)
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
            f"₺{try_price:.2f}\n"
        )

        if original_price is not None:

            text += (
                f"🏷️ السعر الأصلي: "
                f"₺{original_price:.2f}\n"
            )

            if discount > 0:

                text += (
                    f"🔥 التخفيض: "
                    f"%{discount}\n"
                )

        text += (
            f"\n💰 سعر SA STORE: "
            f"{iq_price:,} دينار عراقي"
        )

        await message.edit_text(text)

    except Exception as e:

        print("ERROR:", str(e))

        await message.edit_text(
            "❌ صار خطأ أثناء جلب معلومات اللعبة.\n\n"
            "تأكد من أن الرابط رابط منتج صحيح من Xbox Store."
        )


def main():

    if not BOT_TOKEN:

        raise ValueError(
            "BOT_TOKEN غير موجود في "
            "Environment Variables"
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

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
```0
