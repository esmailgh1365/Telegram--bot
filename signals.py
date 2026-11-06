"""Signal engine with support/resistance, explanations, post-mortems and learning.

Usage:
  python signals.py scan      # find today's best signal and store it
  python signals.py evaluate  # settle open signals, learn, rebuild docs/data/stats.json
  python signals.py selftest  # offline test with synthetic data

"Learning" here = online re-weighting of the filter rules from real outcomes
(each rule's weight follows its own historical win rate). It is simple and
transparent, not a neural network, and needs dozens of settled signals to matter.
"""
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "docs" / "data"
SIGNALS_FILE = DATA / "signals.json"
STATS_FILE = DATA / "stats.json"
WEIGHTS_FILE = DATA / "weights.json"

MAX_HOLD_DAYS = 10     # trading days before forced close
MIN_SCORE_RATIO = 0.70  # fraction of total rule weight required
MIN_RR = 1.5           # minimum reward/risk to accept a signal
UNIVERSE_LIMIT = 150

RULES = {  # key -> Persian label
    "ma20": "بالای میانگین ۲۰ روزه",
    "trend": "روند صعودی (MA20 > MA50)",
    "rsi": "RSI در ناحیه‌ی قدرت",
    "vol15": "حجم بالاتر از ۱.۵ برابر میانگین",
    "vol25": "جهش حجم قوی (۲.۵ برابر)",
    "breakout": "شکست سقف ۲۰ روزه",
    "controlled": "رشد کنترل‌شده‌ی امروز",
}

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
WATCH_URL = (
    "https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch?market=0"
    + "".join(f"&paperTypes%5B{i}%5D={i+1}" for i in range(9))
    + "&showTraded=false&withBestLimits=false"
)
HIST_URL = "https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{code}/0"


def http_json(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def fetch_universe():
    rows = http_json(WATCH_URL).get("marketwatch", [])
    rows = [r for r in rows if r.get("qTotTran5J")]
    rows.sort(key=lambda r: r.get("qTotCap", 0) or r.get("qTotTran5J", 0), reverse=True)
    return [(str(r["insCode"]), r.get("lva", "?")) for r in rows[:UNIVERSE_LIMIT]]


def fetch_history(code, days=120):
    rows = http_json(HIST_URL.format(code=code)).get("closingPriceDaily", [])
    rows = [r for r in rows if r.get("zTotTran", 0) > 0]
    rows.sort(key=lambda r: r["dEven"])
    out = []
    for r in rows[-days:]:
        d = str(r["dEven"])
        out.append({
            "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
            "o": r["priceFirst"], "h": r["priceMax"], "l": r["priceMin"],
            "c": r["pClosing"], "v": r["qTotTran5J"],
        })
    return out


# ---------- indicators ----------
def sma(xs, n):
    return sum(xs[-n:]) / n


def rsi(closes, n=14):
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:]):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def atr(candles, n=14):
    trs = []
    for p, x in zip(candles[-n - 1:-1], candles[-n:]):
        trs.append(max(x["h"] - x["l"], abs(x["h"] - p["c"]), abs(x["l"] - p["c"])))
    return sum(trs) / len(trs)


def pivots(candles, k=3):
    """Swing highs / lows: extreme versus k neighbours on each side."""
    highs, lows = [], []
    for i in range(k, len(candles) - k):
        win = candles[i - k:i + k + 1]
        if candles[i]["h"] == max(x["h"] for x in win):
            highs.append(candles[i]["h"])
        if candles[i]["l"] == min(x["l"] for x in win):
            lows.append(candles[i]["l"])
    return highs, lows


def levels(candles):
    """Nearest support below and resistance(s) above the last close."""
    last = candles[-1]["c"]
    highs, lows = pivots(candles[-90:-1])
    c = [x["c"] for x in candles]
    sup = [p for p in lows if p < last * 0.995]
    if len(c) >= 50 and sma(c, 50) < last:
        sup.append(sma(c, 50))
    support = max(sup) if sup else last * 0.95
    res = sorted(p for p in highs if p > last * 1.01)
    return support, res


# ---------- learning ----------
def load_weights():
    if WEIGHTS_FILE.exists():
        w = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
    else:
        w = {}
    for k in RULES:
        w.setdefault(k, {"w": 1.0, "n": 0, "wins": 0})
    return w


def save_weights(w):
    DATA.mkdir(parents=True, exist_ok=True)
    WEIGHTS_FILE.write_text(json.dumps(w, ensure_ascii=False, indent=1), encoding="utf-8")


