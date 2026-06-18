# ICT 2024 Mentorship — Lecture #2
**Date:** August 6, 2024
**Source:** https://www.youtube.com/watch?v=pkI4AgC4OPI

---

## Overview

Lecture #2 is a live-chart session focused on building the foundational daily observation protocol for intraday trading, using only 15-minute, 5-minute, and 1-minute time frames. ICT walks through the complete morning workflow: identifying relative equal highs/lows starting at 7:00 AM New York time, annotating fair value gaps (SIBI/BISI) with volume-imbalance precision, and recognizing inversion fair value gaps within stop-hunt/breaker sequences. The session clarifies contradictions from Lecture #1 (London session vs. AM session timing) and introduces three hourly macro windows (7:00, 8:00, 9:00) each with a 30-minute manipulation leg before the directional expansion.

---

## Key Concepts

### Relative Equal Highs and Relative Equal Lows (RE Highs / RE Lows)

- Definition: two swing highs (or lows) at approximately the same price level, representing resting liquidity (buy stops above, sell stops below).
- Formation rule: the right-side candidate of a valid RE High is **slightly lower** than the left-side high. This asymmetry is the confirmation.
- Do **not** annotate them before they fully form. Never lead expectations with an anticipated setup; wait for the signature to appear in price.
- Starting time: **only annotate RE highs/lows that form after 7:00 AM New York time**. Anything before 7:00 AM belongs to the London session scope and must be ignored by beginners.
- Exception for advanced traders: if you understand London session setups and daily range profiles, you may reference pre-7:00 AM RE highs/lows for continuation/reversal context only.
- Workflow order: identify RE highs/lows on 15m first, then 5m, then 1m.
- Once one side is taken (e.g., RE highs swept), attention immediately shifts to the opposing RE lows as the draw.

### Fair Value Gap (FVG) — SIBI vs. BISI

- **SIBI (Sell Side Imbalance, Buy Side Inefficiency):** created by a **down-close** candle. The gap exists between the prior candle's low and the subsequent candle's high, bridged only by the down-close candle's body. Signals bearish delivery. On a return, price is expected to resist here and continue lower.
- **BISI (Buy Side Imbalance, Sell Side Inefficiency):** created by an **up-close** candle. The gap exists between the prior candle's high and the subsequent candle's low. Signals bullish delivery.
- Always annotate the **original** FVG levels (low, midpoint/CE, high) and extend them to the right. They remain relevant throughout the session and can be revisited multiple times.
- Track the **remaining inefficiency**: the portion of the original FVG not yet retouched. The small remaining gap between the current candle's high and the original FVG's low is still valid, even if it looks trivial.
- When in a bearish narrative (price confirmed lower), focus exclusively on **SIBIs** (down-close FVGs) for trade direction alignment. Ignore BISIs unless narrative reverses.

### Volume Imbalance — Precision Filter on FVGs

- A volume imbalance exists when **consecutive candle bodies do not overlap or touch**. This is the true gap, not the wick-to-wick gap.
- If a FVG contains a volume imbalance within it, **any wick that penetrates the FVG but does not reach the Consequent Encroachment (CE, the 50% midpoint) should be completely disregarded**. The wick is noise; the body boundary is the true level.
- Rule: ignore wicks below CE inside a FVG if a volume imbalance is present. Only the body of the candle defines the boundary.
- This removes the ambiguity created by price spiking into a FVG without actually delivering to the relevant body level.

### Consequent Encroachment (CE)

- The 50% midpoint of any FVG (or any PD array).
- Acts as the primary reference for fill confirmation. Price trading to CE is the standard expectation for a reaction.
- An Inversion FVG that was previously bullish but is now acting bearish will frequently produce a reaction at CE before continuing the move.
- When price bumps above CE by a small amount, this is the algorithm providing the spread for limit-order fills — not true buying pressure.

### Inversion Fair Value Gap (IFVG)

