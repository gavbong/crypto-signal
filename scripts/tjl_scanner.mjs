/**
 * Trend Join Long (TJL) Strategy Scanner
 *
 * Prerequisites:
 *   1. Chrome open with TradingView and CDP on port 9222
 *      (run C:\Users\tongl\launch-tradingview.bat first)
 *   2. TradingView chart must be visible (not hidden/minimized)
 *
 * Usage:
 *   node scripts/tjl_scanner.mjs [AMD,NVDA,MU]   <- custom universe
 *   node scripts/tjl_scanner.mjs                 <- default universe
 *
 * Output:
 *   - JSON file: data/tjl_watchlists/tjl_watchlist_YYYY-MM-DD_HHMMet.json
 *   - Telegram: only on first run of the day OR new PASS hits
 */

import { writeFileSync, readFileSync, existsSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import http  from 'http';
import https from 'https';

const __dirname  = dirname(fileURLToPath(import.meta.url));
const ROOT       = join(__dirname, '..');
const OUTPUT_DIR = join(ROOT, 'data', 'tjl_watchlists');
const STATE_FILE = join(OUTPUT_DIR, 'today_state.json');

mkdirSync(OUTPUT_DIR, { recursive: true });

// ── Load tradingview-mcp core ─────────────────────────────────────────────────
const TV_MCP    = 'file:///C:/Users/tongl/tradingview-mcp/src/core/';
const chartCore = await import(TV_MCP + 'chart.js');
const dataCore  = await import(TV_MCP + 'data.js');
const healthMod = await import(TV_MCP + 'health.js');

// ── Config ────────────────────────────────────────────────────────────────────
const SMA_PERIOD = 200;
const SETTLE_MS        = 2500;

// ── .env reader ───────────────────────────────────────────────────────────────
function readEnv() {
  const envPath = join(ROOT, '.env');
  if (!existsSync(envPath)) return {};
  const env = {};
  for (const line of readFileSync(envPath, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$/);
    if (m) env[m[1]] = m[2].trim().replace(/^["']|["']$/g, '');
  }
  return env;
}

// ── Telegram ──────────────────────────────────────────────────────────────────
function sendTelegram(token, chatId, text) {
  if (!token || !chatId || token.startsWith('your_')) return Promise.resolve();
  return new Promise((resolve) => {
    const body = JSON.stringify({ chat_id: chatId, text, parse_mode: 'Markdown' });
    const req = https.request({
      hostname: 'api.telegram.org',
      path: `/bot${token}/sendMessage`,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, res => { res.resume(); resolve(); });
    req.on('error', () => resolve());
    req.write(body);
    req.end();
  });
}

// ── State management ──────────────────────────────────────────────────────────
function loadState(today) {
  try {
    if (existsSync(STATE_FILE)) {
      const s = JSON.parse(readFileSync(STATE_FILE, 'utf8'));
      if (s.date === today) return s;
    }
  } catch { /* corrupt state — start fresh */ }
  return { date: today, passes: [], run_count: 0 };
}

function saveState(state) {
  writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const sleep = ms => new Promise(r => setTimeout(r, ms));

function etNow() {
  return new Date(new Date().toLocaleString('en-US', { timeZone: 'America/New_York' }));
}

function isWithinTimeGate() {
  const et = etNow();
  const day = et.getDay();
  if (day === 0 || day === 6) return false;
  const h = et.getHours() + et.getMinutes() / 60;
  return h >= 10.0 && h < 15.5;
}

function padTwo(n) { return String(n).padStart(2, '0'); }

function scanTimestamp() {
  const et = etNow();
  const date = `${et.getFullYear()}-${padTwo(et.getMonth()+1)}-${padTwo(et.getDate())}`;
  const time = `${padTwo(et.getHours())}${padTwo(et.getMinutes())}et`;
  const label = `${padTwo(et.getHours())}:${padTwo(et.getMinutes())} ET`;
  return { date, time, label, iso: new Date().toISOString() };
}

function loadGappersUniverse(date) {
  const f = join(ROOT, 'data', 'premarket_gappers', `premarket_gappers_${date}.json`);
  if (!existsSync(f)) return null;
  try {
    const symbols = JSON.parse(readFileSync(f, 'utf8')).gappers
      ?.map(g => g.symbol).filter(Boolean) ?? [];
    return symbols.length > 0 ? symbols : null;
  } catch { return null; }
}

function fetchGappersFromDashboard(env, date) {
  const base  = (env.DASHBOARD_URL || 'http://localhost:5000').replace(/\/$/, '');
  const token = env.DASHBOARD_TOKEN || '';
  const url   = `${base}/api/gappers/today?date=${date}`;
  const isHttps = url.startsWith('https');
  return new Promise(resolve => {
    const req = (isHttps ? https : http).get(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }, res => {
      if (res.statusCode !== 200) { res.resume(); return resolve(null); }
      let body = '';
      res.on('data', c => body += c);
      res.on('end', () => {
        try {
          const symbols = JSON.parse(body).gappers?.map(g => g.symbol).filter(Boolean) ?? [];
          resolve(symbols.length > 0 ? symbols : null);
        } catch { resolve(null); }
      });
    });
    req.on('error', () => resolve(null));
  });
}

function extractIntradayLevels(bars) {
  const todayET = etNow();
  const todayStr = `${todayET.getFullYear()}-${padTwo(todayET.getMonth()+1)}-${padTwo(todayET.getDate())}`;
  let pmh = null, hod = null;

  for (const bar of bars) {
    const barET   = new Date(new Date(bar.time * 1000).toLocaleString('en-US', { timeZone: 'America/New_York' }));
    const barDate = `${barET.getFullYear()}-${padTwo(barET.getMonth()+1)}-${padTwo(barET.getDate())}`;
    if (barDate !== todayStr) continue;
    const h = barET.getHours() + barET.getMinutes() / 60;
    if (h >= 4.0 && h < 9.5)  pmh = pmh === null ? bar.high : Math.max(pmh, bar.high);
    else if (h >= 9.5)         hod = hod === null ? bar.high : Math.max(hod, bar.high);
  }
  return { pmh, hod };
}

// ── Per-ticker scan ───────────────────────────────────────────────────────────
async function scanTicker(symbol) {
  const result = { symbol, result: null, reason: '', daily: null, intraday: null };

  await chartCore.setSymbol({ symbol });
  await sleep(SETTLE_MS);
  await chartCore.setTimeframe({ timeframe: 'D' });
  await sleep(SETTLE_MS);

  const daily = await dataCore.getOhlcv({ count: SMA_PERIOD + 10, summary: false });
  if (!daily.success || daily.bars.length < SMA_PERIOD + 1) {
    result.result = 'error';
    result.reason  = `Insufficient daily bars (${daily.bars?.length ?? 0})`;
    return result;
  }

  const bars            = daily.bars;
  const lastBar         = bars[bars.length - 1];
  const sma200          = bars.slice(bars.length - SMA_PERIOD).reduce((s, b) => s + b.close, 0) / SMA_PERIOD;
  const prev_daily_high = lastBar.high;
  const prev_daily_close = lastBar.close;

  const quote   = await dataCore.getQuote({});
  const curr_px = quote.last ?? quote.close ?? prev_daily_close;

  result.daily = {
    curr_px:          +curr_px.toFixed(4),
    prev_daily_high:  +prev_daily_high.toFixed(4),
    prev_daily_close: +prev_daily_close.toFixed(4),
    sma200:           +sma200.toFixed(2),
    above_sma200:     prev_daily_close > sma200,
    above_prev_high:  curr_px > prev_daily_high,
  };

  if (!(curr_px > prev_daily_high && prev_daily_close > sma200)) {
    const why = curr_px <= prev_daily_high
      ? `curr_px ${curr_px.toFixed(2)} not above prev_daily_high ${prev_daily_high.toFixed(2)}`
      : `prev_daily_close ${prev_daily_close.toFixed(2)} below SMA200 ${sma200.toFixed(2)}`;
    result.result = 'fail_daily';
    result.reason  = why;
    return result;
  }

  if (!isWithinTimeGate()) {
    result.result = 'fail_intraday';
    result.reason  = 'daily OK — outside trading hours (10:00–15:30 ET)';
    result.intraday = { pmh: null, hod: null };
    return result;
  }

  await chartCore.setTimeframe({ timeframe: '1' });
  await sleep(SETTLE_MS);

  const intra     = await dataCore.getOhlcv({ count: 400, summary: false });
  const { pmh, hod } = extractIntradayLevels(intra.bars ?? []);

  result.intraday = {
    pmh:       pmh !== null ? +pmh.toFixed(4) : null,
    today_hod: hod !== null ? +hod.toFixed(4) : null,
  };

  if (pmh === null || hod === null) {
    result.result = 'fail_intraday';
    result.reason  = `No intraday bars for today (pmh=${pmh}, hod=${hod})`;
    return result;
  }

  if (!(curr_px > pmh && curr_px > hod)) {
    const why = curr_px <= pmh
      ? `curr_px ${curr_px.toFixed(2)} not above PMH ${pmh.toFixed(2)}`
      : `curr_px ${curr_px.toFixed(2)} not above RTH HOD ${hod.toFixed(2)}`;
    result.result = 'fail_intraday';
    result.reason  = why;
    return result;
  }

  result.result = 'PASS';
  result.reason  = `px ${curr_px.toFixed(2)} > PMH ${pmh.toFixed(2)} & HOD ${hod.toFixed(2)}`;
  return result;
}

// ── Build Telegram message ────────────────────────────────────────────────────
function buildMessage(ts, passes, newPasses, isFirstRun) {
  const header = `🎯 *TJL Watchlist* — ${ts.label}`;
  const fmt = r => {
    const d = r.daily, id = r.intraday;
    const pmh = id?.pmh != null ? id.pmh.toFixed(2) : 'n/a';
    return `• ${r.symbol} @ $${d.curr_px.toFixed(2)} (PMH $${pmh}, prev_high $${d.prev_daily_high.toFixed(2)}, SMA200 $${d.sma200.toFixed(2)})`;
  };
  if (isFirstRun) {
    if (passes.length === 0) return `${header}\nNo TJL hits this run.`;
    return [header, ...passes.map(fmt)].join('\n');
  }
  // New hits only
  return [header, ...newPasses.map(fmt)].join('\n');
}

// ── Main ──────────────────────────────────────────────────────────────────────

// Health check
let hc;
try {
  hc = await healthMod.healthCheck();
} catch (e) {
  console.error('ERROR: Cannot connect to TradingView CDP. Run launch-tradingview.bat first.\n', e.message);
  process.exit(1);
}
if (!hc.api_available) {
  console.error('ERROR: TradingView chart API not available. Ensure a chart is open.');
  process.exit(1);
}

const ts      = scanTimestamp();
const env     = readEnv();
const state   = loadState(ts.date);
const isFirstRun = state.run_count === 0;
state.run_count++;

// Universe: CLI arg > local gappers file > dashboard API > error
let universe, universeSource;
if (process.argv[2]) {
  universe = process.argv[2].split(',').map(s => s.trim().toUpperCase());
  universeSource = 'cli';
} else {
  let gappers = loadGappersUniverse(ts.date);
  if (gappers) {
    universeSource = `local gappers file (${gappers.length})`;
  } else {
    console.log('  No local gappers file — fetching from dashboard API...');
    gappers = await fetchGappersFromDashboard(env, ts.date);
    if (gappers) {
      universeSource = `dashboard API (${gappers.length})`;
    } else {
      console.error(`ERROR: Could not load gappers for ${ts.date} — local file missing and dashboard unreachable.\nEnsure Scanner A has run today, or open an SSH tunnel (ssh -L 5000:localhost:5000 root@<YOUR_SERVER_IP>), or pass tickers as a CLI arg.`);
      process.exit(1);
    }
  }
  universe = gappers;
}

console.log(`\nTJL Scanner — ${ts.date} ${ts.label} (run #${state.run_count})`);
console.log(`Universe [${universeSource}]: ${universe.join(', ')} | ${isWithinTimeGate() ? 'Market OPEN' : 'Outside hours'}`);
console.log('─'.repeat(60));

const tickerResults = [];
for (const symbol of universe) {
  process.stdout.write(`  ${symbol}... `);
  const r = await scanTicker(symbol);
  tickerResults.push(r);
  console.log(`${r.result === 'PASS' ? '✓ PASS' : r.result} — ${r.reason}`);
}

console.log('─'.repeat(60));
const passes    = tickerResults.filter(t => t.result === 'PASS');
const newPasses = passes.filter(t => !state.passes.includes(t.symbol));

console.log(`Setups: ${passes.length}/${universe.length}${newPasses.length > 0 ? ` | NEW: ${newPasses.map(t=>t.symbol).join(', ')}` : ''}`);

// ── Notify ────────────────────────────────────────────────────────────────────
const errors       = tickerResults.filter(t => t.result === 'error');
const shouldNotify = isFirstRun || newPasses.length > 0 || errors.length > 0;
if (shouldNotify) {
  const msg = buildMessage(ts, passes, newPasses, isFirstRun);
  console.log('\nSending Telegram...');
  await sendTelegram(env.TELEGRAM_BOT_TOKEN_2, env.TELEGRAM_CHAT_ID_2, msg);
} else {
  console.log('No new hits — staying quiet.');
}

// ── Persist state ─────────────────────────────────────────────────────────────
state.passes = passes.map(t => t.symbol);
saveState(state);

// ── Write JSON ────────────────────────────────────────────────────────────────
const filename = `tjl_watchlist_${ts.date}_${ts.time}.json`;
writeFileSync(join(OUTPUT_DIR, filename), JSON.stringify({
  scan_time:  ts.iso,
  run_number: state.run_count,
  universe,
  tickers:    tickerResults,
}, null, 2));
console.log(`Saved: data/tjl_watchlists/${filename}`);

process.exit(0);
