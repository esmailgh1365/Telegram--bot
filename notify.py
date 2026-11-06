"""Send new / settled signals to Telegram from GitHub Actions (no always-on server needed).

Env: BOT_TOKEN, CHAT_ID (your user id, or a channel like @mychannel)
Usage: python notify.py   # sends signals not yet announced, and results of closed ones
"""
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).parent / "docs" / "data"
SIGNALS = DATA / "signals.json"
SENT = DATA / "sent.json"
TOKEN = os.getenv("BOT_TOKEN")
CHAT = os.getenv("CHAT_ID")
DISCLAIMER = "\n\nاین پیام توصیه‌ی مالی نیست."


def send(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": CHAT, "text": text}).encode()
    urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=30).read()


def main():
    if not (TOKEN and CHAT and SIGNALS.exists()):
        print("nothing to do (missing BOT_TOKEN/CHAT_ID or no signals)")
        return
    sigs = json.loads(SIGNALS.read_text(encoding="utf-8"))
    sent = json.loads(SENT.read_text()) if SENT.exists() else {}
    for s in sigs:
        sid = s["id"]
        if s["status"] == "open" and "open" not in sent.get(sid, []):
            send(f"🔔 سیگنال جدید: {s['symbol']}\n{s['explanation']}{DISCLAIMER}")
            sent.setdefault(sid, []).append("open")
        elif s["status"] in ("win", "loss") and "closed" not in sent.get(sid, []):
            icon = "✅ موفق" if s["status"] == "win" else "❌ ناموفق"
            pm = "\n".join(s.get("post_mortem", []))
            send(f"{icon}: {s['symbol']} ({s['result_pct']}٪)\n{pm}{DISCLAIMER}")
            sent.setdefault(sid, []).append("closed")
    SENT.write_text(json.dumps(sent, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
