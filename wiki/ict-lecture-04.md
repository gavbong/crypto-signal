# ICT 2024 Mentorship — Lecture #4

**Date:** August 8, 2024 (ICT's 52nd birthday)  
**Source:** https://www.youtube.com/watch?v=hdSscxZgE58  
**Duration:** ~137 minutes  
**Format:** Live forward-test session on NQ/US100 (8:00–10:00 AM Eastern)

---

## Overview

This lecture is a live walk-forward drill on Nasdaq demonstrating how to determine directional bias before a news driver using New Day Opening Gaps (NDOG), New Week Opening Gaps (NWOG), and Fair Value Gaps. ICT shows in real time how price delivers to pre-marked levels on a 15-second and 1-second chart. The session reinforces conceptual frameworks from Lectures 1–3 and explicitly teaches students to observe price action without pushing a button.

---

## Key Concepts

### New Day Opening Gap (NDOG)
- Formed by the difference between the **5:00 PM close** and the **6:00 PM open** (the 1-hour CME break) every trading day.
- **NDOG High** = max(5PM close, 6PM open); **NDOG Low** = min(5PM close, 6PM open).
- Apply a Fibonacci to the gap range:
  - **CE (Consequent Encroachment)** = 0.50 midpoint — primary draw target.
  - **Quadrant levels** = 0.25 and 0.75 — add when gap is >= ~20 handles; eyeball for smaller gaps.
- Maintain the **last 5 NDOGs** on a separate reference layout (not the active trading chart).
- After a gap is "filled" it is **NOT discarded** — the algorithm continues referencing it. Old NDOGs remain live.

### New Week Opening Gap (NWOG)
- Same construction: Friday 5PM close → Sunday 6PM open.
- Same quadrant treatment (0.25 / 0.50 / 0.75 FIB).
- Maintain the **last 5 NWOGs** on the reference layout.
- A large NWOG above current price is a strong draw target. If price runs up to a NWOG before 9:30, wait for the 10:00 AM Silver Bullet — do not chase.

### Directional Bias Rule (Pre-News / Pre-8:30)
- Count NDOGs and NWOGs clustering **above** vs **below** current price.
  - More above → bias **LONG**.
  - More below → bias **SHORT**.
  - Equal / sandwiched → **no man's land**, skip the session.
- This applies with or without a news driver. News amplifies the move but does not change direction.
- By 8:00 AM, scan relative equal highs/lows for context. By 8:30, bias should be locked in.

### Consequent Encroachment (CE)
- The 50% midpoint of any gap: NDOG, NWOG, or FVG.
- Price gravitates to CE repeatedly. Wicks do the work but bodies respect CE.
- High-probability touch — plan for it in both entries and targets.

### Fair Value Gap (FVG) / BISI / SIBI
- Three-candle formation: gap between two non-overlapping bodies.
- **BISI** (Buy Side Imbalance / Sell Side Inefficiency) = bullish gap, price left untraded going up.
- **SIBI** (Sell Side Imbalance / Buy Side Inefficiency) = bearish.
- In bullish context: bodies should respect the gap; wicks may reach CE but must repel. Full fill = warning.
- **Inversion FVG**: A BISI displaced through to the downside becomes a **bearish** reference. ICT marks these in orange. A retest from below = potential short. **Do not treat as a buy.**
- FVGs inside Breaker Blocks are the priority. "If you have a breaker and a fair value gap inside it, that's the one you want to focus on."

### Volume Imbalance
- Single-candle zone where prior candle's high overlaps with next candle's open/low — smaller inefficiency than a full FVG.
- Bodies should stay above it (bullish context); wicks may dip in.
- If price leaves a volume imbalance **open** (does not fill) → **breakaway signal** — implies 15–20+ handle continuation.

### Order Block (OB)
- The last **down-close candle** before an impulsive rally (bullish OB).
- Entry: **open of the OB candle** (worst case). Stop: **close of that OB candle** (1-tick precision common).
- If a volume imbalance sits inside the OB zone, the combined structure is the preferred entry area.
- "Every down-close candle supports price" in a bullish delivery — each OB must hold for the bull case.

### Breaker Block
- Pattern: High → Low → **Higher High** (takes out buy-side liquidity).
- The swing low from that sequence becomes a **Bearish Breaker** when price returns to it after displacing lower.
- Refinement: if a FVG sits inside the breaker zone, trade the FVG — not the breaker candles themselves.

### Balanced Price Range (BPR)
- Range where price has traded both directions — "painted." No need to revisit.
- Identified by: overlapping wick ranges of opposing candles.
- Apply FIB quadrants to BPR edges for intra-range bounce targets.
- Price hovering at a BPR edge uses the same 0.25/0.50/0.75 quadrant system.

### Institutional Order Flow Entry Drill (IOFED)
- Entry confirmation: price retraces into a FVG → CE fails to fill (bodies repel) → next candle displaces away.
- Stop: below the FVG low (or OB close containing the FVG).
- "Want to see that FVG left open — if it can leave that open, that's a breakaway gap."

### SMT Divergence (Smart Money Technique)
- Watch NQ, ES (S&P 500), and YM (Dow) simultaneously on a matrix: 5-min, 4-min, 3-min, 2-min, 1-min.
- **SMT divergence** = one index makes a new swing high/low; a correlated index fails to confirm.
- Not required for a trade but raises signal quality. "I like to see it as a qualifier — it gives a little bit more quality."
- When SMT is present alongside a FVG setup, expect faster and stronger delivery.

### The Algorithm
- ICT's core thesis: price is repriced by an **algorithm** to predetermined reference points based on time and price — not buying/selling pressure.
- The algorithm "calls back" to NDOGs, NWOGs, FVGs, and CE levels regardless of how old they are.
- Evidence demonstrated on 1-second chart: CE, quadrant, and body-alignment levels act as precise support/resistance.

---

## Setups Taught

### Setup 1: Pre-News Directional Run Into NDOG Cluster (Primary)
**Conditions:**
1. NDOG/NWOG clustering above price (bullish) or below (bearish) before 8:30 AM.
2. Price in discount zone (below 50% of most recent swing).
3. High-impact news at 8:30 — amplifies but does not change direction.

**Entry:**
- Wait for the 8:30 spool; do not trade the initial spike.
- Drop to 15-second chart.
- Look for pullback into the first BISI or volume imbalance inside an OB after the displacement.
- Enter at the **open of the OB candle**.

**Stop:** Close of the OB candle (often 1 tick).

**Targets:**
- Partial at CE of nearest NDOG above.
- Secondary: CE of next NDOG / NWOG CE.

**Invalidation:** Price breaks below OB candle low by more than 1 tick → stand aside until 9:30.

---

### Setup 2: 10:00 AM Silver Bullet (Second-Chance)
**Conditions:**
- Large initial move already happened.
- Price extended into premium NDOGs or NWOG.
- Window: 10:00–10:10 AM.

**Framework:**
- Wait for return to a discount FVG or NDOG CE.
- Look for SMT divergence on NQ vs ES vs YM to time entry.
- "If it goes up there [NWOG] I would wait until 10:00 Silver Bullet — that would be my setup."

---

### Setup 3: Inversion FVG Short
**Conditions:**
- A prior BISI has been displaced through to the downside.
- Mark original FVG in orange (inversion).
- Price rallies back to test the underside.

**Do not treat as a buy.** "We displace lower — that's not a buy."

---

### Setup 4: Reclaimed FVG
- Missed the first entry? If price returns and re-enters the same FVG → valid second entry.
- Same stop: below the FVG low.

---

## Session & Time Rules

| Time (Eastern) | Rule |
|---|---|
| Pre-7:00 AM | Load NDOGs and NWOGs onto reference layout |
| 7:00–8:00 AM | Scan relative equal highs/lows; assess NDOG/NWOG clustering |
| 8:00–8:30 AM | Finalize directional bias; identify key FVGs inside breakers above/below |
| 8:30 AM | Primary volatility event — trade the retracement, NOT the initial spike |
| 8:30–9:30 AM | Work setups on 15-second and 1-minute charts; partial into NDOG CEs |
| 9:30 AM | Opening bell — "initial volatility can easily trade all the way back down" — high caution |
| 9:30–10:00 AM | If no setup pre-bell, wait for 10:00 AM macro |
| 10:00–10:10 AM | **Silver Bullet** — primary second-chance window |
| Post-10:10 AM | If no Silver Bullet, consider morning session done |

**Macro windows (every hour):** Last 10 min of expiring hour + first 10 min of new hour — the algorithm spools there too. Applies at every hour, not just 8:30 and 10:00.

**News timing:** 8:30, 9:45, 10:00, 10:30 (crude oil inventory) are known spool times. Use **Econoday** (preferred, more complete) or **Forex Factory**.

**Day type rule:** If market makes a large 1-sided move early (100+ handles before 9:30), ICT is done. Does not chase the afternoon.

---

## What To Avoid

1. **Do not trade the initial 8:30 spike.** Price traverses 50+ handles in 1 second. You cannot execute. Position beforehand or wait for the retracement.
2. **No man's land.** If NDOGs/NWOG sandwich current price (equal clusters above and below), no bias — skip the session.
3. **Do not discard filled NDOGs.** The algorithm calls back to them. Keep last 5 active indefinitely.
4. **Inversion FVG ≠ buy.** A displaced BISI is orange, not a buy on retest.
5. **No indicator divergence.** "If you beat and torture numbers enough the data will submit to anything you want it to say." RSI/MACD divergence during valid price delivery is noise.
6. **No mental stops.** "It will make you mental. Not using a stop loss is guaranteeing that you will fail eventually."
7. **Do not watch P&L during the trade.** "You're trading your equity, not price action." Hides P&L ticker until fully developed.
8. **No real money before skill.** "It puts so much toxicity around every decision — you are fortifying and guaranteeing you'll always trade in fear."
9. **Old highs/lows are not resistance — they are stop-hunt targets.** "It's going back there to go above it — because people are shorting it and their stop losses are above that."
10. **Do not chase a NWOG run before 9:30.** If price expands to NWOG territory pre-bell, wait for 10:00 Silver Bullet.

---

## Algorithmic Notes

Mechanically extractable for signal detection:

### Level Construction
```
NDOG_HIGH = max(close_at_5PM, open_at_6PM)   # daily
NDOG_LOW  = min(close_at_5PM, open_at_6PM)
NDOG_CE   = (NDOG_HIGH + NDOG_LOW) / 2
NDOG_Q25  = NDOG_LOW + 0.25 * (NDOG_HIGH - NDOG_LOW)
NDOG_Q75  = NDOG_LOW + 0.75 * (NDOG_HIGH - NDOG_LOW)
# NWOG = same formula, Friday 5PM close → Sunday 6PM open
# Keep last 5 of each type active
```

### Bias Detection (Mechanical)
```python
gaps_above = sum(1 for g in active_ndogs + [nwog] if g.low > current_price)
gaps_below = sum(1 for g in active_ndogs + [nwog] if g.high < current_price)

if gaps_above > gaps_below:   bias = BULLISH
elif gaps_below > gaps_above: bias = BEARISH
else:                         bias = NONE  # no man's land — skip
```

### Entry Pattern (Bullish FVG + OB)
```
1. bias == BULLISH
2. current_price < 50% of most recent swing high-to-low  (discount zone)
3. Impulsive up-candle creates BISI (3-candle FVG, no overlap)
4. Price retraces into BISI
5. Wick may reach CE of BISI but body does not close below CE
6. Next candle closes above BISI low → trigger
Entry:  open of last down-close OB candle
Stop:   close of that OB candle
Target: CE of nearest NDOG above current price
```

### Inversion FVG Flag
- Any BISI that price fully displaced through → flag as INVERSION (bearish reference).
- On retest from below: treat as short entry, not long.

### Breakaway Gap Signal
- FVG left untouched for 2+ candles after a displacement (no wick overlap) → "breakaway."
- Expect 15–20+ handle continuation without significant retracement.

### SMT Filter
- Compare NQ vs ES vs YM on 1-min/2-min/3-min timeframes.
- If one makes a new swing extreme without confirmation from correlated index → SMT divergence.
- Use as quality filter: add weight to FVG signal when SMT confirms.

### Session Time Filters
- PRIMARY window: 8:20–9:30 AM Eastern (pre-news bias + retracement entry)
- SECONDARY window: 10:00–10:10 AM (Silver Bullet)
- MACRO windows: HH-10min to HH+10min at every hour
- BLOCK OUT: 9:30–10:00 AM (opening range chaos)

---

## Notable Quotes

- **On the algorithm:** "The algorithm — the price engine that pushes price — is driven by these reference points. What the algorithm does is it calls back to these points of reference based on time and price."
- **On fundamentals:** "I don't look at the CPI number, PMI, non-farm payroll trends — it's all baked into what price is going to do."
- **On news drivers:** "The news driver is the retail's excuse for why price went up. It's just highlighting the time when the market's going to start spooling."
- **On old gaps:** "You don't want to discard them — they have a life cycle of high degree of sensitivity. The algorithm calls back regardless."
- **On breakout traders:** "Short sellers want to sell on a break below those levels — they don't know what they're doing." (They are the liquidity being harvested.)
- **On support/resistance:** "Why does it need to go back up there if it's going to be resistance? It's going back to go above it — because people are shorting it and their stop losses are above that. It took years for me to figure that out."
- **On indicators:** "Divergence on any indicator is useless. If you beat and torture numbers enough the data will submit to anything you want it to say."
- **On stops:** "Not using a stop loss is guaranteeing that you will fail eventually — given enough time, that outcome always comes with failure."
- **On trading boring:** "You want your trading to be boring. A monotonous task where it's just so redundant — just like your job."
- **On SMT:** "You don't need SMT — you really don't need it. But I like to look for it because it gives me that okay, she's going to run now."
- **On the economic calendar:** "It's your TV Guide to the next important event — it tells me the time when the gazelle are going to the watering hole."
- **On P&L during a trade:** "You should not have your P&L shown while you're first taking trades — condition yourself to focus on price action."
- **On what the market is:** "Stupid money, street money, dumb money being cannibalized by smart money. And smart money uses these concepts."

---

## Live Demonstration Summary (August 8, 2024 — NQ)

All of the following happened in real time on-screen:

1. **8:30 AM**: Price spooled up 100+ handles in ~15 seconds, delivering into clustered NDOGs and NWOG that were above — confirming the pre-stated bullish bias.
2. **15-sec chart**: Price retraced to the CE of Wednesday's NDOG, leaving a BISI above → rallied.
3. Volume imbalance inside an OB held; bodies respected it; wick touched the quadrant of an adjacent BPR.
4. Price hit the CE of Tuesday's NDOG precisely — ICT's pre-stated target, confirmed live.
5. **1-second chart**: CE of Wednesday's NDOG, quadrant levels, and body-alignment levels all acted as exact support/resistance.
6. By ~10:00 AM: Price traded down to relative equal lows ICT had flagged pre-session, then reversed through them to the relative equal highs — exactly as he described.