- Every PD array (FVG, breaker, order block, mitigation block) can **reverse its role**.
- A BISI (up-close FVG, originally bullish) that forms inside a bearish stop-run range becomes an **Inversion FVG** — it now acts as resistance on any return.
- Highest-probability IFVGs are the ones that:
  1. Formed inside the price leg that created a stop hunt (swept RE highs or RE lows).
  2. Are the first FVG prior to the stop hunt.
- IFVG use: after RE highs are taken and price breaks lower, find the first up-close FVG (BISI) inside the prior up-leg. Extend it forward. When price retraces into it, that is the **Optimal Trade Entry (OTE)** for a short.
- Do not treat a BISI inside an extended bearish move as a buy setup — it is an IFVG (short entry) in that context.

### Bearish Breaker

- Structure: a sequence of consecutive down-close candles immediately before a stop hunt, followed by a sharp reversal lower.
- The last down-close candle in the sequence prior to the stop-hunt run is the "most sensitive" level.
- Stop placement for a short via the breaker: above the **highest high of all consecutive down-close candles** forming the breaker, plus 1–2 ticks.
- If a BISI (IFVG) exists inside the breaker range, prefer the IFVG as entry over the breaker low — it offers higher precision and smaller stop.
- If no IFVG is present inside the leg, use the breaker itself.

### Optimal Trade Entry (OTE)

- ICT's flagship pattern (introduced ~2012): a shift in market structure (stop-hunt above RE high → breakdown), then measure from the swing high to the swing low with Fibonacci.
- Entry zone: **62%–72% retracement** of the high-to-low leg.
- A 70.5% level is specifically noted as the sweet spot within the zone.
- The IFVG at this retracement area is the highest-precision version of the OTE.

### Stop Hunt / Judas Swing

- Every AM session macro window (7:00, 8:00, 9:00) begins with an expected **30-minute manipulation leg** that runs against the anticipated direction.
- If RE highs have formed and you expect price to draw lower, the first 30 minutes after each hour should ideally see price **run higher** (Judas swing / stop hunt), then reverse.
- This manipulation is not mandatory within exactly 30 minutes but is the primary expectation. If it does not appear in the first 30 minutes, wait for more information before entering.
- The stop-hunt leg changes the "state of delivery" — the algorithm flips from accumulation/distribution and begins the directional leg.

### Power of Three (PO3)

- The AM session daily range follows this structure: open → manipulation (Judas swing in the wrong direction) → distribution (the real directional move).
- Visually: smooth price, then Jagged (manipulation), then directional expansion.
- "Smooth made Jagged" = manipulation / stop hunt has occurred. This is the visual cue to expect a directional reversal.

### London Session Range

- Defined as the highest high and lowest low formed between **2:00 AM and 5:00 AM Eastern time**.
- The AM session (post-7:00 AM) frequently retraces back into the London range as its first significant move.
- AM session characteristic: **retrade back into the London range** is the default expectation for the early AM move.
- When the morning session trades down to the London session low (or up to the London session high), that is the target reference ICT keeps on the chart from pre-7:00 AM price action.

### Market Structure Shift

- After a stop hunt sweeps RE highs/lows and price reverses, a **shift in market structure (SMS)** is confirmed.
- Post-SMS, all prior BISIs in the up-leg become IFVGs (bearish). The state of delivery has changed.
- Mark every SMS as it occurs — it resets the narrative filter for which FVGs are tradeable.

### Price Delivery Continuum

- All time frames (15m, 5m, 1m, 15s) show the same fractal algorithm repeating.
- The 15-second chart is useful for: (a) reducing stop-loss size via higher precision entry; (b) re-entering a move missed on 1m/5m/15m. It is not a shortcut — context from higher TFs is still required.
- Do not exceed 15m for intraday work. Daily/weekly/hourly charts are not needed.

### Fibonacci Range Measurement (Hourly Standard Deviation)

