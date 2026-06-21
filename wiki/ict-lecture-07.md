# ICT 2024 Mentorship — Lecture #7 (August 13, 2024)

**Source:** Live session, Tuesday, August 13, 2024  
**Context:** PPI day (8:30 AM report). Choppy, one-directional post-news grind all morning.  
**Theme:** Hourly macro windows; breakaway gap entry drill; PPI/CPI day framework; algorithm spooling.

---

## 1. Hourly Macro Windows — The 20-Minute Algorithm Cycle

**Core rule:** Every hour, at ±10 minutes around the top of the hour, the algorithm runs to one of three things.

```
Every 60-minute interval:
  HH:50 to (HH+1):10  ← 20-minute macro window

  The algorithm will spool to ONE of:
    1. Nearest FVG (if present after a consolidation breakout)
    2. Nearest Order Block (if no FVG)
    3. Short-term high or low (buy/sell side liquidity)

  It cannot target all three simultaneously — they cannot occupy
  the same price at the same time. Usually only one or two are present.
```

**Key named macro windows (ET):**
| Window | Name | Notes |
|---|---|---|
| 10:50–11:10 | 11 o'clock macro | Clearest intraday macro; live-traded in this lecture |
| 9:50–10:10 | 10 o'clock macro / Silver Bullet | Primary setup on news days |
| 00:00–01:00 | Midnight macro | Overnight / Asia session |
| Final hour | Closing macros | ICT has covered these in other content; not detailed here |

> "Every hour a macro is in operation. Every single hour. Some macros are better than others — I'll leave that for the book."

**ICT's "spooling" analogy:**  
Like a fishing line leaving the reel as the lure is cast — the macro window is where price delivers efficiently, cleanly, in one direction. Outside the macro, price chops and grinds. *Inside* the macro, the reel is spooling: clean impulsive moves to the target.

```
Outside macro: cars and trucks on a gridlocked highway — movement exists but no direction
Inside macro:  fishing line spooling off the reel — clean, fast, directional delivery
```

**Manual intervention exception:**  
FOMC (2:00 PM and 2:30 PM) is NOT a macro — it's forced, one-sided, and destructive. Do not attempt to trade it as a macro. Wait for delivery to complete.

---

## 2. Macro Target Priority: FVG → OB → Liquidity

When the 20-minute macro window opens, the algorithm seeks its target in this priority order:

**Priority 1 — FVG (Fair Value Gap)**
- If a FVG formed after a consolidation breakout is present (see Section 3), it is the primary draw
- The algorithm will retrace into the FVG, touch CE or candle-low, and reverse
- FVG must be a "breakaway gap" (formed after stop hunt + consolidation exit) to qualify

**Priority 2 — Order Block**
- If no FVG is present, look for the nearest OB (last down-close candle before a bullish impulse, or last up-close candle before a bearish impulse)
- "Change in state of delivery" rule applies: the opening price of the OB candle is the algorithmically targeted price

**Priority 3 — Short-term High or Low (Liquidity)**
- If neither FVG nor OB qualifies, the algorithm sweeps a recent short-term high (buy stops) or low (sell stops)

> "There's no condition that has all three. They can't occupy the same space at the same time. It's two at best, but never all three — usually it's one or the other."

---

## 3. Breakaway Gap — FVG That Stays Open

A **breakaway gap** is a FVG that forms AFTER price exits a consolidation range (following a stop hunt). It tends not to fill completely and acts as a support/resistance reference.

**Conditions that make a FVG a breakaway gap:**
1. Price consolidates (compressed, stagnant range)
2. Stops are hunted below/above the range (wick through swing low/high)
3. Price then breaks ABOVE the range high (for longs) or BELOW the range low (for shorts)
4. A FVG forms after that breakout impulse

```
Breakaway gap sequence:
  Consolidation range forms
     ↓
  Stop hunt (wick below range low / above range high)
     ↓
  Price breaks above range high (bullish) / below range low (bearish)
     ↓
  FVG forms during / just after the breakout impulse
     → This FVG is a BREAKAWAY GAP — expect it to stay open
```

