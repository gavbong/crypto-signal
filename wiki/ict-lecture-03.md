# ICT 2024 Mentorship — Lecture #3
**Date:** August 7, 2024
**Source:** https://www.youtube.com/watch?v=ZkLc4-adodg

---

## Overview

This lecture introduces New Day Opening Gaps (NDOG) and New Week Opening Gaps (NWOG) as the primary algorithmic draw targets that underpin directional bias — establishing the concept ICT calls "engineering liquidity." ICT demonstrates live on Nasdaq how to combine the economic calendar (absence of morning data + 1:00 PM bond auction) with NDOG clusters, relative equal highs/lows, and order block / FVG entries to build and execute a bearish afternoon trade. The session closes with a framework for graduating from intraday scalping to larger price-run holding, emphasizing demo journaling and tape reading as the prerequisite skills.

---

## Key Concepts

### New Day Opening Gap (NDOG)

- **Definition:** The price gap between the 5:00 PM Eastern close and the 6:00 PM Eastern open of the index market (CME 1-hour break), every day except Friday.
- **How to mark:**
  - On a 1-minute chart, locate the 4:59 PM closing candle and the 6:00 PM opening candle.
  - Draw two horizontal rays: one at the 5:00 PM close price, one at the 6:00 PM open price.
  - Label with date (annotate using whatever date format you prefer, but always include the date).
  - The gap "belongs" to the following trading day — e.g., a gap formed Tuesday evening is a Wednesday reference.
- **Quadrant levels (Fibonacci):**
  - Drag Fibonacci from the low of the two prices to the high of the two prices.
  - **0.50** = Consequent Encroachment (CE) — the midpoint of the gap; primary interaction level.
  - **0.25** and **0.75** = upper/lower quadrant levels; price gravitates around these.
  - These levels act as precise algorithmic stops and reversal triggers (demonstrated to the tick in lecture).
- **Life cycle:** 5 **trading** days (not calendar days); skip holidays and add a day. After 5 days, levels can still be used if price is within ~150 handles and fits the narrative, but the high-confidence window is the first 5 days.
- **Post-fill behavior:** A NDOG is NOT discarded once "filled." The algorithm continues to reference it. Most traders discard gaps once touched — that is incorrect.
- **Clustering rule:** Maintain the last 5 NDOGs on a separate reference chart layout. Count how many fall above vs. below current price — the side with more gaps is the gravitational draw direction.
- **Gap direction:** Works the same whether the gap opens higher or lower. Always mark the three levels: high, CE (midpoint), low.

### New Week Opening Gap (NWOG)

- **Definition:** The gap between Friday's 5:00 PM Eastern close and Sunday's 6:00 PM Eastern open.
- Constructed and marked identically to NDOG (three levels: high, CE, low; 0.25/0.75 quadrants).
- **Life cycle:** 5 **weeks** (not 5 days). Maintain the last 5 NWOGs on the reference layout.
- **Relative importance:** NWOGs outweigh NDOGs for swing trade bias because they capture a full weekend of repricing. If there is a cluster of NWOGs below price, that is a stronger gravitational draw than a cluster of NDOGs alone.
- Annotate with "NW" prefix to distinguish from NDOGs.

### Engineering Liquidity

- The algorithm engineers liquidity by creating relative equal highs (buy-side liquidity resting above) and relative equal lows (sell-side liquidity resting below) as a staging mechanism before drawing to a NDOG/NWOG target.
- Relative equal highs above current price with NDOG clusters below = the equal highs are a **Judas swing** (fake breakout upward to trap buyers) before the real move down to the gap.
- The clustering of NDOGs/NWOGs allows a trader to anticipate the direction of the Judas swing before it forms — the "engineering of liquidity" is predictable.
- You can predict where relative equal highs/lows will form by knowing where the algorithm needs to create fuel for the real directional move.

### Priority Hierarchy of Draws on Price

In descending order of algorithmic significance:
1. **New Week Opening Gap** (NWOG) — highest weight
2. **New Day Opening Gap** (NDOG)
3. **Relative equal highs / relative equal lows** — buy-side and sell-side liquidity
4. **Inefficiencies / FVGs (FVG, OB, Breaker)** — subordinate to liquidity pools above

> "Inefficiencies are subordinate and less important than relative equal highs, relative equal lows, or New Day / New Week opening gaps because their influence over price — the algorithm will prefer more importance and significance placed around them."

### Consequent Encroachment (CE) vs. Equilibrium

