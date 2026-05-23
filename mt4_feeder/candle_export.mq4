//+------------------------------------------------------------------+
//| candle_export.mq4                                                |
//| Writes 15m OHLCV candles to JSON in the MT4 Common Files folder  |
//| on every completed 15m bar.                                      |
//|                                                                  |
//| Install:                                                         |
//|   1. Copy to MetaTrader 4/MQL4/Experts/                         |
//|   2. Attach to a chart for each instrument:                      |
//|        DJ30 chart  → set PairName = "DJ30/USD"                   |
//|        FTSE100 chart → set PairName = "FTSE100/USD"              |
//|        DAX chart   → set PairName = "DAX/USD"                    |
//|        XAU chart   → set PairName = "XAU/USD"                    |
//|   3. Make sure "Allow DLL imports" is OFF (not needed)           |
//|      and "Allow live trading" can be OFF (read-only EA)          |
//|                                                                  |
//| Output path (FILE_COMMON):                                       |
//|   %APPDATA%\MetaQuotes\Terminal\Common\Files\candles_<sym>.json  |
//+------------------------------------------------------------------+
#property copyright "mexc-signal-engine"
#property strict

input int    CandleCount = 100;     // Candles to export per file (excluding current bar)
input string PairName    = "";      // Canonical pair name, e.g. "DJ30/USD". Empty = use Symbol()
input bool   UseCommonFolder = true; // Write to Common Files (true) or terminal Files (false)

datetime _lastBarTime = 0;

//+------------------------------------------------------------------+
int OnInit()
{
    EventSetTimer(30);  // Poll every 30s — catches bar close within half a minute
    _Export();          // Export immediately on attach
    return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
    EventKillTimer();
}

void OnTimer()
{
    datetime barTime = iTime(Symbol(), PERIOD_M15, 0);
    if(barTime != _lastBarTime)
    {
        _lastBarTime = barTime;
        _Export();
    }
}

void OnTick()
{
    datetime barTime = iTime(Symbol(), PERIOD_M15, 0);
    if(barTime != _lastBarTime)
    {
        _lastBarTime = barTime;
        _Export();
    }
}

//+------------------------------------------------------------------+
void _Export()
{
    string sym    = Symbol();
    string pair   = (PairName == "") ? sym : PairName;
    string safeSym = sym;
    StringReplace(safeSym, "/", "_");
    StringReplace(safeSym, "\\", "_");
    StringReplace(safeSym, ":", "_");
    string filename = "candles_" + safeSym + ".json";

    int bars = MathMin(CandleCount, iBars(sym, PERIOD_M15) - 1);
    if(bars < 2)
    {
        Print("candle_export [", sym, "]: not enough bars (", bars, ") — waiting");
        return;
    }

    int flags = FILE_WRITE | FILE_TXT | FILE_ANSI;
    if(UseCommonFolder) flags = flags | FILE_COMMON;

    int fh = FileOpen(filename, flags);
    if(fh == INVALID_HANDLE)
    {
        Print("candle_export [", sym, "]: cannot open ", filename,
              " error=", GetLastError(),
              UseCommonFolder ? " (common folder)" : " (terminal folder)");
        return;
    }

    // Write JSON array: oldest first (index bars..1), skip bar 0 (incomplete)
    FileWriteString(fh, "[\n");
    for(int i = bars; i >= 1; i--)
    {
        datetime ts  = iTime(sym,   PERIOD_M15, i);
        double   op  = iOpen(sym,   PERIOD_M15, i);
        double   hi  = iHigh(sym,   PERIOD_M15, i);
        double   lo  = iLow(sym,    PERIOD_M15, i);
        double   cl  = iClose(sym,  PERIOD_M15, i);
        long     vol = iVolume(sym, PERIOD_M15, i);

        bool isLast = (i == 1);
        string line = StringFormat(
            "  {\"time\":%d,\"open\":%.5f,\"high\":%.5f,\"low\":%.5f,\"close\":%.5f,"
            "\"volume\":%d,\"pair\":\"%s\"}%s\n",
            (long)ts, op, hi, lo, cl, vol, pair, isLast ? "" : ","
        );
        FileWriteString(fh, line);
    }
    FileWriteString(fh, "]\n");
    FileClose(fh);

    Print("candle_export [", sym, "]: wrote ", bars, " candles → ", filename);
}
