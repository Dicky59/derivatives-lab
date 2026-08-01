# derivatives-lab — Project Build Log

A personal derivatives-analysis system for options trading on Interactive Brokers
(built and tested against Alpaca paper data). Built from first principles, module by
module, with every component verified against an independent check. This log records
**what was built, why, and what was learned** — the reasoning behind the code.

> **Guiding principle throughout:** the LLM/AI layer never computes, prices, or trades.
> All numbers come from deterministic, verified code. Every quantitative claim is
> checked against an independent method before it's trusted.

---

## System overview

A complete quant research + risk pipeline, self-feeding and honest about its own limits:

```
Data capture (twice daily, automated)
   -> Enrichment (Black-Scholes IV + greeks per contract)
      -> SSVI volatility surface (arbitrage-free)
         -> Tradeable metrics (term structure, skew, IV rank)
            -> Risk engine (net greeks, surface-aware stress grids)
            -> Signal engine (falsifiable, quiet-by-design)
               -> Backtest framework (walk-forward, no-lookahead)
                  -> Dashboard (FastAPI backend + React frontend)
```

**Tech stack:** Python engine (numpy/scipy/pandas, DuckDB + Parquet storage,
alpaca-py for data), FastAPI backend, Next.js/React frontend (in progress).
Windows 11 dev environment, Git Bash, editable-installed package (`pip install -e .`).

---

## Module-by-module status

### M0 — Data pipeline  ✅ COMPLETE (self-feeding)
- **Collector** (`src/collector/snapshot.py`): single-shot capture of the full SPY
  option chain (~13,500–14,000 contracts) to Hive-partitioned, append-only Parquet.
  Stores **bid and ask separately** (never mid), plus underlying price captured in the
  *same* snapshot/timestamp. Raw data is immutable.
- **Scheduling** (`run_snapshot.bat` + `scripts/register_tasks.ps1`): Windows Task
  Scheduler runs the collector **and enrichment** twice daily (16:45 / 22:45 Helsinki).
  Registration is version-controlled PowerShell (reproducible, not trapped in the GUI).
- **Enrichment** (`src/analytics/enrich.py`): applies the pricing engine to each raw
  snapshot -> derived table with `iv_bid/iv_mid/iv_ask`, own greeks, moneyness, and a
  `status` column classifying each contract (ok / zero_bid / below_intrinsic /
  no_solution / expired / no_underlying). Never drops rows.
- **Known nulls (by design):** `open_interest` and `volume` aren't on Alpaca's
  market-data snapshot endpoint — kept as nullable columns, backfillable later from
  `get_option_contracts()`. Honest null beats a plausible wrong number.

### M2 — Pricing engine  ✅ COMPLETE (verified)
- **`src/pricing/black_scholes.py`**: European BS price + all five greeks
  (delta/gamma/vega/theta/rho), with continuous dividend yield.
  - Verified: textbook ATM call = **10.4506**; put–call parity holds to machine
    precision; greeks match finite-difference bumps to ~4 decimals.
- **`src/pricing/implied_vol.py`**: robust IV inversion via **Brent's method**
  (bracketed, derivative-free — beats Newton, which blows up where vega -> 0).
  Returns `None` (never a fake number) on unsolvable/below-intrinsic inputs.
  - Verified: round-trip (price with sigma -> invert -> recover sigma) to 1e-6.

### M2b — Pricing engine on real data  ✅ COMPLETE
- Marries M0 data with M2 pricing. Cross-checked own IV/greeks vs Alpaca's reference
  values: **IV within ~0.002, delta within ~0.003.** Confirmed flat r/q (~3.9% / 1.2%)
  is good enough — no live rate curve needed.

### M3 — Volatility surface  ✅ COMPLETE
- **M3.1 raw SVI** (`src/pricing/svi.py`): single-smile fit. Fit **total variance**
  (w = iv²·T), in **log-forward-moneyness** (k = ln(K/F), forward not spot). Robust fit
  via `differential_evolution` + Nelder-Mead polish with **data-scaled bounds**.
