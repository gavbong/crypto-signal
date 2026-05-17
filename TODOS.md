# TODOS

Deferred work captured during plan reviews. Each item has context so it can be picked up cold.

---

## T1: Polymarket wallet rotation detection (Poly funder graph)

**What:** Extend the `wallet_graph` Arbiscan lookup to also check Poly trader wallets. If two Poly wallets are funded from the same source address, flag them as potential same-operator siblings.

**Why:** The copy trader intelligence layer plan notes that wallet rotation is "PARTIALLY correct — especially on Polymarket." D3 only covers Hyperliquid candidates. The Poly rotation vector is unaddressed.

**Context:** D3 (Phase 2) ships Arbiscan lookups for HL candidates. Extend it to also check `poly_traders` using the same `wallet_graph` table (the `chain` column is already in the schema). Need to verify which chain Polymarket wallets use for funding (likely Polygon `0x2791...` USDC or Arbitrum) before implementing.

**Depends on:** D3 (Phase 2) completing and proving the rotation detection works for HL.

---

## T2: Polymarket discovery win_rate via CLOB trade history

**What:** Replace the D4 discovery score's capital-size proxy (`log1p(total_usdt) × log1p(markets_count)`) with a skill-based `win_rate` computed from historical resolved trades.

**Why:** The current simplified score selects for large capital deployment, not trading skill. A small wallet with consistent 70%+ win_rate on political markets is more valuable to follow than a whale who commits capital indiscriminately.

**Context:** D4 ships with the simplified score (Phase 2). The `data-api.polymarket.com` or CLOB API has a trade activity or history endpoint that returns resolved positions. Research the endpoint (likely `data-api.polymarket.com/activity?user={wallet}`), validate the response schema, and replace the score formula. Requires pagination for wallets with large trade histories.

**Depends on:** D4 (Phase 2) completing first. Don't block Phase 2 on this.

---

## T3: WebSocket real-time copy trader positions

**What:** Replace the 2-minute APScheduler poll in `copy_trader.py` with a WebSocket subscription to Hyperliquid's live position stream for tracked wallets.

**Why:** Top HL traders open and close positions in seconds. A 2-minute poll means copy entries lag by up to 2 minutes, potentially missing the best entry prices. For a shadow/analysis system this is acceptable now, but if the system is ever upgraded to real execution, the lag becomes costly.

**Context:** `copy_trader.py` uses a `BlockingScheduler` with a `CronTrigger` firing every 2 minutes. The Hyperliquid WebSocket API (`wss://api.hyperliquid.xyz/ws`) supports subscription to user position events. Requires significant refactor: replace `poll_positions_job()` with a `websockets`-based async handler, reconnect logic, and backpressure handling. This is a medium infrastructure project.

**Depends on:** Nothing — can be done independently after Phase 1+2 ship.

---

## T4: ML scoring model for HL candidates

**What:** Replace the rule-based `_composite_score()` formula with a learned model trained on historical leaderboard data and subsequent 30d PnL outcomes.

**Why:** The current formula weights are manually calibrated. A trained model can find non-linear relationships between early indicators (7d ROI spike, trade frequency patterns) and sustained 30d performance.

**Context:** The hl_candidates table will accumulate labeled training data: wallets that were promoted and subsequently tracked with known PnL outcomes. After 3–6 months of candidates data, train a gradient boosting model on `(pnl_7d, pnl_30d, trade_count, roi_7d) → promoted_wallet_next_30d_pnl`. Feature engineering is cheap; the bottleneck is waiting for labeled outcome data to accumulate.

**Depends on:** D1+D2 (Phase 1) running for 3+ months to generate training data.

---

## T5: GMX / dYdX integration (expand beyond HL + Poly)

**What:** Add a third copy-trading venue by implementing `gmx_trader.py` or `dydx_trader.py` mirroring the pattern established by `copy_trader.py` and `polymarket_trader.py`.

**Why:** The operator-tracking vision ("stop following wallets, start following operators") requires tracking operators across venues. A trader active on HL and GMX is more signal-rich than one venue alone.

**Context:** Both GMX (Arbitrum) and dYdX v4 (Cosmos chain) have public REST APIs for open positions. The architectural pattern (leaderboard → candidates → positions poll → copy_positions table) is fully established after the intelligence layer ships. Extension is primarily an API research + plumbing task.

**Depends on:** Phase 1 + Phase 2 completing. No new infrastructure needed.
