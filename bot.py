import os
import re
import math
import asyncio
import requests

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)


# =========================================================
# BOT TOKEN
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")


# =========================================================
# HEADERS
# =========================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}


# =========================================================
# SESSION
# =========================================================

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# =========================================================
# حساب سعر SA STORE
# =========================================================

def calculate_price(price):

    price = float(price)

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


# =========================================================
# استخراج Product ID من رابط Xbox
# =========================================================

def get_product_id(url):

    matches = re.findall(
        r"(?<![A-Za-z0-9])([A-Za-z0-9]{12})(?![A-Za-z0-9])",
        url
    )

    if matches:
        return matches[-1].upper()

    return None


# =========================================================
# تحويل القيمة إلى رقم
# =========================================================

def to_float(value):

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    value = str(value).strip()

    value = (
        value.replace("₺", "")
        .replace("TRY", "")
        .replace("TL", "")
        .replace("\xa0", "")
        .replace(" ", "")
    )

    # مثال: 1.299,00
    if "," in value and "." in value:

        if value.rfind(",") > value.rfind("."):

            value = value.replace(".", "")
            value = value.replace(",", ".")

        else:

            value = value.replace(",", "")

    # مثال: 299,00
    elif "," in value:

        value = value.replace(",", ".")

    try:
        return float(value)

    except Exception:
        return None


# =========================================================
# جلب بيانات المنتج من Microsoft Display Catalog
# =========================================================

