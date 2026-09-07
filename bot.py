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


# =========================
# حساب سعر SA STORE
# =========================

def calculate_price(price):

    if price <= 25:
        return 3000

    if price <= 50:
        return 4000

    return math.ceil(price / 100) * 6000


# =========================
# استخراج Product ID
# =========================

def get_product_id(url):

    url = url.split("?")[0].rstrip("/")

    # Product IDs مثل:
    # 9NP7G... أو 9NBL...
    matches = re.findall(
        r"(?<![A-Z0-9])([A-Z0-9]{12})(?![A-Z0-9])",
        url.upper()
    )

    if matches:
        return matches[-1]

    return None


# =========================
# تحويل السعر إلى رقم
# =========================

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
            .replace("\xa0", "")
            .strip()
        )

        # 1.299,00
        if "," in value and "." in value:
            value = value.replace(".", "").replace(",", ".")

        # 299,00
        elif "," in value:
            value = value.replace(",", ".")

        try:
            return float(value)

        except ValueError:
            return None

    return None


# =========================
# البحث عن الاسم
# =========================

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

    properties = product.get("Properties", {})

    if isinstance(properties, dict):

        title = properties.get("ProductTitle")

        if title:
            return title

    return "لعبة Xbox"


# =========================
# استخراج السعر من Price
# =========================

def parse_price_object(price_data):

    if not isinstance(price_data, dict):
        return None, None, 0

    current = None
    original = None
    discount = 0

    # السعر الحالي
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

    # السعر الأصلي
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

    # نسبة الخصم
    for key in [
        "DiscountPercentage",
        "DiscountPercent"
    ]:

        value = price_data.get(key)

        if value is not None:

            try:
                discount = float(value)
            except:
                pass

    # إذا عندنا سعر أصلي وسعر حالي
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

    # إذا ماكو SalePrice بس MSRP
    if current is None and original is not None:

        return original, None, 0

    if current is not None:

        return current, original, discount

    return None, None, 0


# =========================
# البحث داخل JSON كامل
# =========================

def find_prices(data):

    found_prices = []

    if isinstance(data, dict):

        # إذا هذا الكائن يحتوي Price
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

        # بعض البيانات يكون السعر مباشرة
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

        # نكمل البحث بكل العناصر
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


# =========================
# اختيار أفضل سعر
# =========================

def choose_price(prices):

    valid = []

    for price, original, discount in prices:

        if price is None:
            continue

        # نستبعد الأسعار الغريبة
        if price <= 0:
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

    # نفضل السعر اللي بيه خصم
    discounted
