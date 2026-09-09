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
# تحويل السعر التركي إلى رقم
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

    if not value:
        return None

    # مثال تركي:
    # 1.499,00 = 1499.00
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

    except (ValueError, TypeError):
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
        raise Exception("ما تم العثور على معلومات اللعبة")

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

    raise Exception("ماكدر أطلع اسم اللعبة")


# ==========================================
# استخراج رقم من قيمة سعر
# ==========================================

def extract_numeric_price(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):

        if value > 0:
            return float(value)

        return None

    if isinstance(value, str):

        price = to_float(value)

        if price and price > 0:
            return price

    if isinstance(value, dict):

        possible_keys = [
            "Amount",
            "amount",
            "Value",
            "value",
            "Price",
            "price",
            "BasePrice",
            "basePrice"
        ]

        for key in possible_keys:

            if key in value:

                price = extract_numeric_price(
                    value[key]
                )

                if price:
                    return price

    return None


# ==========================================
# استخراج زوج الأسعار من كائن واحد
# مهم: لا نجمع كل أرقام الـ API
# ==========================================

def extract_price_pair_from_dict(data):

    if not isinstance(data, dict):
        return None, None

    current_keys = [
        "SalePrice",
        "salePrice",
        "DiscountPrice",
        "discountPrice",
        "CurrentPrice",
        "currentPrice",
        "UnitPrice",
        "unitPrice"
    ]

    original_keys = [
        "OriginalPrice",
        "originalPrice",
        "MSRP",
        "msrp",
        "ListPrice",
        "listPrice"
    ]

    current_price = None
    original_price = None

    # السعر الحالي
    for key in current_keys:

        if key in data:

            price = extract_numeric_price(
                data[key]
            )

            if price:
                current_price = price
                break

    # السعر الأصلي
    for key in original_keys:

        if key in data:

            price = extract_numeric_price(
                data[key]
            )

            if price:
                original_price = price
                break

    # إذا ماكو سعر خصم، ListPrice يعتبر السعر الحالي
    if not current_price:

        for key in [
            "ListPrice",
            "listPrice",
            "Price",
            "price",
            "MSRP",
            "msrp"
        ]:

            if key in data:

                price = extract_numeric_price(
                    data[key]
                )

                if price:
                    current_price = price
                    break

    # إذا السعر الأصلي نفس الحالي ماكو خصم
    if (
        original_price
        and current_price
        and original_price <= current_price
    ):
        original_price = None

    return current_price, original_price


# ==========================================
# البحث عن كائن تسعير صحيح داخل API
# ==========================================

def find_price_pairs(data, results=None):

    if results is None:
        results = []

    if isinstance(data, dict):

        current, original = (
            extract_price_pair_from_dict(data)
        )

        if current:

            results.append(
                {
                    "current": current,
                    "original": original
                }
            )

        for value in data.values():

            if isinstance(value, (dict, list)):

                find_price_pairs(
                    value,
                    results
                )

    elif isinstance(data, list):

        for item in data:

            find_price_pairs(
                item,
                results
            )

    return results


# ==========================================
# اختيار أفضل نتيجة من API
# ==========================================

def select_best_price_pair(results):

    if not results:
        return None, None

    # نفضل النتائج التي تحتوي على سعر أصلي وحالي
    discounted = []

    normal = []

    for item in results:

        current = item.get("current")
        original = item.get("original")

        if not current:
            continue

        if (
            original
            and original > current
        ):

            discounted.append(item)

        else:

            normal.append(item)

    # إذا وجدنا خصم حقيقي
    if discounted:

        # نختار النتيجة ذات السعر الحالي الأكبر
        # حتى نتجنب الأرقام الصغيرة غير المتعلقة باللعبة
        best = max(
            discounted,
            key=lambda x: x["current"]
        )

        return (
            best["current"],
            best["original"]
        )

    # بدون خصم
    if normal:

        # نختار أعلى سعر منطقي
        best = max(
            normal,
            key=lambda x: x["current"]
        )

        return (
            best["current"],
            None
        )

    return None, None


# ==========================================
# جلب الأسعار من Microsoft Purchase API
# ==========================================

def get_prices_from_api(product_id):

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

    data = response.json()

    results = find_price_pairs(data)

    return select_best_price_pair(results)


# ==========================================
# استخراج السعر من صفحة Xbox
# ==========================================

def get_price_from_store_page(url):

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    html = response.text

    # نبحث فقط عن أسعار مرتبطة بعملة تركية
    patterns = [

        r'([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\s*₺',

        r'₺\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})',

        r'([0-9]{1,6}(?:,[0-9]{2})?)\s*₺',

        r'₺\s*([0-9]{1,6}(?:,[0-9]{2})?)'
    ]

    prices = []

    for pattern in patterns:

        matches = re.findall(
            pattern,
            html,
            re.IGNORECASE
        )

        for match in matches:

            price = to_float(match)

            if price and price > 0:
                prices.append(price)

    if not prices:
        return None, None

    prices = sorted(
        list(set(prices))
    )

    # صفحة المتجر عادة تعرض السعر الحالي أولاً
    # وإذا ظهر سعرين مختلفين نعتبر الأعلى أصلياً
    if len(prices) >= 2:

        current = min(prices)
        original = max(prices)

        # نتجنب الخصومات الوهمية الكبيرة جداً
        if original > current:
            return current, original

    return max(prices), None


