"""
scripts/collect_index_data.py — Build 6-month backtest CSV for index instruments.

yfinance caps 15m history at 60 days. Run this script weekly (Windows Task
Scheduler or cron) to stitch downloads into a rolling CSV. Deduplicates by
timestamp so reruns are safe.

Usage:
    python scripts/collect_index_data.py [--output-dir data/indices]

Symbol map:
    DJ30/USD    → ^DJI   (Dow Jones Industrial Average)
    FTSE100/USD → ^FTSE  (FTSE 100)
    DAX/USD     → ^GDAXI (DAX)
    XAU/USD     → GC=F   (Gold futures front month)
    US500/USD   → ES=F   (S&P 500 E-mini futures)
    NAS100/USD  → NQ=F   (Nasdaq-100 E-mini futures)
    BRENT/USD   → BZ=F   (Brent crude oil futures)
"""
import argparse
import csv
import sys
from pathlib import Path

try:
    import yfinance as yf
    import pandas as pd
except ImportError:
    print("ERROR: yfinance and pandas are required. Run: pip install yfinance pandas")
    sys.exit(1)

SYMBOLS = {
    "DJ30/USD":    "^DJI",
    "FTSE100/USD": "^FTSE",
    "DAX/USD":     "^GDAXI",
    "XAU/USD":     "GC=F",
    "US500/USD":   "ES=F",
    "NAS100/USD":  "NQ=F",
    "BRENT/USD":   "BZ=F",
}


def download_and_stitch(pair: str, ticker: str, output_dir: Path) -> int:
    """Download last 60 days of 15m data and append to CSV. Returns new rows added."""
    safe_name = pair.replace("/", "_")
    output_path = output_dir / f"{safe_name}_15m.csv"

    existing_ts: set[str] = set()
    if output_path.exists():
        with open(output_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing_ts.add(row["datetime"])

    df = yf.download(ticker, period="60d", interval="15m", progress=False, auto_adjust=True)
    if df.empty:
        print(f"  {pair}: no data returned from yfinance")
        return 0

    # yfinance ≥0.2.x returns MultiIndex columns: ('Close', '^DJI') etc.
    # Flatten to single-level first, then reset_index to get Datetime column.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    df = df.reset_index()

    # Datetime may be named 'Datetime', 'Date', or be the unnamed index
    ts_col = None
    for candidate in ("Datetime", "Date", "index"):
        if candidate in df.columns:
            ts_col = candidate
            break
    if ts_col is None:
        # Last resort: first column
        ts_col = df.columns[0]

    df[ts_col] = pd.to_datetime(df[ts_col], utc=True)

    mode = "a" if output_path.exists() else "w"
    new_rows = 0
    with open(output_path, mode, newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if mode == "w":
            writer.writerow(["datetime", "open", "high", "low", "close", "volume"])
        for _, row in df.iterrows():
            ts = str(row[ts_col])
            if ts in existing_ts:
                continue
            writer.writerow([
                ts,
                round(float(row["Open"]), 4),
                round(float(row["High"]), 4),
                round(float(row["Low"]), 4),
                round(float(row["Close"]), 4),
                int(row.get("Volume", 0)),
            ])
            new_rows += 1

    return new_rows


def main():
    parser = argparse.ArgumentParser(
        description="Stitch yfinance 15m index data for backtesting"
    )
    parser.add_argument(
        "--output-dir", default="data/indices",
        help="Output directory for CSV files (default: data/indices)"
    )
    parser.add_argument(
        "--pairs", nargs="*", choices=list(SYMBOLS.keys()),
        help="Specific pairs to download (default: all)"
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs_to_run = {k: v for k, v in SYMBOLS.items()
                   if args.pairs is None or k in args.pairs}

    total_new = 0
    for pair, ticker in pairs_to_run.items():
        safe_name = pair.replace("/", "_")
        try:
            added = download_and_stitch(pair, ticker, output_dir)
            csv_path = output_dir / f"{safe_name}_15m.csv"
            row_count = sum(1 for _ in open(csv_path)) - 1  # subtract header
            print(f"  {pair} ({ticker}): +{added} new rows | total {row_count} rows -> {csv_path}")
            total_new += added
        except Exception as e:
            print(f"  {pair}: ERROR — {e}")

    print(f"\nDone. {total_new} new rows added across {len(pairs_to_run)} pairs.")
    print("Run weekly to build 6-month history. backtest.py reads from data/indices/. ")


if __name__ == "__main__":
    main()
