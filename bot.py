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
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ==========================================
# حساب سعر اللعبة بالعراقي
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

    elif price <= 249:
        return 11000

    elif price <= 260:
        return 12000

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
# استخراج Product ID من رابط Xbox
# ==========================================

def get_product_id(url):

    url = url.upper()

    matches = re.findall(
        r"(?<![A-Z0-9])([A-Z0-9]{12})(?![A-Z0-9])",
        url
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
            value = value.replace(".", "")
            value = value.replace(",", ".")

        else:
            value = value.replace(",", "")

    elif "," in value:
        value = value.replace(",", ".")

    try:
        return float(value)

    except ValueError:
        return None


# ==========================================
# استخراج رقم من قيمة أو Dictionary
# ==========================================

def extract_number(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):

        number = float(value)

        if number > 0:
            return number

        return None

    if isinstance(value, str):
        return to_float(value)

    if isinstance(value, dict):

        possible_keys = [
            "Amount",
            "amount",
            "Value",
            "value",
            "Price",
            "price"
        ]

        for key in possible_keys:

            if key in value:

                number = extract_number(value[key])

                if number and number > 0:
                    return number

    return None


# ==========================================
# جلب معلومات اللعبة من Microsoft
# ==========================================

def get_product_data(product_id):

    api_url = (
        "https://displaycatalog.mp.microsoft.com/"
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

    product = data.get("Product")

    if not product:

        products = data.get("Products", [])

        if products:
            product = products[0]

    if not product:
        raise Exception(
            "ما تم العثور على معلومات اللعبة"
        )

    return product


# ==========================================
# استخراج اسم اللعبة
# ==========================================

def get_game_name(product):

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

    raise Exception(
        "ماكدر أطلع اسم اللعبة"
    )


# ==========================================
# جلب بيانات الأسعار من Purchase API
# ==========================================

def get_availability_data(product_id):

    api_url = (
        "https://purchase.mp.microsoft.com/"
        "v9.0/users/me/availability"
    )

    params = {
        "market": "TR",
        "languages": "tr-TR",
        "productIds": product_id
    }

    response = requests.get(
        api_url,
        params=params,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


# ==========================================
# البحث عن زوج أسعار صحيح
# السعر الحالي + السعر الأصلي
# ==========================================

def find_price_pairs(data, pairs=None):

    if pairs is None:
        pairs = []

    if isinstance(data, dict):

        current_keys = [
            "SalePrice",
            "salePrice",
            "DiscountPrice",
            "discountPrice",
            "UnitPrice",
            "unitPrice"
        ]

        original_keys = [
            "ListPrice",
            "listPrice",
            "OriginalPrice",
            "originalPrice",
            "MSRP",
            "msrp"
        ]


        current_price = None
        original_price = None


        # البحث عن السعر الحالي
        for key in current_keys:

            if key in data:

                number = extract_number(data[key])

                if number and number > 0:
                    current_price = number
                    break


        # البحث عن السعر الأصلي
        for key in original_keys:

            if key in data:

                number = extract_number(data[key])

                if number and number > 0:
                    original_price = number
                    break


        # إذا موجود السعرين بنفس المكان
        if current_price and original_price:

            if (
                current_price > 0
                and original_price > 0
                and original_price >= current_price
            ):

                pairs.append(
                    (
                        current_price,
                        original_price
                    )
                )


        # البحث داخل البيانات
        for value in data.values():

            if isinstance(value, (dict, list)):

                find_price_pairs(
                    value,
                    pairs
                )


    elif isinstance(data, list):

        for item in data:

            find_price_pairs(
                item,
                pairs
            )


    return pairs


# ==========================================
# البحث عن سعر واحد إذا ماكو تخفيض
# ==========================================

def find_single_prices(data, prices=None):

    if prices is None:
        prices = []

    if isinstance(data, dict):

        price_keys = [
            "ListPrice",
            "listPrice",
            "SalePrice",
            "salePrice",
            "UnitPrice",
            "unitPrice",
            "Price",
            "price",
            "MSRP",
            "msrp"
        ]

        for key, value in data.items():

            if key in price_keys:

                number = extract_number(value)

                if number and number > 0:
                    prices.append(number)

            elif isinstance(value, (dict, list)):

                find_single_prices(
                    value,
                    prices
                )


    elif isinstance(data, list):

        for item in data:

            find_single_prices(
                item,
                prices
            )


    return prices


# ==========================================
# فلترة الأسعار غير المنطقية
# ==========================================

def is_valid_turkish_price(price):

    if price is None:
        return False

    if price <= 0:
        return False

    # فلترة الأرقام الغريبة جداً
    if price > 20000:
        return False

    return True


# ==========================================
# اختيار أفضل زوج أسعار
# ==========================================

def choose_best_price_pair(pairs):

    valid_pairs = []

    for current, original in pairs:

        if not is_valid_turkish_price(current):
            continue

        if not is_valid_turkish_price(original):
            continue

        if original >= current:

            valid_pairs.append(
                (
                    current,
                    original
                )
            )


    if not valid_pairs:
        return None, None


    # نفضل الأزواج التي فعلاً تحتوي على تخفيض
    discounted = [

        pair for pair in valid_pairs

        if pair[1] > pair[0]
    ]


    if discounted:

        # اختيار أكبر سعر أصلي معقول
        # من الأزواج الصحيحة
        discounted.sort(
            key=lambda x: (
                x[1] - x[0],
                x[1]
            ),
            reverse=True
        )

        return discounted[0]


    return valid_pairs[0]


# ==========================================
# جلب صفحة Xbox
# ==========================================

def get_store_page(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    return response.text


# ==========================================
# استخراج الأسعار من صفحة Xbox فقط
# ==========================================

def get_prices_from_store_page(url):

    html = get_store_page(url)

    prices = []

    patterns = [

        r'"salePrice"\s*:\s*"([0-9.,]+)"',

        r'"SalePrice"\s*:\s*"([0-9.,]+)"',

        r'"listPrice"\s*:\s*"([0-9.,]+)"',

        r'"ListPrice"\s*:\s*"([0-9.,]+)"',

        r'"originalPrice"\s*:\s*"([0-9.,]+)"',

        r'"OriginalPrice"\s*:\s*"([0-9.,]+)"',

        r'([0-9]{1,6}(?:[.,][0-9]{1,2})?)\s*₺',

        r'₺\s*([0-9]{1,6}(?:[.,][0-9]{1,2})?)'
    ]


    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE
        )

        for match in matches:

            price = to_float(match)

            if (
                price
                and is_valid_turkish_price(price)
            ):

                prices.append(price)


    prices = sorted(
        list(set(prices))
    )

    return prices


# ==========================================
# تحديد السعر من صفحة Xbox
# ==========================================

def determine_page_prices(prices):

    if not prices:
        return None, None

    prices = sorted(prices)

    # سعر واحد فقط
    if len(prices) == 1:
        return prices[0], None


    # نحاول أخذ أصغر سعر وأقرب سعر أعلى منه
    current_price = prices[0]

    higher_prices = [

        price for price in prices

        if price > current_price
    ]


    if higher_prices:

        original_price = max(higher_prices)

        return (
            current_price,
            original_price
        )


    return current_price, None


# ==========================================
# جلب كل معلومات اللعبة
# ==========================================

def get_game_info(url):

    product_id = get_product_id(url)

    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )


    # اسم اللعبة
    product = get_product_data(product_id)

    game_name = get_game_name(product)


    # ======================================
    # أولاً: Purchase API
    # ======================================

    try:

        availability_data = (
            get_availability_data(product_id)
        )


        pairs = find_price_pairs(
            availability_data
        )


        current_price, original_price = (
            choose_best_price_pair(pairs)
        )


        # إذا حصلنا سعر صحيح
        if current_price:

            return (
                game_name,
                current_price,
                original_price
            )


        # إذا ما حصلنا زوج أسعار
        single_prices = find_single_prices(
            availability_data
        )


        single_prices = [

            price
            for price in single_prices
            if is_valid_turkish_price(price)
        ]


        single_prices = sorted(
            list(set(single_prices))
        )


        if single_prices:

            return (
                game_name,
                single_prices[0],
                None
            )


    except Exception as error:

        print(
            "PURCHASE API ERROR:",
            repr(error)
        )


    # ======================================
    # ثانياً: صفحة Xbox كاحتياط
    # ======================================

    try:

        page_prices = (
            get_prices_from_store_page(url)
        )


        current_price, original_price = (
            determine_page_prices(page_prices)
        )


        if current_price:

            return (
                game_name,
                current_price,
                original_price
            )


    except Exception as error:

        print(
            "PAGE PRICE ERROR:",
            repr(error)
        )


    raise Exception(
        "ماكدر أطلع سعر اللعبة"
    )


# ==========================================
# تنسيق السعر العراقي
# ==========================================

def format_game_price(price):

    price = int(price)

    thousands = price // 1000

    if price % 1000 == 