# ==========================================
# استخراج سعر من Product Data
# كاحتياط فقط
# ==========================================

def get_price_from_product_data(product):

    results = find_price_pairs(product)

    return select_best_price_pair(results)


# ==========================================
# جلب كل معلومات اللعبة
# ==========================================

def get_game_info(url):

    product_id = get_product_id(url)

    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )

    product = get_product_data(product_id)

    game_name = get_game_name(product)

    current_price = None
    original_price = None

    # ======================================
    # 1. Microsoft Purchase API
    # ======================================

    try:

        current_price, original_price = (
            get_prices_from_api(product_id)
        )

        print(
            "API PRICE:",
            current_price,
            original_price
        )

    except Exception as error:

        print(
            "API PRICE ERROR:",
            repr(error)
        )

    # ======================================
    # 2. Product Data احتياط
    # ======================================

    if not current_price:

        try:

            current_price, original_price = (
                get_price_from_product_data(
                    product
                )
            )

            print(
                "PRODUCT PRICE:",
                current_price,
                original_price
            )

        except Exception as error:

            print(
                "PRODUCT PRICE ERROR:",
                repr(error)
            )

    # ======================================
    # 3. صفحة Xbox احتياط
    # ======================================

    if not current_price:

        try:

            current_price, original_price = (
                get_price_from_store_page(url)
            )

            print(
                "PAGE PRICE:",
                current_price,
                original_price
            )

        except Exception as error:

            print(
                "PAGE PRICE ERROR:",
                repr(error)
            )

    if not current_price:

        raise Exception(
            "ماكدر أطلع سعر اللعبة"
        )

    # حماية إضافية:
    # إذا السعر الأصلي أقل أو يساوي الحالي نحذفه
    if (
        original_price
        and original_price <= current_price
    ):

        original_price = None

    return (
        game_name,
        current_price,
        original_price
    )


# ==========================================
# تنسيق السعر التركي
# ==========================================

def format_turkish_price(price):

    return (
        f"{price:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


# ==========================================
# أمر Start
# ==========================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = (
        "🎮 SA STORE Price Bot 🇹🇷\n\n"
        "دزلي رابط أي لعبة من Xbox Store "
        "وأجيبلك السعر التركي الحالي.\n\n"
        "🔥 إذا اللعبة عليها تخفيض "
        "راح أظهرلك السعر الأصلي والخصم.\n\n"
        "💰 بعدها أحسبلك سعر SA STORE."
    )

    await update.message.reply_text(message)


# ==========================================
# استقبال رابط Xbox
# ==========================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text.strip()

    if "xbox.com" not in text.lower():

        await update.message.reply_text(
            "❌ خطأ\n\n"
            "دزلي رابط لعبة من Xbox Store."
        )

        return

    processing_message = await update.message.reply_text(
        "⏳ جاري البحث عن اللعبة والسعر..."
    )

    try:

        (
            game_name,
            turkey_price,
            original_price
        ) = get_game_info(text)

        store_price = calculate_price(
            turkey_price
        )

        turkey_price_text = (
            format_turkish_price(
                turkey_price
            )
        )

        store_price_text = (
            f"{store_price:,}"
            .replace(",", ".")
        )

        # ==================================
        # اللعبة عليها تخفيض
        # ==================================

        if (
            original_price
            and original_price > turkey_price
        ):

            original_price_text = (
                format_turkish_price(
                    original_price
                )
            )

            discount_percent = round(
                (
                    (
                        original_price
                        - turkey_price
                    )
                    / original_price
                )
                * 100
            )

            result = (
                f"🎮 {game_name}\n\n"
                f"🔥 اللعبة عليها تخفيض!\n\n"
                f"📉 نسبة الخصم: "
                f"{discount_percent}%\n\n"
                f"❌ السعر الأصلي: "
                f"{original_price_text} ₺\n"
                f"🇹🇷 السعر الحالي: "
                f"{turkey_price_text} ₺\n\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 سعر SA STORE: "
                f"{store_price_text} دينار عراقي"
            )

        # ==================================
        # بدون تخفيض
        # ==================================

        else:

            result = (
                f"🎮 {game_name}\n\n"
                f"🇹🇷 السعر الحالي: "
                f"{turkey_price_text} ₺\n\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💰 سعر SA STORE: "
                f"{store_price_text} دينار عراقي"
            )

        await processing_message.edit_text(
            result
        )

    except Exception as error:

        print("ERROR:", repr(error))

        await processing_message.edit_text(
            "❌ صار خطأ أثناء جلب معلومات اللعبة.\n\n"
            "تأكد أن الرابط صحيح وجرب مرة ثانية."
        )


# ==========================================
# تشغيل البوت
# ==========================================

def main():

    if not BOT_TOKEN:

        raise ValueError(
            "BOT_TOKEN غير موجود في Variables"
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

    app.run_polling()


if __name__ == "__main__":
    main()