- At each macro window (7:00, 8:00, 9:00), anchor the Fibonacci tool from the **highest high to the lowest low** that has formed since that hour's open.
- ICT's Fibonacci levels for this exercise:
  - 2.0 = 1 standard deviation (primary target zone)
  - 2.5 = extreme / wick target (where the algorithm can temporarily spike)
- These levels are not used in isolation — they are corroborated by old lows, old highs, RE lows, or FVGs in the same zone.
- Three separate Fibonacci measurements (one per hour window) will frequently converge into the same price zone, creating a high-probability target.

### Sentiment as a Trade Filter

- When the general public / live-stream chatter is heavily bullish, ICT leans bearish — and vice versa.
- If a trade idea is only lukewarm and public sentiment aligns with the idea (rather than opposing it), ICT stays out. Opposing public sentiment is an additional confirming factor.

---

## Setups Taught

### Setup 1 — Inversion FVG at the Breaker (Primary Short Model for AM Session)

**Conditions required:**
1. Post-7:00 AM New York time.
2. RE highs form on 15m, 5m, or 1m.
3. Price runs above the RE highs (stop hunt / Judas swing).
4. Price shifts market structure lower (consecutive lower candles begin).
5. Inside the up-leg that created the stop hunt, identify the first BISI (up-close FVG).

**Entry:**
- Limit order at the BISI zone (CE or upper half of the gap) as price retraces into it.
- The OTE Fibonacci (62–72% of the stop-hunt high to the reversal low) should align with or be near this BISI.

**Stop placement:**
- If using the IFVG: stop above the highest wick that formed the stop-hunt candle (the manipulation high), or above the full FVG high — whichever is closer to entry while still being above the IFVG.
- If falling back to the bearish breaker: stop above the highest high of all consecutive down-close candles in the breaker sequence, plus 1–2 ticks.
- Rule: "Be a dick for a tick" — ICT explicitly warns against this. Do not demand perfection on fill precision at the cost of stress. Allow 1–2 ticks beyond your ideal level.

**Target:**
- The RE lows that formed after 7:00 AM (the opposing liquidity pool drawn toward).
- If no RE lows are present, extend to old FVGs, old swing lows, or the London session low.
- Fibonacci 2.0 (1 standard deviation) off the hourly range measurement as a zone check.
- Exit before or at the convergence of old lows + Fibonacci confluence. Do not demand the absolute low.

**Invalidation:**
- Price redelivers back into and above the IFVG on a body-close basis without resuming lower.
- Price returns to and trades above the stop-hunt high.

---

### Setup 2 — Bearish Breaker (Fallback When No IFVG Is Present)

**Conditions:**
- Same macro conditions as Setup 1.
- No BISI (IFVG) can be identified inside the stop-hunt up-leg.

**Entry:**
- Limit order at the last down-close candle of the breaker sequence (the most sensitive candle prior to the run-up).

**Stop:**
- Above the highest high of the full consecutive down-close sequence, plus 1–2 ticks.

**Target:**
- Same as Setup 1.

---

### Setup 3 — OTE / Retracement Entry (Continuation)

**Conditions:**
- Market structure has shifted (SMS confirmed post-stop-hunt).
- Price has begun delivering lower.
- A retracement occurs back up into the 62–72% Fibonacci zone of the SMS leg.

**Entry:**
- Inside the OTE zone (62–72% of high-to-low). Ideal: 70.5%.
- Look for a SIBI (down-close FVG) at or near this level as the precision entry point.

**Stop:**
- Above the swing high that created the retracement (the OTE high).

**Target:**
- RE lows on the chart or previous session low.

---

## Session & Time Rules

### 7:00 AM New York — AM Session Open

