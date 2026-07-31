"""Fit a full SVI volatility surface: one raw-SVI slice per viable expiry.

Generalizes scripts/fit_one_smile.py (M3.1, single hardcoded expiry) into a
per-expiry loop over a derived snapshot, plus a calendar-arbitrage scan across
the independently-fitted slices. Slices are fit independently here (no shared
constraint across expiries) so calendar-arbitrage crossings are expected —
reported as a diagnostic, not repaired (that's M3.3).
"""
import re
import glob
import duckdb
import numpy as np
import pandas as pd

import config
from src.pricing.svi import svi_raw, fit_svi
from src.pricing.ssvi import fit_ssvi_surface
from src.risk.position import fitted_k_range

T_MIN_DAYS, T_MAX_DAYS = 7, 90   # expiry selection window
MONEYNESS_BAND = 0.15            # near-money: strike within +/-15% of spot
BAND_MULT = 3.0                  # relative band-outlier multiplier
BAND_ABS_CAP = 0.05              # absolute IV-band cap (vol terms)
MIN_POINTS = 15                  # minimum survivors required to attempt a fit


def band_keep_mask(band, mult=BAND_MULT, abs_cap=BAND_ABS_CAP):
    """Per-expiry adaptive band filter.

    Effective threshold is the TIGHTER of (median(band)*mult) and abs_cap:
    normally the relative rule governs (small median -> small threshold), but
    if an expiry's quotes are broadly noisy (median itself inflated), the
    absolute cap clamps it down so a wide-quoted expiry can't pass everything.
    """
    band = np.asarray(band, float)
    threshold = min(np.median(band) * mult, abs_cap)
    return band <= threshold


def _snapshot_date_ts(parquet_path):
    """Parse (date_str, ts_str) out of the enriched_<ts>.parquet naming convention."""
    m = re.search(r"date=([\d-]+)[/\\]enriched_(\d{8}T\d{6}Z)\.parquet", str(parquet_path))
    if not m:
        raise ValueError(f"Cannot parse date=.../enriched_<ts>.parquet from {parquet_path}")
    return m.group(1), m.group(2)


def fit_surface(parquet_path):
    """Load a derived snapshot and fit one SVI slice per viable expiry.

    Returns the surface DataFrame (also written to
    data/derived/date=<date>/surface_<ts>.parquet).
    """
    parquet_path = str(parquet_path)
    r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD

    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")

    expiries = con.execute(f"""
        SELECT expiry, min(T_used) AS T
        FROM read_parquet('{parquet_path}')
        WHERE status='ok' AND iv_mid IS NOT NULL
        GROUP BY expiry
        ORDER BY expiry
    """).df()

    t_min, t_max = T_MIN_DAYS / 365.0, T_MAX_DAYS / 365.0
    rows = []
    skipped = []

    for _, exp_row in expiries.iterrows():
        expiry, T = exp_row["expiry"], exp_row["T"]

        if not (t_min <= T <= t_max):
            skipped.append((expiry, f"out_of_range(T={T:.4f})"))
            continue

        df = con.execute(f"""
            SELECT strike, iv_mid, iv_bid, iv_ask, underlying_price
            FROM read_parquet('{parquet_path}')
            WHERE status='ok' AND iv_mid IS NOT NULL AND expiry = '{expiry}'
            ORDER BY strike
        """).df()
        n_raw = len(df)

        S = df["underlying_price"].iloc[0]
        near_money = df["strike"].between(S * (1 - MONEYNESS_BAND), S * (1 + MONEYNESS_BAND))
        df = df[near_money]

        band = (df["iv_ask"] - df["iv_bid"]).values
        if len(band) > 0:
            df = df[band_keep_mask(band)]
        n_used = len(df)

        if n_used < MIN_POINTS:
            skipped.append((expiry, f"too_few_points(n_used={n_used})"))
            continue

        F = S * np.exp((r - q) * T)
        k = np.log(df["strike"].values / F)
        w = (df["iv_mid"].values ** 2) * T
        weights = np.ones_like(w)  # equal weights: band-as-weight biased the fit low (M3.1 finding)

        try:
            fit = fit_svi(k, w, weights)
        except Exception as e:
            skipped.append((expiry, f"fit_raised({e!r})"))
            continue

        a, b, rho, m, c = fit["a"], fit["b"], fit["rho"], fit["m"], fit["c"]
        sane = (
            b > 0 and abs(rho) < 1 and c > 0
            and np.isfinite([a, b, rho, m, c, fit["rmse"]]).all()
        )
        if not sane:
            skipped.append((expiry, f"insane_params(a={a:.4g},b={b:.4g},rho={rho:.4g},m={m:.4g},c={c:.4g})"))
            continue

        atm_vol = np.sqrt(max(svi_raw(0.0, a, b, rho, m, c), 1e-12) / T)
        rows.append({
            "expiry": expiry, "T": T, "F": F, "n_raw": n_raw, "n_used": n_used,
            "a": a, "b": b, "rho": rho, "m": m, "c": c,
            "rmse": fit["rmse"], "atm_vol": atm_vol,
        })

    surface = pd.DataFrame(rows).sort_values("expiry").reset_index(drop=True)

    print(f"Fitted {len(surface)} expiries, skipped {len(skipped)}:")
    for expiry, reason in skipped:
        print(f"  SKIP {expiry}: {reason}")
    print()
    print(surface.to_string(index=False))

    date_str, ts_str = _snapshot_date_ts(parquet_path)
    out_dir = config.DATA_DIR / "derived" / f"date={date_str}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"surface_{ts_str}.parquet"
    surface.to_parquet(out_path, index=False)
    print(f"\nWrote {out_path}")

    return surface