- **M3.2 surface** (`src/pricing/surface.py`): per-expiry loop. This step *demonstrated*
  the two problems raw independent fitting has: **rho zigzags** (−0.9..+0.45 across
  adjacent slices) and **17 calendar-arbitrage violations**.
- **M3.3 SSVI** (`src/pricing/ssvi.py`): the fix. Surface-SVI couples all expiries
  through a **single shared rho** + power-law φ(θ), anchored to the ATM total-variance
  term structure θ(T). Butterfly no-arbitrage condition `θφ(1+|ρ|) < 4` **enforced
  during the fit**. Result: **one stable rho (−0.59)**, butterfly-free, and calendar
  violations **17 -> 0**. Rescued 3 expiries raw SVI couldn't fit (9 -> 12 slices).
- **M3.4 metrics** (`src/pricing/metrics.py`): term structure (contango/backwardation +
  slope), skew (ATM skew slope + risk reversal per expiry), and **IV rank** with an
  `build_atm_history()` feed that assembles the front-tenor ATM vol series across all
  snapshots. IV rank activates automatically at 20 snapshots.

### M4 — Risk engine  ✅ COMPLETE (honest by default)
- **`src/risk/position.py`**: positions as lists of leg-dicts (options + underlying,
  signed qty). **×100 contract multiplier** applied to every option leg.
  - `net_greeks` — signed, multiplier-scaled net exposure.
  - `stress_grid` — sticky-strike (frozen IV) spot×vol P&L grid.
  - `stress_grid_surface` — **sticky-moneyness**: under a shock, re-reads each leg's IV
    off the SSVI surface at its NEW moneyness. Reveals skew risk sticky-strike hides.
- **Verified** on known structures: long/short call greek signs; bull call spread
  (capped both ways); iron condor; calendar (net long vega, term-structure risk).
- **Safety fixes applied:** default stress range widened to **±15%** (a ±5% grid hid a
  3× larger condor loss); `surface_iv` **flags extrapolation** when a leg's moneyness
  falls outside the fitted k-range (extreme-shock cells marked approximate).

### M5 — Signal engine  ✅ COMPLETE (core; quiet-by-design)
Three signals, each with a **rule + economic rationale + falsification condition**,
each honestly labelled `UNVALIDATED (needs M6 backtest)`. On calm data they correctly
stay quiet — a signal that fires constantly can't be trusted.
- **Term structure** (`src/signals/term_structure.py`): CONTANGO / BACKWARDATION / FLAT.
  Backwardation = abnormal, near-term event risk. *Falsifies if:* backwardation doesn't
  precede larger realized moves than contango.
- **Skew richness** (`src/signals/skew_richness.py`): fit smooth skew term structure
  (a/√T), flag 2σ residuals as local dislocations. *Falsifies if:* flagged-rich
  expiries don't revert toward the curve. (Anchor B — skew vs realized — scaffolded.)
- **IV rank** (`src/signals/iv_rank_signal.py`): vol mean-reversion. Fires SELL_PREMIUM
  high / AVOID low. **Confidence scales with history depth** (provisional -> moderate ->
  solid). Scaffolded below 20 snapshots; activates automatically. *Falsifies if:* high
  IV-rank days aren't followed by vol declines.

### M6 — Backtest framework  ✅ COMPLETE (honest framework, awaiting data)
- **`src/backtest/framework.py`**: **walk-forward, point-in-time**. When a signal is
  evaluated at time T it sees ONLY snapshots ≤ T; the outcome is measured strictly over
  T+1..T+horizon. **This structural separation is the no-lookahead guarantee.**
- **Honest gating:** returns `INSUFFICIENT_DATA` below 30 instances (a backtest of <30
  is noise); reports hit rate **with a 95% confidence interval** when it does resolve.
- **`src/backtest/price_history.py`**: pulls **real SPY daily bars** from Alpaca for the
  realized-outcome measure (the underlying price series exists for years even though
  surface history is days old). Realized vol measured over a horizon in **trading days**.
