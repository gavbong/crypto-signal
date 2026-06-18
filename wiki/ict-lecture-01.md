# ICT 2024 Mentorship — Lecture #1
**Date:** August 5, 2024
**Source:** https://www.youtube.com/watch?v=GKeLVR3dPuI

---

## Overview

Lecture #1 is the foundational session of the 2024 mentorship, focused entirely on establishing the correct mental framework and a minimal rule-based starting model before attempting to trade. ICT introduces the core time-based logic of the algorithm — that price is coded to seek liquidity (relative equal highs/lows) and fill inefficiencies (Fair Value Gaps) at specific, repeating windows of the day. The session ends with a live forward-test on NQ demonstrating bias determination, a bullish breaker entry, and delivery to a pre-marked relative-equal-high target — all using only a 15-minute, 5-minute, and 1-minute chart.

---

## Key Concepts

### Price Is Algorithm-Driven, Not Auction-Driven

- ICT's core premise: price does **not** move from buying and selling pressure; it is **coded to deliver** to specific levels at specific times.
- The algorithm references **time first** — a level only matters when price is within a time window predisposed to seek it.
- "Unless it stems on the basis of time first it has to be the right time if it's not the right time of day it is absolutely not going to work. Period."
- DOM (Depth of Market) shows equal orders above and below, yet price still marches to pre-coded levels — ICT cites this as proof the move is not order-flow driven.

### The Only Two Things Price Seeks

Price is always doing one of two things:
1. **Running to old highs or old lows** (liquidity pools — buy/sell stops resting there).
2. **Filling inefficiencies** — Fair Value Gaps (FVGs), Volume Imbalances.

"Where's the draw on liquidity? Where are the old highs, old lows, and inefficiencies? That's all you're focused on."

Nothing else is needed as a foundation. No daily chart, no hourly chart, no indicators.

### Relative Equal Highs and Relative Equal Lows

- Two swing highs (or lows) that are visually close in price — smooth, flat areas on the chart.
- **High-probability trigger rule**: A relative equal high is very likely to be swept when the **left swing high is slightly higher than the right**. The market "primes" by failing to take the prior high, trapping shorts with stops just above, then sweeping those stops.
- Conversely, a relative equal low is high-probability when the **left swing low is slightly lower than the right** (the classic "failure swing" in retail terms). ICT reframes this: it is not a technical pattern to trade — it is the algorithm's way of identifying where stops cluster.
- The side that is **smooth** (no jagged prior wicks) is the side the algorithm will attack next.
- The side that is **jagged** (prior candle wicks tearing through) is where the attack has already happened — do not expect another run into jagged price.

> "Where it's smooth, it's going. Where it's jagged, it's going to move away from."

### Relative Equal High Identification Filter

- Look at two swing highs side by side.
- If the **right one is lower** than the left → high probability of a sweep upward.
- The lower right high triggers the "priming" effect: shorts placed there feel safe because it "held as resistance," making their stop just above it a concentrated liquidity pool.

### Relative Equal Low Identification Filter

- If the **right swing low is higher** than the left → high probability of a sweep downward.
- This is the bearish equivalent; longs placed there feel safe because price "held as support."

### Fair Value Gap (FVG) / SIBI / BISI

- **BISI** (Buy-Side Imbalance / Sell-Side Inefficiency): a gap with an **up-close** candle — bullish FVG.
- **SIBI** (Sell-Side Imbalance / Buy-Side Inefficiency): a gap with a **down-close** candle — bearish FVG.
- FVGs are delivery targets — price will fill them as it moves toward liquidity.
- **Consequent Encroachment (CE)**: the 50% midpoint of any FVG. Price gravitates to this level. A wick to CE that repels (with the body outside) is a continuation signal.
- FVG becomes an **inversion** (IFVG) once price blows through it in the opposite direction.

### Volume Imbalance

- A smaller version of FVG: the prior candle's high overlaps with the next candle's open/low, leaving a single-candle untraded gap.
- Bodies should respect the boundary of a volume imbalance in the direction of the trend; wicks may enter.
- If price leaves a volume imbalance **unfilled** as it moves away, it signals a continuation of 15–20+ handles (breakaway gap behavior).

### Order Block (Bullish Breaker)

- The last **down-close candle** before an impulsive rally.
- The full range of consecutive up-close candles leading into the drop that created the displacement is technically the **Breaker Block**; the most sensitive sub-range is the **last up-close candle** in that run.
- Price respecting the body of the breaker (not the wick) confirms the narrative.
- A bullish breaker after a displacement move above a short-term high is a valid buy setup.
- "That is not Supply and Demand. That is not what Sam Seiden would ever refer to... we're looking at what an algorithm is doing, not some floor trader's perception."

### Displacement

