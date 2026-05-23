"""
mt4_feeder.py — Windows-side feeder for mexc-signal-engine index data.

Reads OHLCV JSON files written by candle_export.mq4 from the MT4 Common Files
folder and POSTs new candles to the Hetzner server's /api/index/feed endpoint.

Setup:
    1. Install Python on Windows: winget install Python.Python.3.12
    2. pip install requests
    3. Set environment variables (or edit CONFIG below):
         MT4_FILES_DIR   — path to MT4 Common Files (auto-detected if unset)
         INDEX_FEED_URL  — e.g. http://<YOUR_SERVER_IP>:5000 (or via SSH tunnel)
         INDEX_FEED_API_KEY — shared secret (must match server env var)
    4. Run manually: python mt4_feeder.py
       Or loop continuously: python mt4_feeder.py --loop
       Or schedule via Windows Task Scheduler every 15 minutes (single-run mode).

Symbol → canonical pair mapping:
    Edit SYMBOL_MAP below to match your broker's symbol names.
    Common Trade Nation names: US30, UK100, GER40 or GER30, XAUUSD
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import requests

# ── Configuration ─────────────────────────────────────────────────────────────

# MT4 symbol name → canonical pair name sent to the server
# Trade Nation common names — check your MT4 Market Watch for exact names
SYMBOL_MAP: dict[str, str] = {
    # Trade Nation (dot-wrapped format)
    ".US30.":   "DJ30/USD",
    ".UK100.":  "FTSE100/USD",
    ".DE40.":   "DAX/USD",
    ".DE30.":   "DAX/USD",
    # Generic / other brokers
    "US30":     "DJ30/USD",
    "US30.":    "DJ30/USD",
    "USTEC":    "DJ30/USD",
    "UK100":    "FTSE100/USD",
    "UK100.":   "FTSE100/USD",
    "GER40":    "DAX/USD",
    "GER40.":   "DAX/USD",
    "GER30":    "DAX/USD",
    "DE30":     "DAX/USD",
    "DE40":     "DAX/USD",
    "XAUUSD":   "XAU/USD",
    "GOLD":     "XAU/USD",
    "XAU":      "XAU/USD",
}

# ── Paths & defaults ──────────────────────────────────────────────────────────

LOG_FILE = Path(__file__).parent / "mt4_feeder.log"
STATE_FILE = Path(__file__).parent / "mt4_feeder_state.json"

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_S = 5
LOOP_INTERVAL_S = 15 * 60  # 15 minutes

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("mt4_feeder")


# ── State (last posted timestamp per pair) ────────────────────────────────────

def _load_state() -> dict[str, int]:
    """Load last-posted timestamp per pair from disk."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict[str, int]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ── MT4 files discovery ───────────────────────────────────────────────────────

def _find_mt4_files_dir() -> Path | None:
    """Auto-discover MT4 Common Files folder on Windows."""
    appdata = os.environ.get("APPDATA") or os.path.expanduser(r"~\AppData\Roaming")
    common = Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"
    if common.exists():
        return common

    # Fallback: search all terminal instances for any candles_*.json file
    terminal_root = Path(appdata) / "MetaQuotes" / "Terminal"
    if terminal_root.exists():
        for term_dir in terminal_root.iterdir():
            candidate = term_dir / "MQL4" / "Files"
            if candidate.exists() and any(candidate.glob("candles_*.json")):
                log.info(f"Auto-discovered MT4 files at: {candidate}")
                return candidate
    return None


def _get_files_dir() -> Path:
    env_path = os.environ.get("MT4_FILES_DIR")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
        log.warning(f"MT4_FILES_DIR={env_path} does not exist — trying auto-detect")

    discovered = _find_mt4_files_dir()
    if discovered:
        return discovered

    raise RuntimeError(
        "MT4 Files directory not found. Set MT4_FILES_DIR environment variable to the "
        "path of your MT4 Common Files folder:\n"
        r"  e.g. C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\Common\Files"
    )


# ── Candle reading ────────────────────────────────────────────────────────────

def _read_candles(json_path: Path) -> list[dict] | None:
    """Read candles from a JSON file. Returns None on parse error (MT4 mid-write)."""
    try:
        raw = json_path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.debug(f"{json_path.name}: JSON parse error (mid-write?) — {e}")
        return None
    except OSError as e:
        log.warning(f"{json_path.name}: read error — {e}")
        return None


def _symbol_from_filename(filename: str) -> str | None:
    """Extract symbol from candles_<SYMBOL>.json → SYMBOL."""
    stem = Path(filename).stem  # candles_US30 → candles_US30
    if stem.startswith("candles_"):
        return stem[len("candles_"):]
    return None


