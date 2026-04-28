# Design System — MEXC Signal Engine

## Product Context
- **What this is:** A private crypto futures signal dashboard — the command center for a live MEXC perpetual signal engine
- **Who it's for:** Solo trader / operator running the engine; personal tool, not public-facing
- **Space/industry:** Crypto futures trading, quantitative signal engines
- **Project type:** Web dashboard (to be built; Python/SQLite backend is live)

## Aesthetic Direction
- **Direction:** Precision-dark — "Bloomberg Terminal went to design school"
- **Decoration level:** Minimal — typography and data carry all weight, no gradients, no blobs, no decorative elements
- **Mood:** Serious precision instrument. Dense information, zero decoration. Feels like it was built by someone who actually trades, not assembled from a SaaS template.

## Typography
- **Display/Headers:** Instrument Sans (600 weight) — editorial precision, uncommon in trading tools, slightly warmer than geometric grotesques
- **Body/UI labels:** Outfit (400/500 weight) — modern, geometric, clean at small sizes, not overused
- **Data/prices/numbers:** JetBrains Mono (400/500 weight) — tabular-nums support, extremely readable at small sizes; use for ALL prices, percentages, timestamps, and numeric data
- **Loading:** Google Fonts CDN
  ```
  https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600&family=Outfit:wght@300;400;500&family=JetBrains+Mono:wght@400;500&display=swap
  ```
- **Scale:**
  - xs: 10px / 11px (table headers, labels, badges)
  - sm: 12px / 13px (table rows, secondary text)
  - base: 14px / 15px (body, UI labels)
  - md: 16px (section headers)
  - lg: 20px (panel titles)
  - xl: 28px (stat card values)
  - 2xl: 32px (hero display)

## Color
- **Approach:** Restrained — amber accent is rare and semantic (signal fired / brand); color is otherwise functional
- **Background:** `#0A0B0D` — near-black with a faint warm undertone, not pure black
- **Surface:** `#111318` — card and panel backgrounds
- **Surface elevated:** `#1A1D26` — dropdowns, hover states, inner panels
- **Border:** `#1F2330`
- **Primary text:** `#F0F2F7` — off-white, not harsh pure white
- **Muted text:** `#6B7280`
- **Accent:** `#F0A500` — amber; used for brand, CTAs, active state, TP prices, and regime timeline dots
- **Long / Win:** `#22C55E` — emerald; LONG signals, win outcomes, positive P&L
- **Short / Loss:** `#EF4444` — crisp red; SHORT signals, loss outcomes, negative P&L, stop prices
- **Stopped out:** `#F59E0B` — amber-warm; stopped-out outcome badges (distinct from full loss)
- **Semantic:** success `#22C55E`, warning `#F59E0B`, error `#EF4444`, info `#3B82F6`
- **Dark mode:** This is the primary/only mode. Light mode may be added later as a secondary option.
- **Dimmed variants (for backgrounds):**
  - Long dim: `rgba(34,197,94,0.12)`
  - Short dim: `rgba(239,68,68,0.12)`
  - Accent dim: `rgba(240,165,0,0.12)`

## Spacing
- **Base unit:** 4px
- **Density:** Compact — trading dashboards are data-dense; generous whitespace wastes screen real estate
- **Scale:**
  - 2xs: 2px / xs: 4px / sm: 8px / md: 12px / lg: 16px / xl: 20px / 2xl: 24px / 3xl: 32px
- **Exception:** Hero stat cards get `16px 20px` padding for intentional breathing room around key metrics

## Layout
- **Approach:** Grid-disciplined — 12-column, strict alignment
- **Sidebar:** Fixed left, 52px wide (icon-only nav)
- **Header:** Fixed top, 52px height
- **Max content width:** 1440px
- **Border radius:**
  - inputs / badges: `2px`
  - cards / panels / buttons: `4px`
  - modal overlays: `6px`
  - full/pill: `9999px`
  - **No bubbly radius — 4px is the ceiling on interactive elements**

## Signature UI Patterns
These are non-negotiable design elements that distinguish this product:

1. **Actuarial dot matrix for win rate** — render win rate as an N-dot grid (one dot per trade), colored by outcome (green=win, red=loss, amber=stopped). Conveys streaks at a glance; a percentage badge hides cold runs.

2. **Regime timeline bar instead of candlestick chart** — a horizontal segmented bar showing choppy/trending-up/trending-down/high-vol periods as colored segments, with LONG/SHORT signal dots overlaid at their fired positions. Regime context is what this engine trades on; price noise is irrelevant.

3. **LLM commentary inline** — display signal commentary in a blockquote-style panel with a left accent border in the amber color, styled as attributed text (italic, slightly smaller than body). Not a modal, not a tooltip — always visible on the active signal card.

## Motion
- **Approach:** Minimal-functional — only transitions that aid comprehension
- **Live signal pulse:** `6px` dot with opacity animation (1 → 0.4 → 1, 2s ease-in-out) for the LIVE badge
- **Price flash:** Subtle background pulse on a number cell when a price updates (50ms, ease-out)
- **State transitions:** 100ms ease-in-out for hover/focus states
- **No entrance animations, no scroll-driven effects, no decorative motion**
- **Easing:** enter `ease-out`, exit `ease-in`, move `ease-in-out`
- **Duration:** micro 50ms / short 100ms / medium 150-200ms

## CSS Custom Properties (reference)
```css
:root {
  --bg:           #0A0B0D;
  --surface:      #111318;
  --surface-up:   #1A1D26;
  --border:       #1F2330;
  --text:         #F0F2F7;
  --muted:        #6B7280;
  --accent:       #F0A500;
  --accent-dim:   rgba(240,165,0,0.12);
  --long:         #22C55E;
  --long-dim:     rgba(34,197,94,0.12);
  --short:        #EF4444;
  --short-dim:    rgba(239,68,68,0.12);
  --radius-sm:    2px;
  --radius:       4px;
  --radius-lg:    6px;
  --font-display: 'Instrument Sans', sans-serif;
  --font-ui:      'Outfit', sans-serif;
  --font-mono:    'JetBrains Mono', monospace;
}
```

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-28 | Initial design system | Created by /design-consultation; precision-dark aesthetic chosen for private trading command center |
| 2026-04-28 | Amber `#F0A500` accent over blue/purple | Every trading tool defaults to blue or purple gradients. Amber is semantic (signal fired, pay attention) and distinctive. |
| 2026-04-28 | Instrument Sans for display | Editorial precision — uncommon in trading tools, adds taste signal without sacrificing legibility |
| 2026-04-28 | 4px max border radius | Industry went round (8-12px everywhere). Sharp edges read as precision instrument, not friendly app. |
| 2026-04-28 | Actuarial dot matrix for win rate | Adopted from outside-voice subagent proposal — streaks are visible, cold runs can't hide in an average |
| 2026-04-28 | Regime timeline over candlestick chart | Adopted from outside-voice subagent proposal — this engine trades regime, not price; show the signal |