- **Punch-in time.** This is the beginning of the observation window.
- Do not reference or annotate any RE highs/lows from before 7:00 AM (beginner rule).
- Start scanning for RE highs and RE lows on 15m, 5m, 1m.
- The first 30 minutes (7:00–7:30 AM): expect a Judas swing — a manipulation move in the opposite direction of the anticipated draw. If RE highs are present and you expect lower, look for a push higher in this window.
- If no RE high/low is obvious at 7:00 AM, wait. Do not force annotations.

### 8:00 AM — Second Macro Window

- Restart the scan: look for RE highs/lows formed after 7:00 AM and up to 8:00 AM.
- Apply the same 30-minute Judas-swing expectation (8:00–8:30 AM).
- You can reference RE levels from post-7:00 AM when looking at the 8:00 window.
- Anchor a new Fibonacci measurement from the 8:00 AM window high to low.

### 9:00 AM — Third Macro Window / Pre-Market Range

- Third and final macro window of the AM session.
- Same Judas-swing expectation for the first 30 minutes.
- At 9:00, you can reference all RE levels from post-7:00 AM.
- For traders holding longer: reference the prior day's high or low as the macro draw.
- Anchor third Fibonacci measurement from the 9:00 AM window.

### 9:30 AM — Regular Session Open

- ICT's personal preference: be done trading by 10:15–10:30 AM if a trade has been captured and paid out. He does not chain himself to the charts all day.

### 11:00 AM — AM Session Close (Soft Boundary)

- ICT treats 11:00 AM as the practical end of the AM session. Noon is the technical end.
- After 11:00 AM, liquidity and reliability of the patterns decrease for the models taught here.

### 2:00 AM–5:00 AM Eastern — London Session

- Defines the London session high and low (the "London range").
- The AM session first move typically retraces into this range.
- Only advanced traders with London session model knowledge should observe this for entries.
- Beginners: only look at the London range to know where the London session high and low are as potential targets/draw levels.

---

## What To Avoid

1. **Do not annotate or trade RE highs/lows before 7:00 AM** (for beginners). They belong to the London scope, not the AM session model being taught.

2. **Do not anticipate a setup before it has formed.** Never lead price with an expected annotation. Wait for RE highs/lows to actually exist in price before drawing them. "You never never never lead your expectations with something that has not actually formed in the chart."

3. **Do not use a BISI as a buy setup when the narrative is bearish.** A BISI inside a bearish run is an IFVG — it is a short entry, not a long. Confusing narrative direction on FVGs is cited as a primary way beginners get trapped.

4. **Do not include wicks when defining a FVG if a volume imbalance is present.** Wick penetration inside the FVG below the CE level is irrelevant. Only body-to-body defines the true gap.

5. **Do not trade a FVG that has been retouched multiple times in the same session.** Once a FVG has been overlapped and used two or more times, probability drops dramatically. "It's been overlapped and worked multiple times and it's done enough — your day would be complete here."

6. **Do not enter trades during the first month of study** (for beginners / the protocol ICT assigns to his son). Only observe and journal. No demo trading, no button-pushing.

7. **Do not look above the 15-minute time frame for intraday trading.** No daily, weekly, hourly, or 30-minute charts. "You don't need anything above a 15-minute time frame because it's intraday trading."

8. **Do not trade obvious setups when the broader public sentiment aligns with your idea.** If it's not a clearly contrarian position, reduce size or step aside.

9. **Do not use a 15-second chart as a shortcut to skip context.** The 15s is for reducing stop size and re-entering missed moves only. Without 1m/5m/15m context, the 15s produces chop.

10. **Do not demand perfect fills on limit orders.** The algorithm will sometimes miss a fill by the spread. Accept this. "Don't be a dick for a tick."

11. **Do not rush to trade with real money.** The process must come before live execution. Quitting a job before having two consecutive years of salary saved from trading is explicitly prohibited.

12. **Do not use support and resistance as a framework.** ICT does not trade S/R. "We look for liquidity and inefficiencies." S/R is how less-informed retail money trades — it is the source of the stop runs, not the decision-making framework.

---