- **CE** = midpoint of a gap or inefficiency. It is NOT the same as equilibrium.
- **Equilibrium** applies to a traded range (price has gone up and down through it).
- A gap has not been traded in both directions — only one side of delivery exists. Therefore the midpoint is CE, not equilibrium.
- For a **bearish FVG (sell-side imbalance, buy-side inefficiency / SIBI):** best shorts form in the lower half; leave the upper half unfilled — signals algorithmic weakness.
- For a **bullish FVG (buy-side imbalance, sell-side inefficiency / BISI):** best longs fill in the upper half; leave the lower half open — a breakaway gap signals large range expansion incoming.

### Bearish Order Block (BOB) Entry Conditions

- A candle that fails to reach the CE of a FVG above it is an algorithmic weakness signature.
- If price trades up into a candle's range but cannot touch the CE of the overlying FVG: that candle becomes a bearish order block to trade from on the next touch of its bottom.
- Condition to trust the order block: after the BOB forms, the next candle must also fail to breach the BOB's high.
- Entry: go short when price returns to the bottom of the BOB candle and begins to move away.

### Bond Auction as PM Session Catalyst

- When there is **no morning medium/high-impact news driver**, the morning session is suspect — likely choppy, false breakouts, difficult to trade.
- A **1:00 PM bond auction** (medium-impact) becomes the sole catalyst for the day. It is tradeable but not as volatile as high-impact data.
- The market will typically engineer liquidity (fake moves, relative equal high/low formation) in the morning to set up a directional run into and after the 1:00 PM bond auction.
- Condition: bond auction setup only applies cleanly when there is no morning data. If morning data exists alongside a bond auction, the afternoon setup is less reliable.

### Six-and-Four Pyramid Model

- ICT's standard position scaling: 6 contracts at first entry, 4 contracts added at a secondary entry.
- The secondary (4-contract) add is placed lower (for shorts) after confirmation that the initial leg is valid.
- This means the secondary entry can trade briefly above the first entry without triggering a net loss — the blended average protects the position during retraces into the FVG range.

### Holding Trades Longer — Prerequisite Framework

- You cannot hold for a 50+ handle (or 100+ handle) run until you can consistently capture 5 handles (S&P) or 10 handles (Nasdaq) on intraday setups.
- Definitions:
  - **Intraday / scalp:** < 50 handles on Nasdaq
  - **Intermediate swing (intraday):** 50 handles or more
  - **Larger price run:** 100 handles or more
- To hold longer, you need a draw target that justifies the range (e.g., a NDOG or cluster of NDOGs 100+ handles away) — not just a local FVG.
- When in a winning trade that approaches a prior partial-profit zone, take a partial and journal the remainder — do not exit the full position based on emotion. The journal entry should capture your emotional state at each point for desensitization over time.

---

## Setups Taught

### Afternoon Short Setup (Bond Auction Day — No Morning Data)

**Narrative conditions (must all be true):**
1. No medium or high-impact morning news drivers on economic calendar (ForexFactory or EconoDay).
2. A bond auction scheduled at 1:00 PM Eastern.
3. Cluster of NDOGs and/or NWOGs **below** current price.
4. Relative equal lows identified; the right-side low is **higher** than the prior swing low (higher low filter).

**Entry criteria:**
1. Identify the bearish FVG formed as price rolled over approaching 1:00 PM.
2. Price trades up into the FVG but **fails to reach CE (midpoint)**. This is the strength/weakness confirmation.
3. The next candle after the FVG touch also fails to breach the FVG high.
4. Enter short (6 contracts) as price returns to and touches the **bottom of the bearish order block** and begins to move away.
5. Pyramid (4 contracts) on the next displacement candle lower.

**Stop placement:**
- Initial stop: above the CE of the FVG that price failed to reach. If price would have touched the CE, the stop moves above the CE of the higher overlying FVG.
- After position moves favorably and the next retrace also fails CE, move stop to first entry minus 2 ticks.

**Target rules:**
- Primary partial: just below the nearest relative equal low.
- Secondary target: London session low (or prior session low) — sell-side liquidity.
- Ultimate draw: NDOG or cluster of NDOGs below.
- For a 100+ handle run: the entire multi-day NDOG zone is the objective; enter a limit order at the NDOG level and let price deliver.

**Timing window:**
- Setup initiates 12:42–1:00 PM (approaching bond auction).
- Post-1:00 PM: market pumps briefly (trapping buyers), then accelerates lower — this is the confirmation leg.
- If no clean setup by 2:00 PM, use the **2:00–3:00 PM Silver Bullet** window.
- 3:00 PM to close is a tertiary opportunity window.

