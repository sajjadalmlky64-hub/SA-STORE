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
# استخراج Product ID من الرابط
# ==========================================

def get_product_id(url):

    url = url.split("?")[0].rstrip("/")

    matches = re.findall(
        r"(?<![A-Z0-9])([A-Z0-9]{12})(?![A-Z0-9])",
        url.upper()
    )

    if matches:
        return matches[-1]

    return None


# ==========================================
# تحويل السعر إلى رقم
# ==========================================

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
            .replace(" ", "")
            .strip()
        )

        if "," in value and "." in value:

            if value.rfind(",") > value.rfind("."):
                value = value.replace(".", "").replace(",", ".")
            else:
                value = value.replace(",", "")

        elif "," in value:

            parts = value.split(",")

            if len(parts[-1]) == 3:
                value = value.replace(",", "")
            else:
                value = value.replace(",", ".")

        try:
            return float(value)

        except ValueError:
            return None

    return None


# ==========================================
# جلب بيانات اللعبة من Microsoft
# ==========================================

def fetch_product(product_id):

    api_url = "https://displaycatalog.mp.microsoft.com/v7.0/products"

    params = {
        "bigIds": product_id,
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

    print("STATUS:", response.status_code)
    print("API URL:", response.url)

    response.raise_for_status()

    data = response.json()

    products = data.get("Products", [])

    if not products:
        raise Exception(
            f"ما تم العثور على اللعبة. Product ID: {product_id}"
        )

    return products[0]


# ==========================================
# اسم اللعبة
# ==========================================

def get_title(product):

    localized = product.get(
        "LocalizedProperties",
        []
    )

    # نفضل الإنجليزي
    for item in localized:

        language = item.get(
            "Language",
            ""
        ).lower()

        title = item.get(
            "ProductTitle"
        )

        if title and language.startswith("en"):
            return title

    # أي اسم متوفر
    for item in localized:

        title = item.get(
            "ProductTitle"
        )

        if title:
            return title

    return product.get(
        "ProductTitle",
        "لعبة Xbox"
    )


# ==========================================
# استخراج السعر الحقيقي
# ==========================================

def get_price_info(product):

    market_properties = product.get(
        "MarketProperties",
        []
    )

    best_current = None
    best_original = None
    best_discount = 0

    for market in market_properties:

        price_data = market.get(
            "Price",
            {}
        )

        if not isinstance(price_data, dict):
            continue

        # السعر الأصلي
        original = to_float(
            price_data.get("MSRP")
            or price_data.get("ListPrice")
            or price_data.get("BasePrice")
        )

        # سعر التخفيض
        sale = to_float(
            price_data.get("SalePrice")
            or price_data.get("DiscountPrice")
        )

        # السعر الحالي المباشر
        current = to_float(
            price_data.get("Price")
            or price_data.get("RetailPrice")
        )

        # إذا أكو تخفيض
        if (
            sale is not None
            and original is not None
            and sale < original
        ):

            discount = (
                (original - sale) / original
            ) * 100

            return (
                sale,
                original,
                discount
            )

        # أحياناً السعر الحالي يكون داخل Price
        if (
            current is not None
            and original is not None
            and current < original
        ):

            discount = (
                (original - current) / original
            ) * 100

            return (
                current,
                original,
                discount
            )

        # بدون تخفيض
        if current is not None:

            if (
                best_current is None
                or current < best_current
            ):
                best_current = current

        elif original is not None:

            if (
                best_current is None
                or original < best_current
            ):
                best_current = original

    if best_current is not None:

        return (
            best_current,
            best_original,
            best_discount
        )

    raise Exception(
        "تم العثور على اللعبة لكن ماكدر أطلع السعر التركي"
    )


# ==========================================
# جلب اللعبة
# ==========================================

def get_xbox_game(url):

    product_id = get_product_id(url)

    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )

    product = fetch_product(
        product_id
    )

    title = get_title(product)

    current_price, original_price, discount = (
        get_price_info(product)
    )

    return (
        title,
        current_price,
        original_price,
        discount
    )


# ==========================================
# START
# ==========================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🎮 SA STORE Price Bot 🇹🇷\n\n"
        "دزلي رابط أي لعبة من Xbox Store "
        "وأجيبلك السعر التركي الحالي."
    )


# ==========================================
# استقبال الرابط
# ==========================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

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
            f"₺{try_price:,.2f}\n"
        )

        if (
            original_price is not None
            and original_price > try_price
        ):

            text += (
                f"🏷️ السعر الأصلي: "
                f"₺{original_price:,.2f}\n"
            )

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


# ==========================================
# تشغيل البوت
# ==========================================

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

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
