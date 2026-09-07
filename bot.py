import os
import re
import math
import requests
from urllib.parse import quote_plus

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

    else:
        extra = price - 1000
        extra_steps = math.ceil(extra / 100)

        return 33000 + (extra_steps * 3000)


# ==========================================
# استخراج Product ID من رابط Xbox
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
            .strip()
        )

        if "," in value and "." in value:

            # 1.999,00
            if value.rfind(",") > value.rfind("."):
                value = value.replace(".", "").replace(",", ".")

            # 1,999.00
            else:
                value = value.replace(",", "")

        elif "," in value:
            value = value.replace(",", ".")

        try:
            return float(value)

        except ValueError:
            return None

    return None


# ==========================================
# جلب معلومات اللعبة من Microsoft
# فقط للحصول على الاسم
# ==========================================

def fetch_xbox_product(product_id):

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
        "ما تم العثور على اللعبة"
    )


def get_game_title(product):

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

    return None


# ==========================================
# البحث عن اللعبة في XB Deals
# ==========================================

def normalize_text(text):

    text = text.lower()

    text = re.sub(
        r"[™®©:,\-–—!?.'\"()\[\]]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def search_xbdeals(game_name):

    # البحث عبر DuckDuckGo عن صفحة اللعبة داخل XBDeals
    query = (
        f"site:xbdeals.net/tr-store/game "
        f"\"{game_name}\""
    )

    url = (
        "https://html.duckduckgo.com/html/"
        f"?q={quote_plus(query)}"
    )

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    links = []

    for a in soup.select(".result__a"):

        href = a.get("href", "")

        title = a.get_text(
            " ",
            strip=True
        )

        if "xbdeals.net/tr-store/game/" in href:
            links.append(
                (
                    title,
                    href
                )
            )

    if not links:
        return None

    target = normalize_text(game_name)

    # نحاول اختيار أقرب اسم
    for title, href in links:

        normalized_title = normalize_text(title)

        if target in normalized_title:
            return href

    return links[0][1]


# ==========================================
# قراءة السعر من صفحة XB Deals
# ==========================================

def get_xbdeals_price(game_name):

    game_url = search_xbdeals(game_name)

    if not game_url:

        raise Exception(
            "ماكدر ألقى اللعبة في XB Deals"
        )

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
        " ",
        strip=True
    )

    # نحذف المسافات الزائدة
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    # ======================================
    # نبحث عن الأسعار التركية
    # ======================================

    prices = re.findall(
        r"([\d.,]+)\s*₺",
        text
    )

    numeric_prices = []

    for price in prices:

        value = to_float(price)

        if (
            value is not None
            and value >= 0
        ):
            numeric_prices.append(value)

    if not numeric_prices:

        # حالة الألعاب المجانية
        if re.search(
            r"\bFREE\b",
            text,
            re.IGNORECASE
        ):
            return 0.0

        raise Exception(
            "ماكدر أطلع السعر من XB Deals"
        )

    # ======================================
    # محاولة قراءة السعر الحالي
    #
    # XB Deals عادة يعرض السعر الحالي
    # قبل السعر الأصلي
    # ======================================

    current_price = numeric_prices[0]

    return current_price


# ==========================================
# جلب اللعبة والسعر النهائي
# ==========================================

def get_xbox_game(url):

    product_id = get_product_id(url)

    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )

    product = fetch_xbox_product(
        product_id
    )

    game_name = get_game_title(
        product
    )

    if not game_name:

        raise Exception(
            "ماكدر أطلع اسم اللعبة"
        )

    try_price = get_xbdeals_price(
        game_name
    )

    return (
        game_name,
        try_price
    )


# ==========================================
# أمر Start
# ==========================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🎮 SA STORE Price Bot 🇹🇷\n\n"
        "دزلي رابط لعبة من Xbox Store "
        "وأجيبلك السعر التركي الحالي "
        "وسعر SA STORE."
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

        game_name, try_price = (
            get_xbox_game(url)
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

        print(
            "ERROR:",
            repr(e)
        )

        await message.edit_text(
            f"❌ صار خطأ:\n\n"
            f"{str(e)}"
        )


# ==========================================
# تشغيل البوت
# ==========================================

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
