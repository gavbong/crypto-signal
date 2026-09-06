#!/usr/bin/env bash
# premarket_gappers.sh — Scan top premarket gappers with news catalysts
#
# Scheduled daily Mon–Fri at 08:30 ET via systemd timer (premarket-gappers.timer).
# Data source: stockanalysis.com/markets/gainers/?p=premarket
# News catalyst: benzinga.com/quote/{TICKER}
#
# Usage:  bash scripts/premarket_gappers.sh
# Output: ./data/premarket_gappers/premarket_gappers_YYYY-MM-DD.json
#
# Requires: Python 3 (stdlib only — no pip installs needed)

set -euo pipefail

# ── Config (export so Python reads them as env vars) ──────────────────────────
# Use New York time for date so the file is named correctly regardless of
# the server's system timezone.
export GAPPER_DATE=$(TZ=America/New_York date +%Y-%m-%d)
export GAPPER_SCAN_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
export GAPPER_OUTPUT="./data/premarket_gappers/premarket_gappers_${GAPPER_DATE}.json"

# ── Guards ─────────────────────────────────────────────────────────────────────
# 1. Skip if already ran today (timer restart or manual duplicate)
if [ -f "$GAPPER_OUTPUT" ]; then
    echo "Already ran today (${GAPPER_DATE} ET) — ${GAPPER_OUTPUT} exists. Skipping." >&2
    exit 0
fi

# 2. Skip if premarket window has closed (market opens 09:30 ET)
_HHMM=$(TZ=America/New_York date +%H%M)
if [ "$((10#$_HHMM))" -ge 930 ]; then
    echo "Premarket closed ($(TZ=America/New_York date +%H:%M) ET ≥ 09:30). Data stale — skipping." >&2
    exit 0
fi
export GAPPER_MIN_GAP=5
export GAPPER_MIN_PRICE=3
export GAPPER_MIN_VOL=50000
export GAPPER_MAX_TICKERS=10

# ── Detect Python (Windows stub returns exit 49 even when found by PATH) ──────
PYTHON=""
if python3 -c "pass" 2>/dev/null; then
    PYTHON=python3
elif py -3 -c "pass" 2>/dev/null; then
    PYTHON="py -3"
elif python -c "pass" 2>/dev/null; then
    PYTHON=python
else
    echo "ERROR: Python 3 not found." >&2
    exit 1
fi

# Use quoted heredoc so bash does NOT expand \s \d etc. inside the Python code.
# All runtime values are passed via the GAPPER_* env vars set above.
$PYTHON - <<'PYEOF'
import os, sys, json, re, time, urllib.request, urllib.error

DATE        = os.environ["GAPPER_DATE"]
SCAN_TIME   = os.environ["GAPPER_SCAN_TIME"]
OUTPUT      = os.environ["GAPPER_OUTPUT"]
MIN_GAP     = float(os.environ["GAPPER_MIN_GAP"])
MIN_PRICE   = float(os.environ["GAPPER_MIN_PRICE"])
MIN_VOL     = float(os.environ["GAPPER_MIN_VOL"])
MAX_TICKERS = int(os.environ["GAPPER_MAX_TICKERS"])

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s).strip()


def parse_volume(s):
    """Parse '1,234,567' or '1.23M' style volume strings."""
    s = s.strip().upper().replace(",", "")
    m = re.match(r"^([0-9.]+)([MKBT]?)$", s)
    if not m:
        return 0
    num = float(m.group(1))
    mult = {"M": 1_000_000, "K": 1_000, "B": 1_000_000_000, "T": 1_000_000_000_000}
    return int(num * mult.get(m.group(2), 1))


# ── 1. Fetch gainers ──────────────────────────────────────────────────────────
# ?p=premarket shows premarket movers when run 4-9:30 AM ET;
# falls back to regular session gainers outside those hours.
GAINERS_URL = "https://stockanalysis.com/markets/gainers/?p=premarket"

print(f"Fetching {GAINERS_URL} ...", file=sys.stderr)
try:
    html = fetch(GAINERS_URL)
except Exception as e:
    print(f"ERROR: fetch failed: {e}", file=sys.stderr)
    sys.exit(1)

# SSR table rows follow a 7-column repeating pattern:
# rank | symbol | name | change% | price | volume | market_cap
tds = re.findall(r"<td[^>]*>(.*?)</td>", html, re.DOTALL)
cells = [strip_tags(td) for td in tds]

COLS = 7
gainers = []
for i in range(0, len(cells) - COLS + 1, COLS):
    row = cells[i : i + COLS]
    if not re.match(r"^\d+$", row[0]):       # col 0 must be a rank number
        continue
    if not re.match(r"^[A-Z]{1,5}$", row[1]):  # col 1 must be a ticker
        continue
    try:
        gap_pct = float(row[3].rstrip("%").replace("+", ""))
        price   = float(row[4].replace(",", ""))
        vol     = parse_volume(row[5])
    except (ValueError, TypeError):
        continue
    gainers.append({"symbol": row[1], "price": price, "gap_pct": gap_pct, "premarket_volume": vol})

