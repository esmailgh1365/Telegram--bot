#!/data/data/com.termux/files/usr/bin/bash
# Daily run on the phone (Termux).
# Step 1 needs an Iranian IP (tsetmc), so VPN must be OFF.
# Step 2 needs Telegram/GitHub, so VPN must be ON.
set -u
cd "$(dirname "$0")" || exit 1
[ -f "$HOME/.signals_env" ] && . "$HOME/.signals_env"
export BOT_TOKEN CHAT_ID

echo "=== STEP 1: turn VPN OFF, then press Enter ==="
read -r _
python signals.py evaluate || { echo "evaluate failed"; exit 1; }
python signals.py scan || { echo "scan failed (is VPN really off?)"; exit 1; }
python signals.py evaluate || exit 1

echo "=== STEP 2: turn VPN ON, then press Enter ==="
read -r _
python notify.py || echo "notify failed (Telegram unreachable?)"
git add docs/data
git diff --cached --quiet || git commit -qm "update signals"
git pull --rebase -q || true
git push || echo "push failed (check VPN / token)"
echo "=== done ==="
