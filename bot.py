import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 SA STORE Price Bot\n\n"
        "دزلي رابط لعبة من Xbox Store حتى أتحقق منه 🔎"
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if "xbox.com" in text.lower():
        await update.message.reply_text(
            "🔎 تم استلام رابط Xbox Store.\n"
            "جاري معالجة الرابط..."
        )
    else:
        await update.message.reply_text(
            "❌ هذا مو رابط Xbox Store.\n\n"
            "دزلي رابط اللعبة من موقع Xbox Store."
        )


def main():
    token = os.getenv("BOT_TOKEN")

    if not token:
        raise ValueError("BOT_TOKEN غير موجود في Environment Variables")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link)
    )

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
