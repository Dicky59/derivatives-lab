"""Surface metrics: term structure, skew, risk reversal, and IV-rank + history.

Consumes a fitted SSVI surface (shared rho, eta, gamma + per-slice theta/T) and
produces the tradeable numbers that feed signal logic downstream, plus assembles
a front-tenor ATM vol history across snapshots for IV rank.
"""
import numpy as np
import glob
from pathlib import Path

from src.pricing.ssvi import ssvi_surface

def _is_trading_session(parquet_path, con, max_staleness_hours=6.0):
    """
    Is this snapshot a real trading session (fresh quotes), or a stale
    weekend/holiday/off-hours capture?

    On a live session the option quotes are fresh: quote_ts is within
    max_staleness_hours of snapshot_ts. On a closed day (or a pre-market test
    run) the collector still fires but captures stale quotes, so quote_ts lags
    snapshot_ts by many hours. Returns (is_fresh, stale_hours).
    """
    row = con.execute(f"""
        SELECT min(snapshot_ts_utc) AS snap_ts, max(quote_ts) AS latest_quote
        FROM read_parquet('{parquet_path}')
        WHERE status='ok' AND quote_ts IS NOT NULL
    """).fetchone()
    snap_ts, latest_quote = row[0], row[1]
    if snap_ts is None or latest_quote is None:
        return False, None
    stale_hours = (snap_ts - latest_quote).total_seconds() / 3600.0
    return (stale_hours <= max_staleness_hours), stale_hours


def term_structure_metrics(slices):
    """
    slices: list of {"T": float, "theta": float, ...}, sorted by T.
    Returns ATM vol per tenor, the overall slope, and the regime label.
    """
    Ts = np.array([s["T"] for s in slices])
    thetas = np.array([s["theta"] for s in slices])
    atm_vols = np.sqrt(thetas / Ts)           # sigma_atm = sqrt(theta / T)

    # Slope of ATM vol vs T (per year). Positive = contango, negative = backwardation.
    slope = np.polyfit(Ts, atm_vols, 1)[0]
    regime = "contango" if slope > 0 else "backwardation"

    return {
        "atm_vol_by_T": list(zip(Ts.tolist(), atm_vols.tolist())),
        "front_atm_vol": float(atm_vols[0]),
        "back_atm_vol": float(atm_vols[-1]),
        "slope_per_year": float(slope),
        "regime": regime,
    }


def skew_metrics(surface_fit, slices, r=None, q=None):
    """
    Per-expiry skew: ATM skew slope (dsigma/dk at k=0) and a proxy 25-delta
    risk reversal, using the fitted SSVI surface.

    surface_fit: dict with rho, eta, gamma (shared).
    slices: list of {"T", "theta", ...} sorted by T.
    """
    rho, eta, gamma = surface_fit["rho"], surface_fit["eta"], surface_fit["gamma"]
    out = []
    for s in slices:
        T, theta = s["T"], s["theta"]

        # ATM skew slope: numerically differentiate sigma(k) at k=0.
        h = 1e-4

        def sigma_at(k):
            w = ssvi_surface(np.array([k]), theta, rho, eta, gamma)[0]
            return np.sqrt(max(w, 1e-12) / T)

        skew_slope = (sigma_at(h) - sigma_at(-h)) / (2 * h)

        # Proxy 25-delta risk reversal: sigma at fixed +/- moneyness meant to
        # approximate 25-delta wings. Using k = +/-0.10 as a stable proxy
        # (true 25-delta requires solving delta=0.25; this is the standard
        # quick proxy and is monotone in the real thing).
        sig_put_wing = sigma_at(-0.10)   # OTM put side (k<0)
        sig_call_wing = sigma_at(+0.10)  # OTM call side (k>0)
        risk_reversal = sig_put_wing - sig_call_wing   # >0: puts richer (fear)

        out.append({
            "T": T,
            "atm_skew_slope": float(skew_slope),
            "rr_proxy_10pct": float(risk_reversal),
            "put_wing_vol": float(sig_put_wing),
            "call_wing_vol": float(sig_call_wing),
        })
    return out