---

## Session & Time Rules

| Time (Eastern) | Rule |
|---|---|
| 12:00 AM midnight | True start of algorithmic day. Midnight is the reference point for intraday liquidity and inefficiency labeling. |
| 5:00 PM | Index market pauses (not Friday). 4:59 candle close = first NDOG level. |
| 6:00 PM | Index market reopens. First 1-minute print = second NDOG level. Mark immediately. |
| 6:00 PM Sunday | NWOG forms. Mark with same 3-level methodology. |
| 7:00 AM | Morning session watch begins. Look for relative equal highs/lows forming. Observe only for first 30 min. |
| 7:00–9:00 AM | At each top-of-hour mark, anticipate the opposing direction move in the next 30 minutes. |
| 7:00, 8:00, 9:00 AM | Three interval delineations; each carries a 30-minute window where a fake / Judas move may form. |
| 9:30 AM | Opening bell. Range of 9:00–11:00 is a valid 2-hour window if morning session is chosen. |
| 11:00 AM–1:30 PM | New York lunch. Typically avoid; setups degrade. |
| 1:00 PM | Bond auction release (when scheduled). Anticipate move from this time. |
| 1:30 PM | PM session begins. ICT's preferred start time for afternoon trades. |
| 1:30–2:00 PM | Sweet spot formation window — often the clearest price action of the afternoon. |
| 2:00–3:00 PM | **PM Silver Bullet window.** Use sub-1-minute chart to sync with the in-progress higher-timeframe move. |
| 3:00 PM–close | Tertiary opportunity window. Every day a setup exists — requires correct time frame selection. |

**No-morning-data day rule:** If there are no medium/high-impact AM drivers, skip the morning session entirely. Schedule the eye appointment (as ICT says). Be in front of charts at 1:30 PM.

---

## What To Avoid

1. **Do not discard a NDOG/NWOG once it has been "filled."** The algorithm references old gaps repeatedly. Discarding them after first touch is a retail error.
2. **Do not chase relative equal highs/lows when a NDOG cluster is in the opposite direction.** The NDOG is the higher-priority target. The equal highs may be a Judas swing you would be entering into.
3. **Do not go short at the open of a new AM session when price forms relative equal highs and the NDOG is below.** Wait — the market needs to run those highs first (Judas swing) before dropping to the gap.
4. **Do not use only one time frame (e.g., 1-minute chart) and lose the narrative.** The 1-minute chart's pump candle at 1:00 PM is designed to trap traders into thinking it's a bullish reversal. Zoom out; the narrative says it's going lower.
5. **Do not trade the morning session on a no-data day.** It will be choppy, full of false breakouts, and will grind you up. Cleaner price action is in the afternoon.
6. **Do not clutter the active trading chart with all NDOGs/NWOGs.** Keep them on a separate reference layout. Switch layouts when checking levels, then switch back to your execution chart.
7. **Do not count a FVG's midpoint as equilibrium.** CE ≠ equilibrium. Equilibrium requires two-sided delivery.
8. **Do not enter a short if price has already touched the CE of the FVG.** The CE touch invalidates the weakness signature. If CE was touched, wait for price to move above CE and then look for an entry in the upper portion of the FVG.
9. **Do not attempt holding for large runs (100+ handles) before mastering consistent 5–10 handle intraday captures.** The psychological infrastructure for holding is built through demo/journaling, not by skipping stages.
10. **Do not copy live streamers or follow signal services.** This substitutes someone else's judgment for your own skill development and removes the learning loop.
11. **Do not overtrade on days with no clear narrative.** The economic calendar provides the reason for price to move. If there's no catalyst and no NDOG/NWOG draw, there's no trade.

---

## Algorithmic Notes

### NDOG Construction (pseudocode)

```
every trading day except Friday:
    ndog_level_A = close_price_at(17:00 Eastern)
    ndog_level_B = open_price_at(18:00 Eastern)  # first 1-min print

    ndog_high = max(ndog_level_A, ndog_level_B)
    ndog_low  = min(ndog_level_A, ndog_level_B)
    ndog_ce   = (ndog_high + ndog_low) / 2
    ndog_q25  = ndog_low + (ndog_high - ndog_low) * 0.25
    ndog_q75  = ndog_low + (ndog_high - ndog_low) * 0.75

    # Label format: "NDOG [DATE] [H/CE/L]"
    # Life cycle: mark active for next 5 trading days (skip holidays, add 1)
    # Store in reference layout, NOT execution layout
```

