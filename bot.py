import os
import re
import math
import json
import requests
from urllib.parse import quote_plus, unquote

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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
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


def fetch_xbox_product(product_id):

    api_url = (
        f"https://displaycatalog.mp.microsoft.com/"
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

    if "Product" in data:
        return data["Product"]

    products = data.get("Products", [])

    if products:
        return products[0]

    raise Exception("ما تم العثور على اللعبة في Xbox")


def get_game_title(product):

    localized = product.get(
        "LocalizedProperties",
        []
    )

    for item in localized:

        language = item.get(
            "Language",
            ""
        )

        title = item.get(
            "ProductTitle"
        )

        if title and "en" in language.lower():
            return title

    for item in localized:

        title = item.get(
            "ProductTitle"
        )

        if title:
            return title

    title = product.get("ProductTitle")

    if title:
        return title

    return None


def normalize_text(text):

    if not text:
        return ""

    text = text.lower()

    text = text.replace("™", "")
    text = text.replace("®", "")
    text = text.replace("©", "")

    text = re.sub(
        r"[^a-z0-9\s]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def similarity_score(name1, name2):

    a = set(
        normalize_text(name1).split()
    )

    b = set(
        normalize_text(name2).split()
    )

    if not a or not b:
        return 0

    common = len(a & b)

    return common / max(
        len(a),
        len(b)
    )


def search_duckduckgo(game_name):

    query = (
        f'site:xbdeals.net/tr-store/game/ "{game_name}"'
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

    results = []

    for a in soup.select("a.result__a"):

        href = a.get("href", "")
        title = a.get_text(
            " ",
            strip=True
        )

        href = unquote(href)

        if "uddg=" in href:

            match = re.search(
                r"uddg=([^&]+)",
                href
            )

            if match:
                href = unquote(
                    match.group(1)
                )

        if "xbdeals.net/tr-store/game/" in href:

            results.append(
                (
                    title,
                    href
                )
            )

    return results


def search_bing(game_name):

    query = quote_plus(
        f'site:xbdeals.net/tr-store/game/ "{game_name}"'
    )

    url = (
        f"https://www.bing.com/search?q={query}"
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

    results = []

    for a in soup.select("li.b_algo h2 a"):

        href = a.get("href", "")
        title = a.get_text(
            " ",
            strip=True
        )

        if "xbdeals.net/tr-store/game/" in href:

            results.append(
                (
                    title,
                    href
                )
            )

    return results


def choose_best_result(game_name, results):

    if not results:
        return None

    target = normalize_text(game_name)

    best_url = None
    best_score = -1

    for title, url in results:

        title_normalized = normalize_text(title)

        score = similarity_score(
            target,
            title_normalized
        )

        if target in title_normalized:
            score += 2

        if score > best_score:

            best_score = score
            best_url = url

    return best_url


def search_xbdeals(game_name):

    results = []

    try:
        results.extend(
            search_duckduckgo(game_name)
        )

    except Exception as e:
        print("DuckDuckGo Error:", repr(e))

    if not results:

        try:
            results.extend(
                search_bing(game_name)
            )

        except Exception as e:
            print("Bing Error:", repr(e))

    return choose_best_result(
        game_name,
        results
    )


def get_xbdeals_price(game_name):

    game_url = search_xbdeals(
        game_name
    )

    if not game_url:

        raise Exception(
            "ماكدر ألقى اللعبة في XB Deals"
        )

    print("XBDEALS URL:", game_url)

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

    for script in soup.find_all(
        "script",
        type="application/ld+json"
    ):

        try:

            if not script.string:
                continue

            data = json.loads(
                script.string
            )

            items = (
                data
                if isinstance(data, list)
                else [data]
            )

            for item in items:

                if not isinstance(item, dict):
                    continue

                offers = item.get("offers")

                if isinstance(offers, dict):

                    price = to_float(
                        offers.get("price")
                    )

                    currency = offers.get(
                        "priceCurrency",
                        ""
                    )

                    if (
                        price is not None
                        and currency in (
                            "TRY",
                            "TL",
                            ""
                        )
                    ):
                        return price

        except Exception:
            pass

    text = soup.get_text(
        " ",
        strip=True
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    prices = re.findall(
        r"([\d.,]+)\s*(?:₺|TRY)",
        text,
        re.IGNORECASE
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

        if re.search(
            r"\bFREE\b",
            text,
            re.IGNORECASE
        ):
            return 0.0

        raise Exception(
            "ماكدر أطلع السعر التركي من XB Deals"
        )

    return numeric_prices[0]


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

    return game_name, try_price


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
        "🔎 جاري البحث عن اللعبة والسعر..."
    )

    try:

        game_name, try_price = get_xbox_game(
            url
        )

        iq_price = calculate_price(
            try_price
        )

        if try_price == 0:

            text = (
                f"🎮 اسم اللعبة:\n"
                f"{game_name}\n\n"
                f"🇹🇷 السعر الحالي: مجاني 🆓\n\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 سعر SA STORE: مجاني 🆓"
            )

        else:

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