- A **displacement** is an aggressive move counter to the prior trend direction — it confirms intent.
- Bullish displacement: impulsive move up against a prior downtrend, taking out a short-term high.
- Bearish displacement: impulsive move down against a prior uptrend, taking out a short-term low.
- Displacement is required to validate an order block. Without it, a down-close candle is not an actionable order block.

### Draw on Liquidity

- The initial directional target — the level the algorithm is reaching for during a session.
- It is **not** the absolute terminus of the move. The market can retrace before reaching it.
- Identified as the nearest relative equal highs or lows visible on the 15-minute chart, or a significant FVG above/below current price.
- Does not need to be hit in the current session, but each successive pre-market window that passes without hitting it **increases** the probability of the hit in the next window.

### Breaker vs Inversion FVG

- Use a **higher time frame directional bias** to distinguish whether a level acts as support (bullish breaker) or resistance (inversion FVG).
- Bullish scenario: down-close candle below an FVG that price has already traded through → treat as bullish breaker; the inversion FVG above becomes support on retest.
- "You have to have a higher time frame premise and the directional draw where the market's going to go" to resolve ambiguity.

### Why Smooth Areas Get Attacked

- Smooth price levels = stops clustered just beyond them (trapped positions expecting the level to hold).
- Jagged areas = stops have already been triggered; no new fuel exists.
- "Still Waters invite rocks... you can't accept that. Our sinful nature says we have to disrupt that."
- Algorithmically: the engine is programmed to seek the highest concentration of resting orders. Clean, smooth levels are exactly that.

---

## Setups Taught

### Live Setup 1: Post-8:30 Bullish Order Block to Relative Equal Highs

**Context**: NQ, August 5, 2024 morning session. Prior trend was down. An 8:36 short-term high was printed post-8:30.

**Entry Criteria**:
1. Price trades below relative equal lows post-8:30, clearing sell-side liquidity.
2. Displacement: price rallies impulsively above the 8:36 short-term high.
3. Down-close candle just before the impulsive rally = **bullish order block**.
4. Price retraces into the order block's range (body, not necessarily wick).
5. Time confirmation: setup occurred post-8:30 (algorithm spools for liquidity/inefficiencies at 8:30).

**Stop Placement**: Below the order block's low (below the down-close candle's low).

**Target**: Relative equal highs identified pre-session on the 15-minute chart (17,820.75 cited in the session).

**FVG refinement**: An FVG (SIBI/BISI) inside or adjacent to the order block is the highest-priority entry point. CE of that FVG is the ideal fill level.

**Volume imbalance filter**: If a volume imbalance near the OB remains unfilled (bodies not returning to it), that is a breakaway signal — expect a stronger continuation.

### Setup Framework: Relative Equal Highs/Lows Sweep

**Entry Criteria**:
1. Identify relative equal high (right swing is lower than left) or relative equal low (right swing is higher than left) during the 7:00–7:30, 8:00–8:30, or 9:00–9:30 window.
2. Wait for price to trade **through** the smooth level (sweep the stops).
3. Post-sweep: look for a reaction — order block + displacement, or FVG retest — in the direction of the sweep continuation.

**Stop Placement**: Beyond the extreme of the sweep candle.

**Target**: The opposing smooth level (relative equal high if going long from relative equal lows; relative equal lows if going short from relative equal highs).

**If both equal highs and equal lows exist**: Wait for one side to be taken first; that disruption confirms the bias direction toward the other side.

---

## Session & Time Rules

All times are **New York local time (Eastern)**. The algorithm runs on NY time regardless of trader location.

### Pre-Market Windows (3 opportunities per morning)

| Window | Label | Purpose |
|---|---|---|
| 7:00–7:30 AM | Pre-market Range 1 | Primary: identify rel. equal highs/lows that formed **after 7:00 AM** |
| 7:30–8:00 AM | Opening Range 1 | Price sets up within the range formed in the prior window |
| 8:00–8:30 AM | Pre-market Range 2 | Secondary opportunity; same drill as 7:00–7:30 |
| 8:30 AM | News driver / algorithm spool | Algorithm starts reaching for liquidity or FVGs at or after 8:30 |
| 9:00–9:30 AM | Pre-market Range 3 | Third opportunity pre-open bell |
| 9:30–10:00 AM | Opening Range 2 | Post-bell 30-minute window |

**Key rule**: The **30-minute window** is the algorithmic unit. There is no 15-minute opening range. "It's a 30-minute opening range. That's algorithmic."

### What to Do at Each Window

**7:00 AM**: Sit down. Pull up 15-minute, 5-minute, and 1-minute charts. Mark all **relative equal highs and lows visible from prior price action** (not from before 7:00 AM ideally — London levels may still be in play).

**7:00–7:30**: Watch where price is smooth vs jagged. Identify which side the algorithm is likely to seek. This is the first opportunity window.