## Algorithmic Notes

### Daily Chart Setup Protocol (Pseudocode)

```
EVERY TRADING DAY:

1. LOAD_CHARTS()
   - Upper left:  15-minute
   - Lower left:  5-minute
   - Upper right: 1-minute
   - Lower right: 15-second (optional; for re-entries only)

2. MARK_SESSION_TIMES()
   Draw vertical lines at:
   - 7:00 AM  (AM session open — start of observation)
   - 8:00 AM  (second macro window)
   - 9:00 AM  (third macro window / regular open)
   Note: London range = highest high / lowest low from 2:00 AM to 5:00 AM Eastern

3. FOR each_timeframe IN [15m, 5m, 1m]:
   SCAN_POST_7AM_PRICE for RE_HIGHS and RE_LOWS
   IF two swing highs exist AND right_high slightly_lower than left_high:
       ANNOTATE as RE_HIGH (horizontal line across both highs)
   IF two swing lows exist AND right_low slightly_higher than left_low:
       ANNOTATE as RE_LOW (horizontal line across both lows)

4. ANNOTATE_FVGs()
   FOR each candle in post_7AM_price:
       IF down_close_candle AND prior_candle_low > subsequent_candle_high:
           MARK SIBI (bearish FVG)
           Levels: [prior_candle_low, CE = midpoint, subsequent_candle_high]
           EXTEND to the right
       IF up_close_candle AND prior_candle_high < subsequent_candle_low:
           MARK BISI (bullish FVG)
           Levels: [prior_candle_high, CE = midpoint, subsequent_candle_low]
           EXTEND to the right
       IF volume_imbalance_present_inside_FVG:
           IGNORE any wick that does not reach CE
           TRUE_FVG_BOUNDARY = body_level, not wick

5. DETERMINE_NARRATIVE()
   IF RE_HIGHS taken out by stop_hunt AND price breaks lower:
       NARRATIVE = BEARISH
       FOCUS_FVGs = SIBIs only (down-close FVGs)
       MARK_IFVGs = all BISIs inside the stop-hunt up-leg
       STATE_OF_DELIVERY = seeking sell-side liquidity (RE lows, old lows)

   IF RE_LOWS taken out by stop_hunt AND price breaks higher:
       NARRATIVE = BULLISH
       FOCUS_FVGs = BISIs only (up-close FVGs)
       MARK_IFVGs = all SIBIs inside the stop-hunt down-leg
       STATE_OF_DELIVERY = seeking buy-side liquidity (RE highs, old highs)

6. FOR each_macro_window IN [7:00, 8:00, 9:00]:
   FIBONACCI_MEASUREMENT()
       anchor_high = highest high since window open
       anchor_low  = lowest low since window open
       PLOT Fib(anchor_high, anchor_low)
       MARK levels: 2.0 (1 std dev), 2.5 (extreme)
   EXPECT_JUDAS_SWING() in first 30 minutes:
       IF NARRATIVE == BEARISH:
           expect price to push HIGHER in first 30 min (stop hunt)
           THEN look for rejection and breakdown
       IF NARRATIVE == BULLISH:
           expect price to push LOWER in first 30 min (stop hunt)
           THEN look for rejection and mark up

7. JOURNAL_ANNOTATIONS()
   At significant price reactions, ADD TEXT note on chart:
   - State what happened (e.g., "IFVG respected at CE — price folded lower")
   - Keep ALL notes positive or observational — no self-criticism
   - Highlight only what worked and what was visible
```

### FVG Identification Rule (Precise)