# ── HTTP POST ─────────────────────────────────────────────────────────────────

def _post_candles(url: str, api_key: str, candles: list[dict]) -> bool:
    """POST candle batch to server. Returns True on success."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = requests.post(
                f"{url.rstrip('/')}/api/index/feed",
                json=candles,
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 200:
                result = resp.json()
                log.debug(f"  → {result['inserted']} inserted, {result['skipped']} skipped")
                return True
            elif resp.status_code == 401:
                log.error("Authentication failed — check INDEX_FEED_API_KEY on both ends")
                return False
            else:
                log.warning(f"  HTTP {resp.status_code}: {resp.text[:200]} (attempt {attempt})")
        except requests.ConnectionError as e:
            log.warning(f"  Connection error (attempt {attempt}): {e}")
        except requests.Timeout:
            log.warning(f"  Timeout (attempt {attempt})")
        except Exception as e:
            log.warning(f"  Unexpected error (attempt {attempt}): {e}")

        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_BACKOFF_S * attempt)

    log.error(f"  Failed after {RETRY_ATTEMPTS} attempts")
    return False


# ── Main feed cycle ───────────────────────────────────────────────────────────

def run_once(files_dir: Path, server_url: str, api_key: str) -> int:
    """Read all candle files and POST new candles. Returns total candles sent."""
    state = _load_state()
    total_sent = 0

    json_files = sorted(files_dir.glob("candles_*.json"))
    if not json_files:
        log.warning(f"No candles_*.json files found in {files_dir}")
        log.warning("Is candle_export.mq4 attached to your MT4 charts?")
        return 0

    for json_file in json_files:
        symbol = _symbol_from_filename(json_file.name)
        if symbol is None:
            continue

        pair = SYMBOL_MAP.get(symbol)
        if pair is None:
            log.debug(f"Skipping {json_file.name}: symbol '{symbol}' not in SYMBOL_MAP")
            continue

        candles = _read_candles(json_file)
        if candles is None:
            log.debug(f"Skipping {json_file.name}: unreadable (mid-write?)")
            continue
        if not isinstance(candles, list) or not candles:
            log.debug(f"Skipping {json_file.name}: empty or invalid")
            continue

        # Override pair name from SYMBOL_MAP (feeder is authoritative for canonical names)
        for c in candles:
            c["pair"] = pair

        # Deduplicate: only send candles newer than last posted timestamp
        last_ts = state.get(pair, 0)
        new_candles = [c for c in candles if int(c["time"]) > last_ts]

        if not new_candles:
            log.debug(f"{pair}: no new candles (last_ts={last_ts})")
            continue

        log.info(f"{pair}: sending {len(new_candles)} new candles (newest ts={new_candles[-1]['time']})")

        if _post_candles(server_url, api_key, new_candles):
            newest_ts = max(int(c["time"]) for c in new_candles)
            state[pair] = newest_ts
            _save_state(state)
            total_sent += len(new_candles)
        else:
            log.error(f"{pair}: POST failed — will retry next cycle")

    return total_sent


def main():
    parser = argparse.ArgumentParser(description="MT4 candle feeder for mexc-signal-engine")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuously every 15 minutes (default: single run)")
    parser.add_argument("--interval", type=int, default=LOOP_INTERVAL_S,
                        help=f"Loop interval in seconds (default: {LOOP_INTERVAL_S})")
    args = parser.parse_args()

    server_url = os.environ.get("INDEX_FEED_URL", "").rstrip("/")
    api_key    = os.environ.get("INDEX_FEED_API_KEY", "")

    if not server_url:
        log.error("INDEX_FEED_URL not set. Example: set INDEX_FEED_URL=http://<YOUR_SERVER_IP>:5000")
        return 1

    try:
        files_dir = _get_files_dir()
    except RuntimeError as e:
        log.error(str(e))
        return 1

    log.info(f"MT4 feeder starting | files_dir={files_dir} | server={server_url}")
    log.info(f"Watching pairs: {sorted(set(SYMBOL_MAP.values()))}")

    if args.loop:
        log.info(f"Loop mode: running every {args.interval}s")
        while True:
            try:
                sent = run_once(files_dir, server_url, api_key)
                log.info(f"Cycle complete: {sent} candles sent")
            except Exception as e:
                log.error(f"Cycle error: {e}")
            time.sleep(args.interval)
    else:
        sent = run_once(files_dir, server_url, api_key)
        log.info(f"Done: {sent} candles sent")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