- **State:** correctly reports 0 usable instances today — forward windows haven't closed
  yet (the future literally hasn't happened). That's the framework refusing to cheat.
  Matures automatically as history accumulates.

### Dashboard backend  ✅ COMPLETE
- **`api.py`** (FastAPI): `/health`, `/surface`, `/signals` endpoints wrapping the engine,
  returning JSON. CORS enabled for the React dev server. Auto-generated `/docs` (Swagger)
  used to verify every endpoint in-browser before any frontend existed.
- **`load_latest_surface()`** in `surface.py` = single source of truth; kills the
  "every script refits the surface independently" debt.
- Verified live: `/surface` returns rho≈−0.56, spot ≈743, full term structure; `/signals`
  returns all three signal states as structured JSON.

### Dashboard frontend  🔜 IN PROGRESS (next)
Next.js / React / TypeScript reading from the FastAPI endpoints. This is the builder's
home turf (senior frontend background). Slow data cadence -> simple fetch-on-load UI, no
real-time needed.

---

## Key architectural decisions (and why)

1. **Python engine, not TypeScript** — the whole quant core is Python (scipy, QuantLib
   ecosystem). FastAPI serves it directly; the React frontend reads JSON. Each language
   does what it's best at.
2. **Store bid/ask separately, never mid** (M0) — you cannot reconstruct a spread from a
   mid, and the spread IS the cost model. This one decision made the honest IV-band and
   the sticky-moneyness risk both possible.
3. **Capture underlying price in the same snapshot/timestamp** — a minute's mismatch
   biases every IV silently.
4. **Fixed, timestamped ticker universe** — avoids silent survivorship-style gaps.
5. **Raw data immutable; derived data recomputable** — raw snapshots are never modified;
   enrichment/surface/metrics are all regenerable.
6. **Build risk before signals** (M4 before M5) — so every signal idea lands into a risk
   engine that shows its worst case *before* it can be sized. Matches the trader's
   start-small-scale-with-experience discipline.
7. **Every signal is falsifiable** — a rule + rationale + an explicit condition that
   would prove it wrong. M6 tests each against its own falsification condition.
8. **Honest gating everywhere** — IV rank refuses to rank below 20 snapshots; the
   backtest refuses conclusions below 30 instances. Better to say "not enough data" than
   to present noise as signal.

---

## Lessons learned (the hard-won ones)

- **SSVI needs monotone θ.** Independent per-slice fitting gave calendar arbitrage; SSVI
  with a shared rho + monotone ATM total-variance term structure removed it *by
  construction*. When θ dipped (from one noisy far-dated quote), calendar arbitrage
  reappeared — fixed by extracting θ robustly (local quadratic at k=0), not from a single
  cherry-picked strike.
- **Nearest expiry & far wings are the least trustworthy data.** Expiry-day options give
  garbage IV (445% "vol"); thin wings give wide bands. Fit and signal on the liquid
  middle (~20–60 DTE, within ±15% of spot); treat edges as extrapolation.
- **Stress ranges must reach a structure's boundaries.** A ±5% grid hid an iron condor's
  true ~3× larger loss because the protective wings sat at ±10%. Always stress past the
  long strikes.
- **Skew adds real tail risk to short-premium trades.** Sticky-moneyness (surface-aware)
  showed ~30–40% more downside on a short strangle/condor than frozen-IV pricing — real
  where legs are inside the fitted range, approximate (flagged) where they extrapolate.
- **The most dangerous backtest bug is the one that doesn't error.** M6 first produced
  realized-vol = 0.0000 (sparse snapshot prices) and counted fake instances. Caught on
  tiny data where it was obvious, not months later hidden inside plausible numbers.
- **A quiet signal engine is a trustworthy one.** On calm data all three signals
  correctly say "normal." Credibility for the rare loud day is earned by not crying wolf.
- **Verify against an independent method, not the code itself.** BS price vs textbook +
  parity; greeks vs finite differences; IV vs round-trip; own greeks vs Alpaca's;
  no-lookahead vs timestamp ordering. Every layer cross-checked.
- **`have: 1` vs `have: 8` taught the pipeline-gap lesson:** the collector was automated
  but enrichment wasn't — raw data piled up while derived lagged. Now enrichment runs in
  the same scheduled `.bat`, so the pipeline is truly self-feeding.

---

## Known follow-ups (tracked, not blocking)

- **Weekend/holiday snapshots are stale duplicates — add a trading-day filter (analysis
  layer).** US markets are closed weekends and holidays, but Task Scheduler keeps firing,
  so the collector captures frozen Friday-close quotes on Sat/Sun (and on holidays like
  Thanksgiving / July 4). These are harmless and *identifiable* — on a closed day
  `quote_ts` lags `snapshot_ts` by hours/days — but they add flat, non-informative points.
  **Risk:** once IV rank and the backtest produce real numbers (~2 weeks out), flat
  weekend points can dilute the vol range and distort time-based measures. **Fix (do NOT
  put in the collector — keep raw capture dumb/immutable):** add a trading-day filter in
  the *analysis* layer — `build_atm_history()` and the backtest snapshot assembly — using
  a US market calendar (`pandas_market_calendars`, NYSE). This correctly handles holidays,
  which a naive "skip weekends" check would miss. The M6 backtest already sidesteps this
  for *outcomes* (it uses real Alpaca daily trading bars, which skip non-sessions); the
  gap is only in the *surface-snapshot* history. Add before relying on IV-rank range.
- **Candidate-structure mapping is a placeholder.** The term-structure signal's CONTANGO
  case proposed a long-vol calendar (net vega +68) that doesn't match its "sell near-term
  premium" rationale. The signal *detection* is sound; the *"which trade expresses this
  view"* logic needs a deliberate pass — shared across all signals, so do it once.
  **Do this AFTER M6 validates signals**, not before (don't polish trade suggestions for
  unvalidated signals).
- **Anchor B (skew vs realized downside)** — needs return history; scaffolded.
- **Surface caching in the API** — currently fits per request (a few seconds). Cache the
  fit and refresh when a new snapshot lands. Simple optimization, do after frontend works.
- **Refactor scripts to call `load_latest_surface()`** — several scripts still duplicate
  the load-and-fit loop; the API now has the single-source-of-truth version to migrate to.
- **`risk_surface_check.py`** — has a 3-value unpack of `stress_grid_surface` that now
  returns 4; add the trailing `_` next time it's run.

---

## What's waiting on time (not code)

Almost everything left matures on its own as the collector runs:
- **IV rank activates at 20 snapshots** (~5 days from 11).
- **Backtest instances accumulate** as forward windows close; conclusions possible around
  the ~4-week mark with real, non-cheating results.
- **Signal confidence firms up** (provisional -> moderate) as history deepens.

The system now works while you sleep and gets smarter every day untouched. The most
valuable near-term activity is to **let data accumulate and watch it mature** — run
`run_signals.py` / `backtest_signals.py` every few days (or watch the dashboard) as IV
rank comes online and backtest instances climb.

---

## Module map (files)

```
src/
  collector/snapshot.py         M0 capture
  analytics/enrich.py           M0/M2b enrichment
  pricing/
    black_scholes.py            M2 price + greeks
    implied_vol.py              M2 IV inversion (Brent)
    svi.py                      M3.1 raw SVI single smile
    surface.py                  M3.2 surface + load_latest_surface()
    ssvi.py                     M3.3 arbitrage-free SSVI
    metrics.py                  M3.4 term structure, skew, IV rank, history feed
  risk/position.py              M4 net greeks + stress grids (sticky-strike & surface)
  signals/
    term_structure.py           M5 term-structure regime
    skew_richness.py            M5 skew dislocation
    iv_rank_signal.py           M5 IV-rank mean-reversion
  backtest/
    framework.py                M6 walk-forward, point-in-time
    price_history.py            M6 real daily bars for outcomes
    test_term_structure.py      M6 term-structure signal's outcome/success test
api.py                          FastAPI backend
scripts/                        run_signals, surface_metrics, atm_history, backtest_signals,
                                risk_structures, risk_surface_check, fit_surface, fit_ssvi, ...
tests/test_imports.py           pytest smoke tests (BS price 10.4506, IV round-trip)
```

---

*This log distils the design decisions and lessons from the build. Keep it in the repo
alongside the code it describes; update it as modules evolve.*
