import os
import re
import math
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Safari/537.36"
}


def calculate_price(try_price: float) -> int:
    # تسعيرتك
    if try_price <= 25:
        return 3000
    elif try_price <= 50:
        return 4000
    else:
        return math.ceil(try_price / 100) * 6000


def get_xbox_price(url: str):
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # اسم اللعبة
    title = None

    if soup.find("meta", property="og:title"):
        title = soup.find("meta", property="og:title").get("content")

    if not title and soup.title:
        title = soup.title.text.strip()

    # محاولة استخراج السعر بالليرة التركية
    text = soup.get_text(" ", strip=True)

    patterns = [
        r"₺\s*([\d\.,]+)",
        r"([\d\.,]+)\s*TL",
        r"([\d\.,]+)\s*TRY"
    ]

    price = None

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            value = match.group(1)
            value = value.replace(".", "").replace(",", ".")

            try:
                price = float(value)
                break
            except ValueError:
                pass

    return title, price


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 SA STORE Price Bot\n\n"
        "🔎 دزلي رابط لعبة من Xbox Store التركي حتى أتحقق من سعرها."
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if "xbox.com" not in text.lower():
        await update.message.reply_text(
            "❌ دزلي رابط صحيح من Xbox Store التركي.\n\n"
            "مثال:\nhttps://www.xbox.com/tr-TR/"
        )
        return

    if "/tr-tr/" not in text.lower():
        await update.message.reply_text(
            "❌ هذا الرابط مو من Xbox Store التركي 🇹🇷\n\n"
            "لازم الرابط يكون بهذا الشكل:\n"
            "https://www.xbox.com/tr-TR/"
        )
        return

    message = await update.message.reply_text(
        "🔎 تم استلام رابط Xbox Store.\nجاري معالجة الرابط..."
    )

    try:
        game_name, try_price = get_xbox_price(text)

        if not try_price:
            await message.edit_text(
                "❌ ماكدر أطلع السعر من الرابط.\n"
                "تأكد أن اللعبة متوفرة بالـ Xbox Store التركي 🇹🇷."
            )
            return

        iq_price = calculate_price(try_price)

        await message.edit_text(
            f"🎮 اسم اللعبة:\n{game_name}\n\n"
            f"🇹🇷 سعر Xbox التركي: ₺{try_price:,.2f}\n"
            f"💰 سعر SA STORE: {iq_price:,} دينار عراقي"
        )

    except Exception as e:
        await message.edit_text(
            "❌ صار خطأ أثناء معالجة الرابط.\n"
            "جرب رابط ثاني أو تأكد من الرابط."
        )


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN غير موجود في Environment Variables")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link)
    )

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