print(f"Parsed {len(gainers)} rows", file=sys.stderr)

# ── 2. Filter + rank ──────────────────────────────────────────────────────────
filtered = [
    g for g in gainers
    if g["gap_pct"] > MIN_GAP and g["price"] > MIN_PRICE and g["premarket_volume"] > MIN_VOL
]
filtered.sort(key=lambda x: x["gap_pct"], reverse=True)
top = filtered[:MAX_TICKERS]
print(
    f"Filters (gap>{MIN_GAP}% price>${MIN_PRICE} vol>{int(MIN_VOL):,}): "
    f"{len(filtered)} qualify, taking top {len(top)}",
    file=sys.stderr,
)

if not top:
    with open(OUTPUT, "w") as f:
        json.dump({"scanned_at": SCAN_TIME, "gappers": []}, f, indent=2)
    print(f"No qualifying gappers. Written to {OUTPUT}", file=sys.stderr)
    print(f"Premarket Gappers: 0 names. Top: (none)")
    sys.exit(0)


# ── 3. Benzinga catalyst fetch ────────────────────────────────────────────────
_HTML_ENTITIES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&#39;": "'", "&apos;": "'",
}

def decode_html(s):
    for ent, char in _HTML_ENTITIES.items():
        s = s.replace(ent, char)
    return s.strip()

_SKIP_TITLE = re.compile(
    r"(?:stock price|quote|news|history|benzinga|cookie|privacy|subscribe|sign in|log in)",
    re.IGNORECASE,
)


def get_catalyst(symbol):
    """Returns (catalyst_str_or_None, [headline, ...]).
    Never raises — on any error returns (None, [])."""
    try:
        html = fetch(f"https://www.benzinga.com/quote/{symbol}", timeout=15)
    except Exception as e:
        print(f"  {symbol}: fetch failed ({e})", file=sys.stderr)
        return None, []

    headlines = []

    # Pass 1: JSON "headline" or "title" fields — skip page-level titles
    for m in re.finditer(r'"(?:headline|title)"\s*:\s*"([^"\\]{15,})"', html):
        title = decode_html(m.group(1))
        if _SKIP_TITLE.search(title):
            continue
        if title not in headlines:
            headlines.append(title)
        if len(headlines) == 2:
            break

    # Pass 2: <h3>/<h2> with non-trivial text
    if not headlines:
        for m in re.finditer(r"<h[23][^>]*>(.*?)</h[23]>", html, re.DOTALL | re.IGNORECASE):
            title = decode_html(strip_tags(m.group(1)))
            if len(title) < 20 or _SKIP_TITLE.search(title):
                continue
            if title not in headlines:
                headlines.append(title)
            if len(headlines) == 2:
                break

    # Pass 3: <a> tags with headline-like class
    if not headlines:
        for m in re.finditer(
            r'class="[^"]*(?:headline|article-title)[^"]*"[^>]*>(.*?)</a>',
            html,
            re.DOTALL | re.IGNORECASE,
        ):
            title = decode_html(strip_tags(m.group(1)))
            if len(title) >= 20 and not _SKIP_TITLE.search(title) and title not in headlines:
                headlines.append(title)
            if len(headlines) == 2:
                break

    return (headlines[0] if headlines else None), headlines[:2]


result_gappers = []
for i, g in enumerate(top):
    sym = g["symbol"]
    print(f"  [{i+1}/{len(top)}] {sym} ({g['gap_pct']:.1f}%) — catalyst ...", file=sys.stderr)
    catalyst, headlines = get_catalyst(sym)
    print(f"         {(catalyst or '(none)')[:90]}", file=sys.stderr)
    result_gappers.append({
        "rank": i + 1,
        "symbol": sym,
        "price": round(g["price"], 2),
        "gap_pct": round(g["gap_pct"], 2),
        "premarket_volume": g["premarket_volume"],
        "catalyst": catalyst,
        "headlines": headlines,
    })
    if i < len(top) - 1:
        time.sleep(2)

# ── 4. Write JSON ─────────────────────────────────────────────────────────────
import os as _os
_os.makedirs(_os.path.dirname(OUTPUT), exist_ok=True)
with open(OUTPUT, "w") as f:
    json.dump({"scanned_at": SCAN_TIME, "gappers": result_gappers}, f, indent=2)
print(f"\nSaved {len(result_gappers)} gappers → {OUTPUT}", file=sys.stderr)

# ── 5. Summary line (stdout) ──────────────────────────────────────────────────
n = len(result_gappers)
parts = [
    f"{t['symbol']} ({t['gap_pct']:.1f}%) — {t['catalyst'] or 'no catalyst'}"
    for t in result_gappers[:3]
]
print(f"Premarket Gappers: {n} names. Top: {', '.join(parts)}")
PYEOF
