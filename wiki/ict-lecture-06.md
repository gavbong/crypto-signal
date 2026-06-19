# ICT 2024 Mentorship — Lecture #6 (August 12, 2024)

**Source:** Live session, Monday, August 12, 2024 (9:15 AM ET start)  
**Context:** Day-before CPI/PPI week (Tue = PPI, Wed = CPI). Lighter news day.  
**Theme:** Real-time reinforcement of Lectures 1–5 logic; OB entry precision; pre-news protocol.

---

## 1. Bearish Order Block (OB) — Entry and Stop Rules

ICT specifies the exact entry and stop for a bearish OB trade:

**Entry = Opening price of the up-close displacement candle**
- The candle that breaks above REH and closes above it is the "OB candle"
- Its opening price is the entry for the SHORT
- NOT the high, NOT the midpoint — the **open**
- Rationale: that's where the algorithm initiates delivery; highest probability fill

**Lowest threshold = bottom of the FVG formed after displacement**
- Alternative entry for those who want confirmation: bottom of the subsequent FVG
- ICT uses this when a limit at the OB open doesn't fill

**Stop = Mean Threshold (midpoint) of the OB candle**
- The OB candle's midpoint = `(open + close) / 2` (for an up-close candle = mean threshold)
- Risk is defined as distance from entry to this midpoint
- This is TIGHTER than current practice of stop-above-wick; intentionally so

```
Bearish OB trade structure:
  REH sweep candle wick pierces REH, closes above
  ↓
  Displacement impulse candle closes below REH (CHoCH)
  ↓
  Entry: opening price of the up-close OB candle
  Stop:  mean threshold = (OB_open + OB_close) / 2
  TP:    NDOG CE → session low → FVG CE → ATR fallback
```

---

## 2. Inversion Fair Value Gap (IFVG) — Sell Program Barrier

When price returns to an old FVG while in a **sell program** (NWOG above, NDOGs below):

- That old FVG is now a **resistance barrier** (inversion), not a bounce zone
- ICT calls this a "reclaimed fair value gap"
- Bodies of subsequent candles should be HELD BELOW the FVG midpoint
- If bodies stay below FVG CE → confirms sell program; look for next leg down
- If price breaks above FVG CE → sell program may be invalidated; wait

**Key rule:** Narrative (bearish) + Time (in killzone) must both agree for IFVG to work.  
If time is wrong or bias is absent, old FVGs may produce genuine bounces.

---

## 3. Pre-News Timing Protocol (CPI/PPI Weeks)

When the **next trading day** has a high-impact news driver (CPI, PPI, FOMC):

### AM session preference: 7:00–8:00 ET over 9:30 bell
- At 9:30 opening on a pre-news day, everyone is in the market → chaotic volatility
- 7:00–7:30 ET: cleaner, fewer participants, algorithm delivery is purer
- Delineate the 7:00 AM high/low as your reference frame (per Lecture #5 rules)
- Wait for REH/REL to form in the 7–7:30 window and pierce

### Aggressive partial protocol
- On pre-news days: take first partial EARLIER than normal
- Move stop to break-even immediately after first partial
- Target closest NDOG level (CE), not full session sweep
- Once stopped in profit: DO NOT re-enter; accept the day

### No Monday TGIF context
- If TGIF failed to deliver on Friday (market didn't retrace 20–30%), it defers
- Monday absorbs that pent-up move → expect choppier directional delivery
- Don't force trades at 9:30 Monday if you know big drivers are Tue/Wed

---

## 4. NWOG + NDOG Bias Rules (Reinforced)

Full decision tree explicitly restated in Lecture #6:

```
At 7:00 AM ET, assess:
  Is price ABOVE NWOG for this week?
  Are last week's NDOGs (clustering) BELOW current price?

IF BOTH TRUE:
  → Algorithm is in SELL program
  → Seek discount = drop toward NDOG cluster
  → Look for REH to form after 7 AM → pierce → bearish OB/FVG short

  IF price ABOVE NWOG AND NDOGs below:
    Price will seek fair value = go down
    Relative equal HIGHS will form → be broken → short entry

IF price BELOW NWOG AND NDOGs above:
  → Algorithm is in BUY program
  → Seek premium = rise toward NDOG cluster
  → Look for REL to form → pierce → bullish OB/FVG long

IF mixed (some above, some below):
  → No Man's Land; wait for clearer alignment
```

**Gravitational draw:** NDOG/NWOG levels are primary price draw targets, not just filters.  
The algorithm MUST deliver to those levels; the only question is WHEN.

---

## 5. Lowest Threshold Entry Rule

"I'm going to use the lowest threshold level on a fair value gap"  
= enter at the price level CLOSEST to current price that is still inside the gap

- For SHORTS: bottom of the FVG (nearest, easiest to hit)
- For LONGS: top of the FVG (nearest, easiest to hit)
- This maximizes fill probability at the cost of slightly wider risk vs OB open

**Order of preference:**
1. OB opening price (tightest risk, hardest fill)
2. Bottom/top of FVG (moderate risk, easier fill)
3. FVG CE (Consequent Encroachment — midpoint; widest but confirmed retrace)

---

## 6. Live Session Notes (August 12, 2024)

Market context on the day (NQ/ES):
- NWOG for week of Aug 11 sat BELOW price → bearish week bias
- Prior NDOGs all clustering below → algorithmic draw down
- Relative equal highs formed at 7 AM → price ran above them at 9:30ish
- Displacement below REH → bearish OB (opening price of up-close candle = entry)
- Inversion FVG formed → held price below CE → confirmed sell program
- ICT shorted, took partials, moved stop to break-even
- Stopped in profit when price briefly retraced — did NOT re-enter (pre-news discipline)
- Market then sold off to prior NDOG CE as originally targeted

---

## 7. Implementable Rules Checklist

| Rule | Already Implemented? | Notes |
|---|---|---|
| NDOG/NWOG bias filter | ✓ `_ict_ndog_bias` | Lectures 3–4 |
| REH/REL sweep detection | ✓ `_ict_find_sweep` | combined session H/L |
| FVG entry (CE half-split) | ✓ `_ict_find_fvg` | BISI/SIBI filters |
| NDOG TP chain | ✓ `_ict_find_ndog` | session → CE → ATR |
| Asian PM killzone | ✓ `_ict_in_pm_killzone` | Lecture 5 |
| OB open as entry (vs FVG midpoint) | ✗ | New in Lecture #6 |
| OB mean threshold as stop | ✗ | New in Lecture #6 |
| Inversion FVG as resistance | ✗ | New in Lecture #6 |
| Pre-news timing preference (7 AM) | partial | `killzone_hours` can be widened |

---

## Key Quotes

> "The opening price on an up-close candle when the market is in a sell program — that's my entry."

> "The risk has to be defined as much as the midpoint or mean threshold of that order block."

> "If we're above the new week opening gap and clustering of new day opening gaps below — the algorithm is going to seek fair value in a discount."

> "When narrative and time are not in agreement, even though it trades back up to these inefficiencies, it's a reclaimed fair value gap" (= IFVG, barrier not bounce).

> "On a day before CPI/PPI, take the trades early — the 7 o'clock to 8 o'clock window — not at the 9:30 bell."