**8:00**: Rescan. If the 7:00–7:30 target has not been hit, the probability of it being hit in a subsequent window is **higher**, not lower. Re-mark levels on 15M, 5M, 1M.

**8:00–8:30**: Second opportunity. Sharpen bias using any FVGs or order blocks that formed since 7:00.

**8:30**: News drivers fire here. Do not enter during the initial spike on major news (ISM PMI, NFP, CPI, FOMC). These can be "manual intervention" — untradeable. Wait for the structure to form after the spike.

**9:00–9:30**: Third and final pre-market window. If the same target from 7:00 is still unmet, probability of a hit is now very high.

**9:30**: Opening bell. A fake move against the bias (Judas Swing) frequently forms here before the real move. Do not chase the 9:30 move; wait for the retracement into OB/FVG.

**Until 10:00**: Study price. One trade per day maximum if new. No afternoon trading required.

### What to Study: 4-Hour Morning Block

- Screenshot the 15M, 5M, and 1M charts from 7:00 AM to 11:00 AM.
- Annotate: which levels were relative equal highs/lows, which FVGs formed, which OBs formed.
- Record candle count from the OB to the target hit.
- Record handles moved from key level to target.
- Record your emotional state at each key candle (anxious, confident, second-guessing).

---

## What To Avoid

### Trading Mechanics

- **Never trade more than one micro contract per day when learning.** "It is physically impossible for you to go out there on day one and blow the account" with one micro and one trade per day.
- **Never pyramid trades until one year of consistent one-contract trading.** "Pyramiding should not be part of your repertoire yet."
- **Do not use more than one contract just because a funded account allows it.** "If you're trading more than one contract of a micro with $3,000 cushion and you're not consistent, you're absolutely gambling."
- **Do not trade news spikes.** "As soon as it starts going and it doesn't stop, that's manual intervention. Think like FOMC, CPI, Non-Farm Payroll — you're literally chasing the wind."
- **Do not trade the 9:30 opening move directly.** The opening often produces a Judas Swing — a fake move against the bias. Wait for the retest.
- **Do not look for relative equal highs that formed before 7:00 AM.** London session may still be in play and override them.
- **Do not use sub-1-minute charts or above 15-minute charts for this model.** "You don't need a daily chart, you don't need an hourly chart... you don't need anything below a one minute chart."

### Study Methodology

- **Never use Market Replay.** "I absolutely loathe it. I hate it. It's a crutch that allows frauds to sound smart." Forward-test only.
- **Do not try to trade everything ICT has taught.** Pick one setup from this lecture and master it before adding complexity.
- **Do not set a time limit for learning.** "Anyone that says I'm going to teach you how to do ICT in this number of days... they are full of grade-A manure."
- **Do not treat a demo win as skill.** "You got lucky doing something that had no bearing on what you should be doing consistently going forward."

### Psychology / Mindset

- **Do not put a time pressure on becoming profitable.** "You can't force being profitable. You absolutely cannot do it."
- **Do not copy other traders' setups live.** Study the model, apply your own eye, do not co-depend.
- **Do not exit a trade at 10 handles when calling a 50-handle target** because of pressure. "Your image is more important to them than following a model that they have seen works."
- **Do not blame external factors for losses from over-leverage.** "If you happen to be overleveraged when [an unexpected event] happens... it is going to be a hard swallow and probably end you entirely."
- **Do not watch other traders' live streams while learning.** They will distract you or give you a false reason to blame when a trade fails.

---

## Algorithmic Notes

### Core Detection Logic

```
BIAS DETERMINATION (run at 7:00, 8:00, 9:00 AM NY time):
  1. Pull 15M, 5M, 1M charts
  2. Scan for RELATIVE_EQUAL_HIGHS and RELATIVE_EQUAL_LOWS
  3. For each pair of swing highs H_left, H_right (left is older):
       if H_left > H_right → RELATIVE_EQUAL_HIGH (high probability sweep target)
  4. For each pair of swing lows L_left, L_right:
       if L_left < L_right → RELATIVE_EQUAL_LOW (high probability sweep target)
  5. Classify each as SMOOTH (no prior wick penetration) or JAGGED (prior wicks present)
  6. BIAS = direction toward the SMOOTH level

IF both REH above AND REL below exist:
  WAIT → first sweep determines bias
  After first sweep: bias flips toward the opposite level
```

### FVG / BISI / SIBI Detection

```
For three consecutive candles [C_prev, C_mid, C_curr]:
  gap_top    = min(C_prev.high, C_curr.high)   -- actually max of the surrounding lows
  gap_bottom = max(C_prev.low, C_curr.low)     -- actually min of the surrounding highs

  BISI (bullish FVG):
    C_mid is up-close (C_mid.close > C_mid.open)
    AND C_curr.low > C_prev.high  (gap exists between prev high and curr low)

  SIBI (bearish FVG):
    C_mid is down-close (C_mid.close < C_mid.open)
    AND C_curr.high < C_prev.low  (gap exists between prev low and curr high)

  CE = midpoint of gap range
```

