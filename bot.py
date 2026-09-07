import os
import re
import math
import requests
from bs4 import BeautifulSoup

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
    "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
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
# استخراج Product ID
# ==========================================

def get_product_id(url):

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
# جلب اسم اللعبة من Xbox
# ==========================================

def get_xbox_game_name(product_id):

    api_url = (
        "https://displaycatalog.mp.microsoft.com/"
        f"v7.0/products/{product_id}"
    )

    params = {
        "market": "TR",
        "languages": "en-US,tr-TR",
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
        raise Exception("ما تم العثور على اللعبة")

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
# البحث في Xbox-Now
# ==========================================

def search_xbox_now(game_name):

    search_url = (
        "https://www.xbox-now.com/en/search"
    )

    params = {
        "q": game_name
    }

    response = requests.get(
        search_url,
        params=params,
        headers=HEADERS,
        timeout=30
    )

    if response.status_code != 200:
        raise Exception(
            "Xbox-Now ما رجع الصفحة بشكل صحيح"
        )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    links = []

    for a in soup.find_all("a", href=True):

        href = a["href"]

        if re.match(
            r"^/[a-z]{2}/game/\d+/",
            href
        ):

            title = a.get_text(
                " ",
                strip=True
            )

            links.append(
                (
                    title,
                    "https://www.xbox-now.com" + href
                )
            )

    if not links:
        raise Exception(
            "ماكدر ألقى اللعبة في Xbox-Now"
        )

    # نحاول اختيار أقرب اسم
    target = game_name.lower()

    for title, link in links:

        if target in title.lower():
            return link

    return links[0][1]


# ==========================================
# استخراج السعر التركي
# ==========================================

def get_turkish_price(game_url):

    response = requests.get(
        game_url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    text = soup.get_text(
        "\n",
        strip=True
    )

    # نبحث عن قسم تركيا
    turkey_match = re.search(
        r"TR Turkey(.*?)(?:Image:|Deal until|Prices last updated|$)",
        text,
        re.DOTALL | re.IGNORECASE
    )

    if turkey_match:

        turkey_text = turkey_match.group(1)

        prices = re.findall(
            r"([\d.,]+)\s*TRY",
            turkey_text,
            re.IGNORECASE
        )

        if prices:

            values = []

            for price in prices:

                number = to_float(price)

                if number is not None:
                    values.append(number)

            if values:
                # نأخذ أقل سعر = السعر الفعلي
                return min(values)

    # بحث عام احتياطي
    prices = re.findall(
        r"([\d.,]+)\s*TRY",
        text,
        re.IGNORECASE
    )

    values = []

    for price in prices:

        number = to_float(price)

        if number is not None:
            values.append(number)

    if values:
        return min(values)

    raise Exception(
        "ماكدر أطلع السعر التركي من Xbox-Now"
    )


# ==========================================
# جلب اللعبة والسعر
# ==========================================

def get_game_info(url):

    product_id = get_product_id(url)

    if not product_id:
        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )

    game_name = get_xbox_game_name(
        product_id
    )

    game_url = search_xbox_now(
        game_name
    )

    print("XBOX NOW GAME:", game_url)

    try_price = get_turkish_price(
        game_url
    )

    return game_name, try_price


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

    url = update.message.text.strip()

    if "xbox.com" not in url.lower():

        await update.message.reply_text(
            "❌ دزلي رابط لعبة صحيح من Xbox Store."
        )

        return

    message = await update.message.reply_text(
        "🔎 جاري البحث عن اللعبة والسعر..."
    )

    try:

        game_name, try_price = get_game_info(
            url
        )

        iq_price = calculate_price(
            try_price
        )

        text = (
            f"🎮 اسم اللعبة:\n"
            f"{game_name}\n\n"
            f"🇹🇷 السعر الحالي: "
            f"₺{try_price:,.2f}\n\n"
            f"━━━━━━━━━━━━━━\n\n"
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