**Why it stays open:** The stop hunt + breakout is an algorithmic "state change." The FVG after it is a departure gap — the algorithm has no incentive to return and fill it fully.

**When to expect it to fill:** If narrative fails or higher TF bias is absent. An unfilled FVG that suddenly fills completely signals the breakaway failed; exit or watch for reversal.

---

## 4. IOF Entry Drill — Low Resistance Barrier Entry

**IOF (Institutional Orderflow) Entry Drill** is ICT's preferred way to enter a breakaway gap FVG.

**Entry logic:**
- Place a **limit order at the FVG bottom** (for longs: candle-low of c0)
- One tick below that candle's low triggers the fill
- You are NOT waiting for price to be inside the FVG — the limit sits at its lower edge
- This gives the **lowest-risk, highest-probability fill** without demanding price go to the midpoint

**Fill zone when using CE/midpoint:**
- If you miss the candle-low fill or spread makes it difficult, the "low resistance barrier" zone is between the **CE midpoint and the candle's low** (upper half for longs)
- Never try to fill at the very bottom of the FVG (spread risk; algorithm often stops one tick short)

```
For a LONG in a breakaway gap:
  FVG = [c0_high (fvg_bottom), c2_low (fvg_top)]
  CE  = midpoint = (fvg_top + fvg_bottom) / 2

  IOF Entry Drill fill zone: [CE, fvg_top]   ← upper half (BISI)
  IOF limit placement: at fvg_bottom (c0 high)
  Fill triggered: one tick below c0 high
  Stop: mean threshold of OB candle (Lecture #6 rule)
  TP: nearest PD array on higher timeframe (e.g., daily volume imbalance)
```

> "The most sensitive area in a FVG is the midpoint to the high of it — the candle low. Even if I'm wrong and it trades down to the low, it doesn't matter because I'm going to get filled either at that candle's low or just above the CE midpoint."

> "I am never trying to get a fill at the low end. The spread won't let me and if it goes there it won't fill me. I want the low-hanging fruit."

---

## 5. PPI/CPI Day Protocol (Extended from Lecture #6)

This lecture provides the most detailed statement of the news-day framework:

**Pre-report (before 8:30 ET):**
- Do NOT attempt to identify initial buy side or sell side setups
- Do NOT set directional bias or targets — nobody knows what the report will do
- Sit on hands

**Post-report (8:30 ET onward):**
- Wait for the initial volatility wave to complete ("let the storm pass")
- Use the **7:00–9:30 AM ET range** as the session framework — all operating hours, but nothing before 7 AM (avoid London complexity)
- After identifying the 7–9:30 range, annotate relative equal highs and lows within it
- Do NOT try to set up initial buy/sell side sweeps INTO these levels until after 9:30

**On-the-bell (9:30 ET):**
- Usually one-sided, one-shot delivery in the direction of the news impulse
- "Long in the tooth" — don't chase the opening bell move; it's already run
- Wait for price to settle and macro windows to provide entries

**Primary target on news days:** 10:00 Silver Bullet macro (9:50–10:10 ET)
- Even on NFP: skip the 8:30 chaos entirely, wait for 10:00 Silver Bullet
- This is the "cleanest" entry window after news-day manipulation

