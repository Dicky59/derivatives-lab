"""Run the walk-forward backtest for the term-structure signal.
Outcome measured over real daily prices; honest INSUFFICIENT_DATA gate."""
import glob
import numpy as np
import duckdb

from src.pricing.ssvi import fit_ssvi_surface
from src.backtest.framework import walk_forward
from src.backtest.price_history import fetch_daily_bars
from src.backtest.test_term_structure import (ts_signal_fn, make_ts_outcome_fn,
                                              make_ts_success_fn)
import config

r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD
HORIZON_DAYS = 5   # forward window in TRADING DAYS (a week) — the signal's real horizon


def fit_snapshot(path, con):
    ts = con.execute(f"SELECT min(snapshot_ts_utc) FROM read_parquet('{path}')").fetchone()[0]
    exp = con.execute(f"""SELECT DISTINCT expiry,T_used FROM read_parquet('{path}')
        WHERE status='ok' AND iv_mid IS NOT NULL ORDER BY expiry""").df()
    slices, S = [], None
    for _, row in exp.iterrows():
        T = row["T_used"]
        if not (7/365 <= T <= 365/365): continue
        df = con.execute(f"""SELECT strike,iv_mid,underlying_price,(iv_ask-iv_bid) AS band
            FROM read_parquet('{path}') WHERE status='ok' AND expiry='{row["expiry"]}'
            AND iv_mid IS NOT NULL""").df()
        S = df["underlying_price"].iloc[0]
        df = df[(df["strike"]>=0.85*S)&(df["strike"]<=1.15*S)]
        thr = min(np.median(df["band"])*3.0, 0.15); df = df[df["band"]<=thr]
        if len(df) < 15: continue
        F = S*np.exp((r-q)*T); k=np.log(df["strike"].values/F); w=(df["iv_mid"].values**2)*T
        near=np.abs(k)<0.03
        iv=np.polyval(np.polyfit(k[near],df["iv_mid"].values[near],2),0.0) if near.sum()>=3 else df["iv_mid"].values[np.argmin(np.abs(k))]
        slices.append({"theta":(iv**2)*T,"k":k,"w":w,"T":T})
    slices.sort(key=lambda s:s["T"])
    if len(slices) < 3:
        return None
    return {"ts": ts, "underlying_price": float(S), "slices": slices}


con = duckdb.connect(); con.execute("SET TimeZone='UTC'")
paths = sorted(glob.glob("data/derived/date=*/enriched_*.parquet"))
print(f"Building point-in-time snapshots from {len(paths)} derived files...")
snapshots = []
for p in paths:
    snap = fit_snapshot(p, con)
    if snap is not None:
        snapshots.append(snap)
snapshots.sort(key=lambda s: s["ts"])
print(f"{len(snapshots)} usable point-in-time snapshots.")

# --- Fetch real daily SPY prices covering the snapshot span + forward horizon ---
first_date = str(snapshots[0]["ts"].date())
print(f"Fetching SPY daily bars from {first_date}...")
prices = fetch_daily_bars("SPY", start=first_date)
print(f"Got {len(prices)} daily bars (real underlying price series).\n")

outcome_fn = make_ts_outcome_fn(prices, HORIZON_DAYS)

# Baseline median realized vol (directional calibration)
tmp = walk_forward(snapshots, ts_signal_fn, outcome_fn,
                   lambda sig, out: True, horizon=HORIZON_DAYS, min_instances=1)
rvs = [x["outcome"]["realized_vol"] for x in tmp.get("detail", [])]
median_rv = float(np.median(rvs)) if rvs else 0.0
print(f"Baseline median realized vol across instances: {median_rv:.4f}")
print(f"(instances with a full {HORIZON_DAYS}-trading-day forward window: {len(rvs)})\n")

result = walk_forward(snapshots, ts_signal_fn, outcome_fn,
                      make_ts_success_fn(median_rv), horizon=HORIZON_DAYS)

print("="*60)
print("TERM-STRUCTURE SIGNAL BACKTEST")
print("="*60)
if result["status"] == "INSUFFICIENT_DATA":
    print(f"  STATUS: INSUFFICIENT_DATA")
    print(f"  {result['message']}")
    print(f"\n  ({result['instances']} instance(s) so far — wiring check, NOT conclusions:)")
    for x in result["detail"]:
        print(f"    {str(x['ts'])[:16]}  {x['signal']['regime']:14s} "
              f"realized_vol={x['outcome']['realized_vol']:.4f}  success={x['success']}")
else:
    print(f"  STATUS: OK  instances: {result['instances']}  hits: {result['hits']}")
    print(f"  hit rate: {result['hit_rate']:.2f}  95% CI: "
          f"[{result['ci_95'][0]:.2f}, {result['ci_95'][1]:.2f}]")