### NWOG Construction (pseudocode)

```
every Sunday:
    nwog_level_A = close_price_at(Friday 17:00 Eastern)
    nwog_level_B = open_price_at(Sunday 18:00 Eastern)

    nwog_high = max(nwog_level_A, nwog_level_B)
    nwog_low  = min(nwog_level_A, nwog_level_B)
    nwog_ce   = (nwog_high + nwog_low) / 2

    # Life cycle: active for 5 trading weeks
    # Label: "NWOG [DATE]"
```

### Directional Bias Filter (pseudocode)

```
gaps_above = count(ndogs + nwogs where level_high > current_price)
gaps_below = count(ndogs + nwogs where level_low < current_price)

if gaps_above > gaps_below:
    bias = LONG
elif gaps_below > gaps_above:
    bias = SHORT
else:
    bias = NONE  # no-trade condition ("no man's land")
```

### Relative Equal Low Quality Filter (from lectures 1–3)

```
# Two candidate swing lows qualify as a "relative equal low" target if:
right_low > left_low  # right-side low must be HIGHER than left-side low
abs(right_low - left_low) < threshold  # visually smooth / nearly equal
```

### FVG Weakness / Bearish Order Block Detection (pseudocode)

```
# On a 1-minute chart approaching a known news time:
for candle in approach_candles:
    if candle.high < fvg_ce:
        # Price failed to reach CE — algorithmic weakness signature
        # Next candle must also fail to breach candle.high
        if next_candle.high <= candle.high:
            bearish_ob = candle
            entry_signal = "short at bottom of bearish_ob on next touch"
            stop = fvg_ce  # or CE of next higher FVG if applicable

# Entry execution:
if price returns to bearish_ob.low:
    if candle moves away (closes below bearish_ob.low):
        enter_short(size=6)
```

### PM Session Trading Decision Tree

```
if no_medium_high_impact_AM_news:
    skip_morning_session()
    wait_until(13:30)

    if bond_auction_at_1300:
        anticipate_directional_move_from(13:00)
        look_for_fvg_weakness_between(12:30, 13:00)

    if setup_forms:
        enter_on_bearish_ob_touch()
        partial_below(nearest_relative_equal_low)
        hold_remainder_toward(ndog_cluster)

    elif no_setup_by_14:00:
        use_silver_bullet_window(14:00, 15:00)
```

### 150-Handle Proximity Rule for Old NDOGs

```
# Old NDOGs (> 5 trading days) remain relevant if:
abs(current_price - ndog_ce) <= 150  # handles (NQ/Nasdaq)
# AND narrative supports the draw direction
# Track in spiral notebook: market, date, NDOG high, NDOG low, CE, 
# first reference date, number of times referred to
```

---

## Notable Quotes

- "This is not for him [Caleb], but it's for the sake of completeness."
- "Midnight New York local time — that is the beginning of the true day. That's the beginning of the real true day in financial markets."
- "New day opening gaps have a life cycle of five days."
- "Once it fills, they say throw it out the window — it's done. Not me, brother. Not me."
- "If you have a clustering of new day opening gaps predominantly above where the market's trading at — oh my goodness, I'm getting moist — it's going to gravitate where the multitude of inefficiencies existed."
- "That is the real hidden magnet. That's the magnet on price."
- "You can predict relative equal highs and lows before they form. Yeah, you're [expletive] right. That's exactly what engineering liquidity is."
- "Inefficiencies are subordinate and less important than relative equal highs, relative equal lows, or New Day or New Week opening gaps."
- "CE is the midpoint of any gap or any inefficiency. That means if it's a SIBI — the best shorts will form at the lower half of that because you want to see the upper half left open. A midpoint of a BISI — the best fills for going long are going to form in the upper half of that."
- "I basically get a hard on from that. I am turned on by that when I'm in a trade — when I see it not even touch the consequent encroachment."
- "The fact that it goes up there and doesn't touch it — and then closes here — I know that is a bearish order block."
- "If there's no data, medium impact or high impact, in the morning session, try to trade the afternoon session because the cleaner price action will be after New York lunch."
- "New week opening gaps go with a life cycle of five weeks."
- "It's not a void of liquidity — it offered buy-side delivery. What's absent? Sell-side delivery."
- "The trade has to give me — if I want to take 10 handles — I have to look for something that's going to give me 15 to 20."
- "Process, practice, proficiency — in that order. That's how it happens. There's no circumvention."
- "Every single week, every single day — and it won't stop."
- "These candlesticks are not doing anything different than they did when they were doing it in 1992."