def iv_rank(current_atm_vol, history_atm_vols, min_history=20):
    """
    IV rank and percentile of today's ATM vol vs its own trailing history.

    Returns 'insufficient_history' until min_history snapshots exist, then
    produces real values automatically as history accumulates.

    history_atm_vols: 1D array of past front-tenor ATM vols (chronological).
    """
    hist = np.asarray(history_atm_vols, float)
    hist = hist[np.isfinite(hist)]
    if len(hist) < min_history:
        return {
            "status": "insufficient_history",
            "have": int(len(hist)),
            "need": min_history,
        }
    lo, hi = np.min(hist), np.max(hist)
    iv_rank_val = (current_atm_vol - lo) / (hi - lo) if hi > lo else 0.0
    iv_pctile = float(np.mean(hist <= current_atm_vol))
    return {
        "status": "ok",
        "iv_rank": float(np.clip(iv_rank_val, 0, 1)),   # position in min-max range
        "iv_percentile": iv_pctile,                     # fraction of days below today
        "current": float(current_atm_vol),
        "hist_low": float(lo),
        "hist_high": float(hi),
        "n": int(len(hist)),
    }


def _front_atm_vol_from_snapshot(parquet_path, r, q, con,
                                 t_min=7/365, t_max=365/365,
                                 band_abs_cap=0.15, min_points=15):
    """
    Extract the FRONT-tenor ATM vol from one derived snapshot, using the same
    robust theta-quadratic method as the surface fit. Returns (snapshot_ts, atm_vol)
    or (snapshot_ts, None) if no viable front expiry.
    """
    ts = con.execute(f"""
        SELECT min(snapshot_ts_utc) FROM read_parquet('{parquet_path}')
    """).fetchone()[0]

    expiries = con.execute(f"""
        SELECT DISTINCT expiry, T_used FROM read_parquet('{parquet_path}')
        WHERE status='ok' AND iv_mid IS NOT NULL ORDER BY expiry
    """).df()

    best = None  # (T, atm_vol) for the shortest viable expiry
    for _, row in expiries.iterrows():
        T = row["T_used"]
        if not (t_min <= T <= t_max):
            continue
        df = con.execute(f"""
            SELECT strike, iv_mid, underlying_price, (iv_ask-iv_bid) AS band
            FROM read_parquet('{parquet_path}')
            WHERE status='ok' AND expiry='{row["expiry"]}' AND iv_mid IS NOT NULL
        """).df()
        S = df["underlying_price"].iloc[0]
        df = df[(df["strike"] >= 0.85*S) & (df["strike"] <= 1.15*S)]
        if len(df) == 0:
            continue
        thr = min(np.median(df["band"]) * 3.0, band_abs_cap)
        df = df[df["band"] <= thr]
        if len(df) < min_points:
            continue
        F = S * np.exp((r - q) * T)
        k = np.log(df["strike"].values / F)
        near = np.abs(k) < 0.03
        if near.sum() >= 3:
            iv_atm = np.polyval(np.polyfit(k[near], df["iv_mid"].values[near], 2), 0.0)
        else:
            iv_atm = df["iv_mid"].values[np.argmin(np.abs(k))]
        best = (T, float(iv_atm))
        break  # shortest viable expiry = front tenor; stop at first

    return ts, (best[1] if best else None)


def build_atm_history(derived_glob, r, q, trading_sessions_only=True,
                      max_staleness_hours=6.0):
    """
    Walk all derived snapshots matching derived_glob, extract front ATM vol from
    each, and return a chronological list of {"ts", "atm_vol", "file"}.

    trading_sessions_only (default True): exclude stale weekend/holiday/off-hours
    captures via quote-staleness, so IV rank / history / backtest all see only
    real trading sessions. Stale files stay on disk (raw data immutable) but are
    ignored analytically. Set False to include everything (e.g. for auditing).
    """
    import duckdb
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")

    paths = sorted(glob.glob(derived_glob))
    history = []
    for p in paths:
        if trading_sessions_only:
            is_fresh, _ = _is_trading_session(p, con, max_staleness_hours)
            if not is_fresh:
                continue                      # skip stale (closed-market) snapshot
        ts, vol = _front_atm_vol_from_snapshot(p, r, q, con)
        history.append({"ts": ts, "atm_vol": vol, "file": Path(p).name})
    con.close()
    history.sort(key=lambda h: h["ts"])
    return history