# ربات سیگنال بورس (تلگرام + مینی‌اپ)

## ساختار
- `signals.py` موتور سیگنال (اسکن، ارزیابی، یادگیری وزن قوانین)
- `notify.py` ارسال سیگنال و نتیجه به تلگرام
- `bot.py` دستورهای `/start` و `/stats` و دکمه‌ی مینی‌اپ
- `docs/` مینی‌اپ (GitHub Pages) و داده‌ها در `docs/data/`
- `.github/workflows/signals.yml` اجرای خودکار روزانه

## راه‌اندازی
1. در BotFather ربات بسازید و توکن بگیرید.
2. GitHub: Settings → Pages → Source: `main` و پوشه‌ی `/docs`.
3. GitHub: Settings → Secrets and variables → Actions:
   - `BOT_TOKEN` توکن ربات
   - `CHAT_ID` شناسه‌ی عددی خودتان (از @userinfobot) یا `@نام_کانال`
4. یک بار به ربات خودتان پیام `/start` بدهید (وگرنه نمی‌تواند به شما پیام بدهد).
5. Actions → signals → Run workflow برای تست.
6. برای دستورها: `pip install -r requirements.txt` و اجرای
   `BOT_TOKEN=... MINIAPP_URL=https://USER.github.io/Telegram--bot/ python bot.py`
   روی سرور یا کامپیوتر همیشه روشن.
7. تست آفلاین موتور: `python signals.py selftest`

این ابزار توصیه‌ی مالی نیست.