def scan_calendar_arbitrage(surface_df, k_grid=None):
    """Diagnostic-only calendar-arbitrage scan across independently-fitted slices.

    Total variance w(k) must be non-decreasing in T at fixed k (no-arbitrage).
    Since each expiry is fit independently, crossings are expected here; this
    reports them (count + T-range) without attempting a repair (M3.3's job).
    """
    if k_grid is None:
        k_grid = np.linspace(-0.15, 0.15, 61)

    surface_df = surface_df.sort_values("T").reset_index(drop=True)
    n_violations = 0
    violation_Ts = []

    for i in range(len(surface_df) - 1):
        row_a, row_b = surface_df.iloc[i], surface_df.iloc[i + 1]
        w_a = svi_raw(k_grid, row_a["a"], row_a["b"], row_a["rho"], row_a["m"], row_a["c"])
        w_b = svi_raw(k_grid, row_b["a"], row_b["b"], row_b["rho"], row_b["m"], row_b["c"])
        crossed = w_b < w_a
        n = int(crossed.sum())
        if n > 0:
            n_violations += n
            violation_Ts.extend([row_a["T"], row_b["T"]])

    violation_T_range = (min(violation_Ts), max(violation_Ts)) if violation_Ts else None
    return {"n_violations": n_violations, "violation_T_range": violation_T_range}

def load_latest_surface():
    """
    Load the most recent derived snapshot, fit the SSVI surface, and return
    everything downstream consumers need. Single source of truth — API,
    scripts, and dashboards all call this instead of each re-implementing it.

    Returns dict: {path, S, slices, surface, snapshot_ts}
    """
    r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD
    paths = sorted(glob.glob("data/derived/date=*/enriched_*.parquet"))
    if not paths:
        raise FileNotFoundError("No derived snapshots under data/derived/")
    path = paths[-1]

    con = duckdb.connect(); con.execute("SET TimeZone='UTC'")
    snapshot_ts = con.execute(
        f"SELECT min(snapshot_ts_utc) FROM read_parquet('{path}')").fetchone()[0]
    exp = con.execute(f"""SELECT DISTINCT expiry,T_used FROM read_parquet('{path}')
        WHERE status='ok' AND iv_mid IS NOT NULL ORDER BY expiry""").df()

    slices, S = [], None
    for _, row in exp.iterrows():
        T = row["T_used"]
        if not (7/365 <= T <= 365/365):
            continue
        df = con.execute(f"""SELECT strike,iv_mid,underlying_price,(iv_ask-iv_bid) AS band
            FROM read_parquet('{path}') WHERE status='ok' AND expiry='{row["expiry"]}'
            AND iv_mid IS NOT NULL""").df()
        S = df["underlying_price"].iloc[0]
        df = df[(df["strike"] >= 0.85*S) & (df["strike"] <= 1.15*S)]
        thr = min(np.median(df["band"])*3.0, 0.15); df = df[df["band"] <= thr]
        if len(df) < 15:
            continue
        F = S*np.exp((r-q)*T)
        k = np.log(df["strike"].values/F)
        w = (df["iv_mid"].values**2)*T
        near = np.abs(k) < 0.03
        iv = (np.polyval(np.polyfit(k[near], df["iv_mid"].values[near], 2), 0.0)
              if near.sum() >= 3 else df["iv_mid"].values[np.argmin(np.abs(k))])
        slices.append({"theta": (iv**2)*T, "k": k, "w": w, "T": T})
    con.close()

    slices.sort(key=lambda s: s["T"])
    fit = fit_ssvi_surface(slices)
    surface = {"rho": fit["rho"], "eta": fit["eta"], "gamma": fit["gamma"],
               "theta_by_T": [(s["T"], s["theta"]) for s in slices],
               "k_range": fitted_k_range(slices)}
    return {"path": path, "S": float(S), "slices": slices,
            "surface": surface, "snapshot_ts": snapshot_ts}