**Aggressive partial protocol (reinforced from Lecture #6):**
- On PPI/CPI day: take first partial as soon as target is touched
- Do not re-enter after being stopped in profit
- "Take it and leave and don't regret it"

---

## 6. Higher Timeframe PD Array as TP Target

**Rule:** Once entered on a macro-window FVG, the TP target must come from a higher timeframe PD array — not just the intraday swing high.

**Process:**
1. Identify the nearest **daily** PD array above (for longs) or below (for shorts) the current price
2. The "easiest obvious level" on the daily chart is the first inefficiency you encounter
3. Common daily TPs: daily volume imbalance (SIBI/BISI on daily), daily FVG, daily OB opening price

In the live session (NQ, Aug 13):
- Entered at 10:52 (inside 10:50–11:10 macro) on a breakaway FVG
- TP = daily volume imbalance above (not just the intraday swing high)
- The macro window (10:50–11:10) gave the full run from the FVG to the daily target

> "From entering here at 10:52 into this fair value gap, you have all the way up to 11:10 to see any new entry. All through this period from here to here, relative to time — this is a time window."

---

## 7. Change in State of Delivery — OB Opening Price

When an order block has **consecutive down-close (or up-close) candles**, the algorithm targets the opening price of the most recent candle that is adjacent to the FVG:

```
Bearish OB with FVG above (bullish context):
  Three consecutive down-close candles: A, B, C (C is most recent, adjacent to FVG)
  Algorithm targets: C's opening price
  Why: "Highest of the three consecutive candles" → change in state of delivery
  Validation: Price trades above C's open → OB is confirmed, delivery resumes upward
```

This is the same logic as Lecture #6's OB entry (open of the displacement candle), extended to consecutive-candle sequences.

---

## 8. Live Session Notes (August 13, 2024)

Instrument: NQ / NASDAQ September delivery contract.

**Pre-market:** Weekly chart shows SIBI near 18,883 as potential resistance. ICT wary.

**8:30 AM:** PPI report releases — one-directional bull run from open; do NOT chase.

**9:30 AM:** Opening bell — single-shot delivery from open to weekly level. "Long in the tooth."

**10:00 macro:** Relative equal highs form after 9:30. ICT waits. Price creates REH.

**10:10:** Price breaks above REH → leaves consolidation. Stop hunt below range confirmed. FVG forms = breakaway gap.

**10:52 (inside 10:50–11:10 macro):**
- Price retraces into breakaway FVG
- ICT identifies this as IOF entry drill opportunity
- Daily volume imbalance is the target above

**Outcome:** Price delivers from FVG (10:52) to daily volume imbalance (11:10) — full macro window delivery. Caleb (student) would have captured 30 handles by exiting at midpoint.

**ICT's choice:** Did NOT trade the setup despite narrating it live — PPI day, he was satisfied with explanation. "There are lots of things all day long that I may be looking at but I'm not going to push the button."

---

## 9. Implementable Rules Checklist

| Rule | Already Implemented? | Notes |
|---|---|---|
| Killzone gates (AM + PM) | ✓ `_ict_in_killzone`, `_ict_in_pm_killzone` | Lectures 5–6 |
| REH/REL sweep detection | ✓ `_ict_find_sweep` | combined session H/L |
| FVG entry (CE half-split) | ✓ `_ict_find_fvg` | BISI/SIBI + CHoCH filters |
| OB open as entry | ✓ `sig["ob_entry"]` | Lecture #6 |
| OB mean threshold as stop | ✓ `ob_mean` stop logic | Lecture #6 |
| NDOG/NWOG bias filter | ✓ `_ict_ndog_bias` | Lectures 3–4 |
| NDOG TP chain | ✓ `_ict_find_ndog` | session → CE → ATR |
| Silver Bullet timing (10:00 AM) | partial | killzone_hours already covers 09:00–11:00 |
| Hourly macro windows (10:50–11:10 etc.) | ✗ | New in Lecture #7; would narrow valid entry window within killzone |
| Breakaway gap filter (FVG after consolidation stop hunt) | ✗ | New in Lecture #7; separate from CHoCH logic |
| IOF entry drill (limit at FVG bottom) | ✗ | New in Lecture #7; current entry is close-based |
| Higher TF PD array as TP | partial | NDOG/NWOG chain is the closest analogue |

---

## Key Quotes

> "Every hour a macro is in operation — every single hour. Some macros are better than others."

> "The market will spool — it jumps and runs to one of two things: a short-term low to tap liquidity, a short-term high to engage buy stops, or it trades to an inefficiency to invite smart money right before price spools to the liquidity."

> "Inefficiencies that stay open are going to act like real support or resistance. This is acting as a breakaway gap."

> "Once we're outside of this range and if we have a fair value gap — those tend to be left open."

> "I am never trying to get a fill at the low end. I want the low-hanging fruit — the low resistance barriers to entry."

> "The real runs start in there [the macro window] — and then after 10:50 price can still advance but look how shitty it gets."

> "On a PPI or CPI day — just wait until the Silver Bullet at 10:00. That's the easiest way."

> "Take one little win and leave. Don't look back. Shake the dust off the trading day and leave it."