def get_product_data(product_id):

    url = (
        "https://displaycatalog.mp.microsoft.com/"
        "v7.0/products"
    )

    params = {
        "bigIds": product_id,
        "market": "TR",
        "languages": "tr-TR,en-US",
        "fieldsTemplate": "Details",
        "actionFilter": "Browse"
    }

    response = SESSION.get(
        url,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    products = data.get("Products", [])

    if not products:

        product = data.get("Product")

        if product:
            return product

        raise Exception(
            "Microsoft لم يعثر على اللعبة"
        )

    return products[0]


# =========================================================
# استخراج اسم اللعبة
# =========================================================

def get_game_name(product):

    localized = product.get(
        "LocalizedProperties",
        []
    )

    # نحاول أخذ الاسم التركي أو أول اسم موجود
    for item in localized:

        title = item.get("ProductTitle")

        if title:
            return title


    # بديل
    title = product.get("ProductTitle")

    if title:
        return title


    return "لعبة Xbox"


# =========================================================
# استخراج السعر الصحيح من Display Catalog
# =========================================================

def get_prices_from_catalog(product):

    results = []

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

            order_data = availability.get(
                "OrderManagementData",
                {}
            )

            price_data = order_data.get(
                "Price",
                {}
            )


            if not price_data:
                continue


            # السعر الحالي
            list_price = to_float(
                price_data.get("ListPrice")
            )


            # السعر الأصلي
            msrp = to_float(
                price_data.get("MSRP")
            )


            # العملة
            currency = price_data.get(
                "CurrencyCode",
                ""
            )


            # نريد فقط الليرة التركية
            if currency and currency.upper() not in [
                "TRY",
                "TL"
            ]:
                continue


            # تجاهل الأسعار الفارغة
            if list_price is None:
                continue

            if list_price <= 0:
                continue


            # =============================================
            # إذا MSRP أكبر من السعر الحالي = تخفيض حقيقي
            # =============================================

            if (
                msrp is not None
                and msrp > list_price
            ):

                results.append(
                    (
                        list_price,
                        msrp
                    )
                )

            else:

                results.append(
                    (
                        list_price,
                        None
                    )
                )


    return results


# =========================================================
# اختيار السعر الأفضل
# =========================================================

def determine_best_price(price_pairs):

    if not price_pairs:
        return None, None


    valid_pairs = []


    for current, original in price_pairs:

        try:
            current = float(current)

        except Exception:
            continue


        # حماية من البيانات الغريبة
        if current <= 0 or current > 50000:
            continue


        if original is not None:

            try:
                original = float(original)

            except Exception:
                original = None


        # =============================================
        # تنظيف التخفيض
        # =============================================

        if original is not None:

            if original <= current:
                original = None

            elif original > 50000:
                original = None

            else:

                discount = (
                    (original - current)
                    / original
                ) * 100


                # منع خصم 100% الوهمي
                if discount >= 99:
                    original = None


        valid_pairs.append(
            (
                current,
                original
            )
        )


    if not valid_pairs:
        return None, None


    # =====================================================
    # أولاً: البحث عن تخفيض حقيقي
    # =====================================================

    discounted = []


    for current, original in valid_pairs:

        if (
            original is not None
            and original > current
        ):

            discount = (
                (original - current)
                / original
            ) * 100


            if 1 <= discount < 99:

                discounted.append(
                    (
                        current,
                        original
                    )
                )


    # إذا وجدنا تخفيض
    if discounted:

        # نزيل التكرار
        unique = list(
            set(
                (
                    round(current, 2),
                    round(original, 2)
                )
                for current, original in discounted
            )
        )


        # نختار السعر الأقل الحالي
        # لأنه غالباً العرض الحقيقي
        unique.sort(
            key=lambda x: x[0]
        )


        return unique[0]


    # =====================================================
    # بدون تخفيض
    # =====================================================

    prices = list(
        set(
            round(current, 2)
            for current, original in valid_pairs
        )
    )


    if not prices:
        return None, None


    # نأخذ أقل سعر صالح
    prices.sort()

    return prices[0], None


# =========================================================
# جلب معلومات اللعبة كاملة
# =========================================================

def get_game_info(url):


    # استخراج Product ID
    product_id = get_product_id(url)


    if not product_id:

        raise Exception(
            "ماكدر أطلع Product ID من الرابط"
        )


    print(
        "PRODUCT ID:",
        product_id
    )


    # جلب بيانات اللعبة
    product = get_product_data(
        product_id
    )


    # اسم اللعبة
    game_name = get_game_name(
        product
    )


    print(
        "GAME:",
        game_name
    )


    # استخراج الأسعار
    price_pairs = get_prices_from_catalog(
        product
    )


    print(
        "PRICE PAIRS:",
        price_pairs
    )


    # اختيار السعر الصحيح
    current_price, original_price = (
        determine_best_price(
            price_pairs
        )
    )


    if current_price is None:

        raise Exception(
            "Microsoft لم يعثر على سعر اللعبة"
        )


    return (
        game_name,
        current_price,
        original_price
    )


# =========================================================
# تنسيق سعر SA STORE
# =========================================================

def format_store_price(price):

    price = int(price)


    if price % 1000 == 0:

        return f"{price // 1000} ألف"


    return (
        f"{price:,} دينار"
        .replace(",", ".")
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🎮 أرسل رابط أي لعبة من Xbox Store\n\n"
        " وأطلعلك سعر"
    )


# =========================================================
# استقبال الرابط
# =========================================================

async def handle_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return


    text = update.message.text.strip()


    # =====================================================
    # التأكد من أنه رابط Xbox
    # =====================================================

    if "xbox.com" not in text.lower():

        await update.message.reply_text(
            "❌ يرجى إرسال رابط لعبة من Xbox Store"
        )

        return


    # =====================================================
    # رسالة الانتظار
    # =====================================================

    processing_message = await update.message.reply_text(
        "⏳ جاري البحث عن اللعبة..."
    )


    try:


        (
            game_name,
            turkey_price,
            original_price
        ) = await asyncio.to_thread(
            get_game_info,
            text
        )


        # =================================================
        # حساب سعر SA STORE
        # =================================================

        store_price = calculate_price(
            turkey_price
        )


        store_price_text = format_store_price(
            store_price
        )


        # =================================================
        # عليها تخفيض
        # =================================================

        if (
            original_price is not None
            and original_price > turkey_price
        ):


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
                f"💰 سعر: "
                f"{store_price_text} 🇮🇶"
            )


        # =================================================
        # بدون تخفيض
        # =================================================

        else:


            result = (
                f"🎮 {game_name}\n\n"
                f"💰 سعر: "
                f"{store_price_text} 🇮🇶"

                f" لطلب شراء "
                f"@Sijadsa" 
            )
        


        await processing_message.edit_text(
            result
        )


    except Exception as error:


        print(
            "ERROR:",
            repr(error)
        )


        await processing_message.edit_text(
            "❌ صار خطأ أثناء جلب معلومات اللعبة.\n\n"
            "جرّب رابط ثاني، وإذا تكرر الخطأ دزلي صورة من Deploy Logs."
        )


# =========================================================
# تشغيل البوت
# =========================================================

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


    # START
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    # استقبال الروابط
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


# =========================================================
# تشغيل البرنامج
# =========================================================

if __name__ == "__main__":
    main()