def learn(weights, fired, won):
    """Update each fired rule; weight ~ smoothed win rate relative to 50%."""
    for k in fired:
        r = weights[k]
        r["n"] += 1
        r["wins"] += 1 if won else 0
        rate = (r["wins"] + 2) / (r["n"] + 4)      # Laplace smoothing
        r["w"] = round(max(0.3, min(2.0, rate * 2)), 3)


# ---------- scoring ----------
def score(candles, weights=None):
    """Return (weighted score, max score, fired keys, features) or None."""
    if len(candles) < 55:
        return None
    weights = weights or load_weights()
    c = [x["c"] for x in candles]
    h = [x["h"] for x in candles]
    v = [x["v"] for x in candles]
    last = c[-1]
    r = rsi(c)
    vol_ratio = v[-1] / max(sma(v[:-1], 20), 1)
    day_pct = (last / c[-2] - 1) * 100
    fired = []
    if last > sma(c, 20): fired.append("ma20")
    if sma(c, 20) > sma(c, 50): fired.append("trend")
    if 52 <= r <= 70: fired.append("rsi")
    if vol_ratio >= 1.5: fired.append("vol15")
    if vol_ratio >= 2.5: fired.append("vol25")
    if last >= max(h[-21:-1]): fired.append("breakout")
    if 0.5 <= day_pct <= 4.5: fired.append("controlled")
    total = sum(weights[k]["w"] for k in RULES)
    got = sum(weights[k]["w"] for k in fired)
    feats = {"rsi": round(r, 1), "vol_ratio": round(vol_ratio, 2), "day_pct": round(day_pct, 2)}
    return got, total, fired, feats


def build_plan(candles):
    """Entry zone, stop, targets from support/resistance + ATR. None if R/R is poor."""
    last = candles[-1]["c"]
    support, res = levels(candles)
    a = atr(candles)
    stop = max(support * 0.99, last - 2.0 * a)        # just under support, capped by ATR
    stop = min(stop, last * 0.98)                     # at least 2% room
    stop = max(stop, last * 0.94)                     # never wider than 6%
    risk = last - stop
    t1 = res[0] if res and res[0] - last >= 1.5 * risk else last + 1.5 * risk
    t2 = res[1] if len(res) > 1 and res[1] > t1 * 1.01 else last + 2.5 * risk
    rr = (t1 - last) / risk
    if rr < MIN_RR:
        return None
    return {
        "buy_low": round(max(support, last * 0.985)), "buy_high": round(last * 1.005),
        "entry": round(last), "stop": round(stop), "target": round(t1), "target2": round(t2),
        "support": round(support), "resistance": round(res[0]) if res else None,
        "rr": round(rr, 2),
    }


def explain(sym, fired, feats, plan):
    why = [RULES[k] for k in fired]
    txt = (
        f"چرا {sym}؟ " + "، ".join(why) + f". (RSI={feats['rsi']}، حجم={feats['vol_ratio']} برابر میانگین). "
        f"خرید در محدوده‌ی {plan['buy_low']:,} تا {plan['buy_high']:,}. "
        f"حمایت نزدیک {plan['support']:,}"
        + (f"، مقاومت نزدیک {plan['resistance']:,}" if plan["resistance"] else "، مقاومت بالاتری نزدیک نیست")
        + f". حد ضرر {plan['stop']:,} (زیر حمایت). فروش مرحله‌ی اول {plan['target']:,} و دوم {plan['target2']:,}. "
        f"نسبت ریسک به ریوارد {plan['rr']}."
    )
    return txt


# ---------- storage ----------
def load_signals():
    if SIGNALS_FILE.exists():
        return json.loads(SIGNALS_FILE.read_text(encoding="utf-8"))
    return []


