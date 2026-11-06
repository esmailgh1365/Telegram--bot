import json
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
MINIAPP_URL = os.getenv("MINIAPP_URL")  # e.g. https://USER.github.io/Telegram--bot/
STATS = Path(__file__).parent / "docs" / "data" / "stats.json"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = None
    if MINIAPP_URL:
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📈 باز کردن مینی‌اپ", web_app=WebAppInfo(url=MINIAPP_URL))]]
        )
    await update.message.reply_text(
        "به ربات سیگنال بورس خوش آمدید.\nبرای دیدن سیگنال و آمار، مینی‌اپ را باز کنید یا /stats بزنید.",
        reply_markup=kb,
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not STATS.exists():
        await update.message.reply_text("هنوز آماری ثبت نشده است.")
        return
    s = json.loads(STATS.read_text(encoding="utf-8"))
    lines = ["📊 نرخ موفقیت سیگنال‌ها"]
    for k, name in (("daily", "روزانه"), ("weekly", "هفتگی"), ("monthly", "ماهانه")):
        p = s[k]
        rate = f"{p['win_rate']}٪ ({p['wins']}/{p['total']})" if p["total"] else "بدون داده"
        lines.append(f"{name}: {rate}")
    for o in s["open"]:
        lines.append(f"\n🔔 {o['symbol']}\n{o['explanation']}")
    lines.append("\nاین پیام توصیه‌ی مالی نیست.")
    await update.message.reply_text("\n".join(lines))


if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.run_polling()