```
# SIBI (down-close, bearish)
candle[N] is down-close
candle[N-1].low > candle[N+1].high
GAP_LOW   = candle[N+1].high
GAP_HIGH  = candle[N-1].low
CE        = (GAP_LOW + GAP_HIGH) / 2

# BISI (up-close, bullish)
candle[N] is up-close
candle[N-1].high < candle[N+1].low
GAP_LOW   = candle[N-1].high
GAP_HIGH  = candle[N+1].low
CE        = (GAP_LOW + GAP_HIGH) / 2

# Volume Imbalance filter
IF candle[N].body_low > candle[N-1].body_high OR
   candle[N].body_high < candle[N-1].body_low:
       volume_imbalance = TRUE
       ignore_wicks_below_CE = TRUE
```

### Inversion FVG Detection

```
# After a stop hunt confirms narrative change:
FOR each BISI in the up-leg that preceded the stop_hunt:
    RECLASSIFY as IFVG
    EXPECTED_BEHAVIOR = resistance on retest
    ENTRY_TRIGGER = price retraces into IFVG zone
    IDEAL_ENTRY  = CE of the IFVG
    STOP         = above the stop-hunt high
    TARGET       = RE lows / prior session low / Fib 2.0 convergence

# First BISI prior to stop hunt = highest probability IFVG
```

### RE High/Low Identification

```
# Relative Equal Highs
swing_high[A] and swing_high[B] at approximately same price
CONDITION: swing_high[B] < swing_high[A] by small margin (not identical, slightly lower)
CONDITION: at least one lower candle between A and B
CONDITION: both formed after 7:00 AM New York time
→ Liquidity resting as buy stops just above swing_high[A]

# Relative Equal Lows
swing_low[A] and swing_low[B] at approximately same price
CONDITION: swing_low[B] > swing_low[A] by small margin (slightly higher)
→ Liquidity resting as sell stops just below swing_low[A]
```

### Three-Window Fibonacci Convergence Target Logic

```
FOR hour IN [7, 8, 9]:
    H = max(price[hour:hour+30])
    L = min(price[hour:hour+30])
    target_1sd[hour] = L - (H - L) * 1.0   # bearish: 2.0 extension below
    target_ext[hour] = L - (H - L) * 1.5   # 2.5 extension

IF abs(target_1sd[7] - target_1sd[8]) < threshold AND
   abs(target_1sd[8] - target_1sd[9]) < threshold:
       HIGH_PROBABILITY_TARGET = mean(target_1sd[7], target_1sd[8], target_1sd[9])
```

---

## Notable Quotes

- "At 7 o'clock in the morning, that begins your hunt for relative equal highs or relative equal lows."

- "You never never never lead your expectations with something that has not actually formed in the chart. Don't predict the setup, you have to wait for the setup."

- "A Down close fair value Gap is a SIBI — it stands for Sell Side Imbalance, Buy Side Inefficiency."

- "The volume imbalance tells you to ignore any of the wick. This wick will not be all that influential."

- "Every single PD array has an inversion aspect to them. Every single one of them can reverse their role."

- "The first fair value Gap prior to a stop run — always always always have that one noted."

- "The market is algorithmic. It's absolutely 100% manipulated and controlled and scripted until they manually intervene."

- "Smooth made Jagged — that's indicating it's probably going to go in the opposite direction."

- "Don't be a dick for a tick."

- "We look for liquidity and inefficiencies. I'm not a support and resistance Trader."

- "It's either going to go up or it's going to go down. Why would it go up? It's going to go towards relative equal highs. Why would it go down? Relative equal lows."

- "If it's not obvious, why are you risking money? Sit on your hands, turn the charts off."

- "The market breaks down, the queue working off of that inversion fair value gap — that drop creates this gap right there. That right there is the Sweet Spot. When you're bearish and you have everything behind you that's in play, it's your Optimal Trade Entry."

- "Your eye jumps to all the Sell Side Imbalance Buy Side Inefficiencies — the down-close big range candles. All by themselves. That's what your eye jumps to."

- "The AM session characteristic is always, first and foremost: retrade back into the London range."

- "Each hour — at 7 o'clock, 8 o'clock, and at 9 o'clock — you're starting the whole process all over again."

---

*Last updated: 2026-06-18*