def save_signals(sigs):
    DATA.mkdir(parents=True, exist_ok=True)
    SIGNALS_FILE.write_text(json.dumps(sigs, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- scan ----------
def scan():
    sigs = load_signals()
    weights = load_weights()
    open_syms = {s["symbol"] for s in sigs if s["status"] == "open"}
    best = None
    for code, sym in fetch_universe():
        if sym in open_syms:
            continue
        try:
            candles = fetch_history(code)
        except Exception:
            continue
        res = score(candles, weights)
        if not res or res[0] < MIN_SCORE_RATIO * res[1]:
            continue
        plan = build_plan(candles)
        if plan and (best is None or res[0] * plan["rr"] > best[0]):
            best = (res[0] * plan["rr"], res, plan, code, sym, candles[-1])
        time.sleep(0.3)
    if not best:
        print("no signal today")
        return
    _, (got, total, fired, feats), plan, code, sym, last = best
    sigs.append({
        "id": f"{last['date']}-{sym}", "date": last["date"], "symbol": sym, "code": code,
        **plan, "score": round(got, 2), "max_score": round(total, 2),
        "fired": fired, "features": feats, "explanation": explain(sym, fired, feats, plan),
        "status": "open", "result_pct": None, "closed": None,
        "post_mortem": [], "learned": False,
    })
    save_signals(sigs)
    print("signal:", sym)


# ---------- settlement & post-mortem ----------
def settle(sig, candles):
    """Walk candles after entry. Stop checked first (conservative)."""
    after = [x for x in candles if x["date"] > sig["date"]][:MAX_HOLD_DAYS]
    e = sig["entry"]
    for x in after:
        if x["l"] <= sig["stop"]:
            return "loss", round((sig["stop"] / e - 1) * 100, 2), x["date"]
        if x["h"] >= sig["target"]:
            return "win", round((sig["target"] / e - 1) * 100, 2), x["date"]
    if len(after) >= MAX_HOLD_DAYS:
        pct = round((after[-1]["c"] / e - 1) * 100, 2)
        return ("win" if pct > 0 else "loss"), pct, after[-1]["date"]
    return None


def post_mortem(sig, candles, status):
    """Rule-based analysis of why the signal worked or failed."""
    after = [x for x in candles if x["date"] > sig["date"]][:MAX_HOLD_DAYS]
    if not after:
        return []
    notes = []
    vols = [x["v"] for x in candles if x["date"] <= sig["date"]][-21:-1]
    avg_v = sum(vols) / len(vols) if vols else 1
    first = after[0]
    mfe = (max(x["h"] for x in after) / sig["entry"] - 1) * 100
    mae = (min(x["l"] for x in after) / sig["entry"] - 1) * 100
    notes.append(f"بیشترین سود لحظه‌ای {mfe:.1f}٪ و بیشترین افت {mae:.1f}٪ بود.")
    f = sig.get("features", {})
    if status == "loss":
        if first["v"] < avg_v:
            notes.append("حجم روز بعد از سیگنال کمتر از میانگین شد؛ خریدار ادامه نداد.")
        if first["c"] < sig["entry"]:
            notes.append("روز بعد پایین‌تر از قیمت ورود بسته شد؛ شکست یا جهش تایید نشد.")
        if f.get("rsi", 0) > 65:
            notes.append("RSI بالا بود (بیش از ۶۵)؛ احتمالاً سهم نزدیک اشباع خرید بود.")
        if "breakout" not in sig.get("fired", []):
            notes.append("سیگنال بدون شکست سقف بود و مقاومت جلوی آن را گرفت.")
        if mfe >= (sig["target"] / sig["entry"] - 1) * 100 * 0.6:
            notes.append("قیمت به بیش از ۶۰٪ مسیر هدف رسید و برگشت؛ فروش پلکانی می‌توانست ضرر را کم کند.")
        notes.append("درس: امتیاز همین قوانین کمی کاهش یافت تا دفعه‌ی بعد سخت‌گیری بیشتری شود.")
    else:
        if first["v"] >= avg_v:
            notes.append("حجم روز بعد حفظ شد؛ تایید خریداران.")
        if "breakout" in sig.get("fired", []):
            notes.append("شکست سقف ۲۰ روزه با حجم همراه بود و ادامه پیدا کرد.")
        notes.append("درس: وزن قوانین فعال این سیگنال بیشتر شد.")
    return notes


def evaluate():
    sigs = load_signals()
    weights = load_weights()
    for sig in sigs:
        if sig["status"] != "open":
            continue
        try:
            candles = fetch_history(sig["code"])
            res = settle(sig, candles)
        except Exception:
            continue
        if res:
            sig["status"], sig["result_pct"], sig["closed"] = res
            sig["post_mortem"] = post_mortem(sig, candles, sig["status"])
            if not sig.get("learned"):
                learn(weights, sig.get("fired", []), sig["status"] == "win")
                sig["learned"] = True
    save_signals(sigs)
    save_weights(weights)
    build_stats(sigs, weights)


# ---------- stats ----------
def _period(sigs, since):
    done = [s for s in sigs if s["status"] in ("win", "loss") and s["closed"] >= since]
    wins = sum(1 for s in done if s["status"] == "win")
    n = len(done)
    return {
        "total": n, "wins": wins, "losses": n - wins,
        "win_rate": round(100 * wins / n, 1) if n else None,
        "avg_return": round(sum(s["result_pct"] for s in done) / n, 2) if n else None,
    }


def insights(weights):
    rows = [{"key": k, "label": RULES[k], "n": r["n"],
             "win_rate": round(100 * r["wins"] / r["n"]) if r["n"] else None, "weight": r["w"]}
            for k, r in weights.items() if k in RULES]
    return sorted(rows, key=lambda r: -r["weight"])


def build_stats(sigs, weights=None, today=None):
    today = today or date.today()
    weights = weights or load_weights()
    iso = lambda d: d.isoformat()
    stats = {
        "updated": datetime.now().isoformat(timespec="minutes"),
        "daily": _period(sigs, iso(today)),
        "weekly": _period(sigs, iso(today - timedelta(days=7))),
        "monthly": _period(sigs, iso(today - timedelta(days=30))),
        "all": _period(sigs, "0000"),
        "open": [s for s in sigs if s["status"] == "open"],
        "recent": sorted(sigs, key=lambda s: s["date"], reverse=True)[:30],
        "insights": insights(weights),
    }
    DATA.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    return stats


# ---------- offline test ----------
def _synthetic(n=80):
    import random
    random.seed(1)
    c, price = [], 1000.0
    for i in range(n):
        price *= 1 + random.uniform(-0.01, 0.012)
        c.append({"date": f"2026-01-{i+1:03d}", "o": price, "h": price * 1.01,
                  "l": price * 0.99, "c": price, "v": 1000})
    c[-1].update(c=c[-2]["c"] * 1.03, h=c[-2]["c"] * 1.04, v=3500)
    return c


def selftest():
    c = _synthetic()
    w = load_weights()
    got, total, fired, feats = score(c, w)
    plan = build_plan(c)
    print("score", got, "/", total, fired)
    print("plan", plan)
    assert plan and plan["stop"] < plan["entry"] < plan["target"] < plan["target2"]
    assert plan["buy_low"] <= plan["entry"] <= plan["buy_high"]
    print(explain("TEST", fired, feats, plan)[:120], "...")

    sig = {"date": "2026-01-070", "entry": 100, "target": 105, "stop": 97, "fired": ["breakout"],
           "features": {"rsi": 70}}
    mk = lambda d, h, l, cl, v=1000: {"date": d, "h": h, "l": l, "c": cl, "v": v}
    assert settle(sig, [mk("2026-01-071", 106, 99, 104)]) == ("win", 5.0, "2026-01-071")
    assert settle(sig, [mk("2026-01-071", 101, 96, 98)]) == ("loss", -3.0, "2026-01-071")
    assert settle(sig, [mk("2026-01-071", 106, 96, 100)])[0] == "loss"
    assert settle(sig, [mk("2026-01-071", 102, 99, 101)]) is None
    flat = [mk(f"2026-02-{i:03d}", 102, 99, 101) for i in range(MAX_HOLD_DAYS)]
    assert settle(sig, flat) == ("win", 1.0, "2026-02-009")

    notes = post_mortem(sig, [mk("2026-01-068", 1, 1, 1, 2000), mk("2026-01-069", 1, 1, 1, 2000), mk("2026-01-070", 1, 1, 1, 2000), mk("2026-01-071", 101, 96, 98, 500)], "loss")
    assert any("حجم" in n for n in notes) and any("RSI" in n for n in notes), notes

    wt = {k: {"w": 1.0, "n": 0, "wins": 0} for k in RULES}
    for _ in range(10):
        learn(wt, ["breakout"], True)
        learn(wt, ["rsi"], False)
    assert wt["breakout"]["w"] > 1.4 and wt["rsi"]["w"] < 0.7, wt
    print("weights after 10 wins/10 losses:", wt["breakout"]["w"], wt["rsi"]["w"])

    sigs = [
        {"status": "win", "result_pct": 5, "closed": "2026-11-06", "date": "2026-11-01"},
        {"status": "loss", "result_pct": -3, "closed": "2026-11-04", "date": "2026-11-01"},
        {"status": "win", "result_pct": 5, "closed": "2026-10-20", "date": "2026-10-10"},
        {"status": "open", "result_pct": None, "closed": None, "date": "2026-11-05"},
    ]
    st = build_stats(sigs, wt, today=date(2026, 11, 6))
    assert st["daily"]["win_rate"] == 100.0 and st["weekly"]["total"] == 2
    assert st["monthly"]["total"] == 3 and st["all"]["win_rate"] == 66.7
    STATS_FILE.unlink()
    print("selftest OK")


if __name__ == "__main__":
    {"scan": scan, "evaluate": evaluate, "selftest": selftest}[sys.argv[1]]()
