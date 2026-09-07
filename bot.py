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


# ==============================
# تسعيرة SA STORE
# ==============================

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


# ==============================
# استخراج Product ID
# ==============================

def get_product_id(url):

    url = url.split("?")[0].rstrip("/")

    matches = re.findall(
        r"(?<![A-Z0-9])([A-Z0-9]{12})(?![A-Z0-9])",
        url.upper()
    )

    if matches:
        return matches[-1]

    return None


# ==============================
# تحويل السعر إلى رقم
# ==============================

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
            .replace("$", "")
            .replace("\xa0", "")
            .replace(" ", "")
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


# ==============================
# اسم اللعبة
# ==============================

def get_title(product):

    localized = product.get(
        "LocalizedProperties",
        []
    )

    for item in localized:

        if not isinstance(item, dict):
            continue

        title = item.get("ProductTitle")

        if title:
            return title

    title = product.get("ProductTitle")

    if title:
        return title

    return "لعبة Xbox"


# ==============================
# تحليل كائن السعر
# ==============================

def parse_price_data(data):

    if not isinstance(data, dict):
        return None

    original_keys = [
        "MSRP",
        "ListPrice",
        "OriginalPrice",
        "BasePrice",
        "RegularPrice"
    ]

    sale_keys = [
        "SalePrice",
        "DiscountPrice",
        "CurrentPrice",
        "Price",
        "RetailPrice"
    ]

    original_price = None
    current_price = None

    # السعر الأصلي
    for key in original_keys:

        value = to_float(data.get(key))

        if value is not None and value > 0:
            original_price = value
            break

    # السعر الحالي / سعر التخفيض
    for key in sale_keys:

        value = to_float(data.get(key))

        if value is not None and value > 0:
            current_price = value
            break

    # بعض بيانات Xbox تكون داخل حقول مختلفة
    if current_price is None:

        for key in [
            "FormattedPrice",
            "DisplayPrice",
            "PriceValue"
        ]:

            value = to_float(data.get(key))

            if value is not None and value > 0:
                current_price = value
                break

    if current_price is None:
        return None

    discount = 0

    # حساب التخفيض الحقيقي
    if (
        original_price is not None
        and current_price < original_price
    ):

        discount = (
            (original_price - current_price)
            / original_price
        ) * 100

        return (
            current_price,
            original_price,
            discount,
            True
        )

    # نسبة التخفيض إذا كانت موجودة مباشرة
    discount_percentage = data.get(
        "DiscountPercentage"
    )

    if discount_percentage is not None:

        try:

            discount_percentage = float(
                str(discount_percentage)
                .replace("%", "")
            )

            if discount_percentage > 0:

                return (
                    current_price,
                    original_price,
                    discount_percentage,
                    True
                )

        except:
            pass

    return (
        current_price,
        None,
        0,
        False
    )


# ==============================
# البحث عن جميع معلومات الأسعار
# ==============================

def find_all_prices(data):

    results = []

    if isinstance(data, dict):

        # نفحص الكائن نفسه
        parsed = parse_price_data(data)

        if parsed is not None:
            results.append(parsed)

        # نفحص الحقول الداخلية
        for key, value in data.items():

            # نتجنب بعض الحقول غير المهمة
            if key in [
                "LocalizedProperties",
                "Images",
                "Videos"
            ]:
                continue

            results.extend(
                find_all_prices(value)
            )

    elif isinstance(data, list):

        for item in data:

            results.extend(
                find_all_prices(item)
            )

    return results


# ==============================
# اختيار السعر الصحيح
# ==============================

def choose_best_price(prices):

    valid = []

    for item in prices:

        current, original, discount, is_discounted = item

        if current is None:
            continue

        if current <= 0:
            continue

        valid.append(item)

    if not valid:
        return None, None, 0

    # الأولوية للسعر المخفض الحقيقي
    discounted = []

    for item in valid:

        current, original, discount, is_discounted = item

        if (
            original is not None
            and current < original
        ):
            discounted.append(item)

        elif is_discounted and discount > 0:
            discounted.append(item)

    if discounted:

        # نختار التخفيض الأقوى / السعر الحالي الصحيح
        discounted.sort(
            key=lambda x: (
                -x[2],
                x[0]
            )
        )

        current, original, discount, _ = discounted[0]

        return (
            current,
            original,
            discount
        )

    # إذا ماكو تخفيض نختار أول سعر منطقي
    current, original, discount, _ = valid[0]

    return (
        current,
        None,
        0
    )


# ==============================
# استخراج السعر من MarketProperties
# ==============================

def get_market_price(product):

    market_properties = product.get(
        "MarketProperties",
        []
    )

    candidates = []

    for market in market_properties:

        if not isinstance(market, dict):
            continue

        # الطريقة الأساسية
        price_data = market.get("Price")

        if isinstance(price_data, dict):

            parsed = parse_price_data(price_data)

            if parsed:
                candidates.append(parsed)

        # بعض المنتجات تحتوي السعر داخل MarketProperties مباشرة
        parsed = parse_price_data(market)

        if parsed:
            candidates.append(parsed)

        # بحث أعمق داخل بيانات السوق فقط
        candidates.extend(
            find_all_prices(market)
        )

    if candidates:

        return choose_best_price(candidates)

    return None, None, 0


# ==============================
# جلب المنتج من Xbox Catalog
# ==============================

def fetch_product(product_id):

    api_url = (
        "https://displaycatalog.mp.microsoft.com/"
        "v7.0/products"
    )

    params = {
        "bigIds": product_id,
        "market": "TR",
        "languages": "tr-TR,en-US",
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

    products = data.get(
        "Products",
        []
    )

    if products:
        return products[0]

    # محاولة احتياطية
    api_url_2 = (
        f"https://displaycatalog.mp.microsoft.com/"
        f"v7.0/products/{product_id}"
    )

    response = requests.get(
        api_url_2,
        params={
            "market": "TR",
            "languages": "tr-TR,en-US",
            "fieldsTemplate": "details"
        },
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


# ==============================
# الحصول على اللعبة والسعر
# ==============================

def get_xbox_game(url):

    product_id = get_product_id(url)

    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )

    product = fetch_product(product_id)

    title = get_title(product)

    # أولاً نحاول MarketProperties
    price, original_price, discount = (
        get_market_price(product)
    )

    # إذا ما حصلنا سعر نبحث داخل المنتج
    if price is None:

        all_prices = find_all_prices(product)

        price, original_price, discount = (
            choose_best_price(all_prices)
        )

    if price is None:

        raise Exception(
            "تم العثور على اللعبة لكن ماكدر أطلع السعر التركي"
        )

    return (
        title,
        price,
        original_price,
        discount
    )


# ==============================
# أمر Start
# ==============================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🎮 SA STORE Price Bot 🇹🇷\n\n"
        "دزلي رابط أي لعبة من Xbox Store "
        "وأجيبلك السعر التركي الحالي "
        "وسعر SA STORE."
    )


# ==============================
# استقبال الرابط
# ==============================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    url = update.message.text.strip()

    if "xbox.com" not in url.lower():

        await update.message.reply_text(
            "❌ دزلي رابط صحيح من Xbox Store."
        )

        return

    message = await update.message.reply_text(
        "🔎 جاري فحص اللعبة والسعر والتخفيض..."
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

        # إذا أكو تخفيض حقيقي
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


# ==============================
# تشغيل البوت
# ==============================

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