### Order Block Detection

```
BULLISH ORDER BLOCK:
  1. Find the last down-close candle (C_ob) before an impulsive bullish displacement
  2. Displacement = impulsive rally that trades ABOVE the most recent short-term high
  3. OB range = [C_ob.low, C_ob.high]
  4. Most sensitive sub-range = last up-close candle in the run of consecutive up-closes
     preceding the down-close sequence → range [last_up_close.low, last_up_close.high]
  5. Entry zone = price returning into OB range from above
  6. Time filter: OB must have formed post-8:30 AM (or post-7:00, post-9:00 depending on window)
```

### Relative Equal High/Low Probability Filter

```
REH_high_probability(H_left, H_right):
  return H_left > H_right  -- left is higher → right is "lower high" → stops trapped above both

REL_high_probability(L_left, L_right):
  return L_left < L_right  -- left is lower → right is "higher low" (failure swing) → stops trapped below both

SMOOTH_vs_JAGGED(swing_level, lookback_candles):
  prior_wicks = [c for c in lookback_candles if c.high > swing_level or c.low < swing_level]
  if len(prior_wicks) == 0: return SMOOTH
  else: return JAGGED
```

### Time Window Sequencing

```
MORNING_WINDOWS = [
  (07:00, 07:30),  # Window 1: pre-market range
  (08:00, 08:30),  # Window 2: pre-news range
  (09:00, 09:30),  # Window 3: pre-open range
]

for window_start, window_end in MORNING_WINDOWS:
  if current_time in [window_start, window_end]:
    scan_relative_equal_highs_lows()
    mark_smooth_levels()
    mark_fvgs()
    determine_bias()
    if target_not_hit_in_prior_window:
      increase_confidence(target)  # probability rises each missed window
```

### Probability Escalation Rule

```
# Each pre-market window that passes without hitting the smooth target
# INCREASES (not decreases) the probability of a hit in the next window.
# Reason: algorithm is building confluence at that level via repeated approaches.

missed_windows_count += 1
target_probability = base_probability * (1 + 0.1 * missed_windows_count)
# (Conceptual — exact scaling not specified; rule is directional only)
```

### Judas Swing at 9:30

```
JUDAS_SWING:
  At 9:30 NY open, price frequently makes an initial move AGAINST the pre-session bias
  Purpose: trap breakout traders on the wrong side
  Action: DO NOT trade the 9:30 initial move
  Wait: for price to reverse and return to OB/FVG within the 9:30–10:00 opening range
  Then: enter in bias direction
```

### One-Trade-Per-Day Rule (for developing traders)

```
TRADE_BUDGET = 1  # per session
CONTRACT_SIZE = 1 micro  # regardless of account cushion
MAX_LEVERAGE = 1 micro per $3,000 cushion

Entry only when:
  - Time window is active (7:00-7:30, 8:00-8:30, or 9:00-9:30)
  - Bias confirmed from relative equal high/low analysis
  - Price has returned to OB or FVG (not chasing displacement)
  - No active news spike (manual intervention filter)
```

---

## Notable Quotes

> "Price will do what it's going to do because it's coded to do it based on time. Time is the first hallmark to when and why a market should produce a displacement."

> "Between 8:00 and 8:30 in the morning New York local time... this is always, absolutely without fail, it's never not going to do it. It's always every single day going to do this very thing."

> "The only two things you're worried about [are] old highs, old lows, and inefficiencies. That's it."

> "Where it's smooth, it's going. Where it's jagged, it's going to move away from."

> "Still Waters invite rocks... the market will go to an area of smoothness for the purpose of disrupting any orders that would be resting above or below it."

> "As soon as you enter these markets you've entered the jungle. Are you liquidity right now? Because if you're liquidity, you're lunch."

> "A draw on liquidity is just an initial reasonable assumption on our part to determine a directional move that could unfold. It does not define the absolute terminus."

> "If you're trading more than one contract of a micro with $3,000 cushion and you're not consistent... you're absolutely gambling."

> "You can't force being profitable. You absolutely cannot do it."

> "Unless it stems on the basis of time first — it has to be the right time — if it's not the right time of day it is absolutely not going to work. Period. End of story."

> "Complication comes when people want to try to dilute it to make it look like it isn't my concepts. That's what makes it complicated."

> "I absolutely loathe Market Replay. I hate it. I can't stand it. It's a crutch that allows frauds to sound smart."

> "This is going to be the end of lecture number one dealing with the foundations of determining a bias. It's very time-specific. Without the time elements none of it matters."
