import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 SA STORE Price Bot\n\n"
        "دزلي رابط لعبة من Xbox Store وسأبحث عن السعر."
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if "xbox.com" in text:
        await update.message.reply_text("🔎 Finding the lowest price...")
    else:
        await update.message.reply_text("❌ دزلي رابط صحيح من Xbox Store.")


def main():
    token = os.getenv("BOT_TOKEN")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    app.run_polling()


if __name__ == "__main__":
    main()
