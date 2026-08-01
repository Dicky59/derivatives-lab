"""FastAPI backend: serves the engine's outputs as JSON for the dashboard.

Thin wrapper — all real work lives in the engine. Fits the surface per request
for now (simple, always fresh); caching comes later.
"""
import glob
import duckdb
import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.pricing.surface import load_latest_surface
from src.pricing.ssvi import ssvi_surface
from src.signals.term_structure import term_structure_signal
from src.signals.skew_richness import skew_richness_signal
from src.signals.iv_rank_signal import iv_rank_signal
from src.pricing.metrics import build_atm_history
import config

app = FastAPI(title="derivatives-lab API", version="0.1.0")

# Allow the React dev server (localhost:3000) to call this API in the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"], allow_headers=["*"],
)

r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD


@app.get("/")
def root():
    return {"service": "derivatives-lab", "endpoints": ["/surface", "/signals", "/health"]}


@app.get("/health")
def health():
    """Cheap liveness check that also confirms a surface can be loaded."""
    try:
        s = load_latest_surface()
        return {"ok": True, "snapshot_ts": str(s["snapshot_ts"]),
                "n_expiries": len(s["slices"])}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/surface")
def get_surface():
    """Fitted SSVI surface: params, per-expiry theta/atm-vol, and a sampled grid."""
    s = load_latest_surface()
    surf, slices = s["surface"], s["slices"]

    # Per-expiry summary
    expiries = []
    for sl in slices:
        atm_vol = float(np.sqrt(sl["theta"] / sl["T"]))
        expiries.append({"T": sl["T"], "theta": sl["theta"], "atm_vol": atm_vol})

    # A sampled surface grid for the frontend to render (k x T -> iv)
    k_grid = np.linspace(-0.15, 0.15, 25).tolist()
    grid = []
    for sl in slices:
        row = []
        for k in k_grid:
            w = ssvi_surface(np.array([k]), sl["theta"], surf["rho"],
                             surf["eta"], surf["gamma"])[0]
            row.append(float(np.sqrt(max(w, 1e-12) / sl["T"])))
        grid.append({"T": sl["T"], "ivs": row})

    return {
        "snapshot_ts": str(s["snapshot_ts"]),
        "spot": s["S"],
        "params": {"rho": surf["rho"], "eta": surf["eta"], "gamma": surf["gamma"]},
        "k_grid": k_grid,
        "expiries": expiries,
        "surface_grid": grid,
    }


@app.get("/signals")
def get_signals():
    """All three signals fired on the latest surface."""
    s = load_latest_surface()
    slices, surf = s["slices"], s["surface"]

    ts_sig = term_structure_signal(slices)
    sk_sig = skew_richness_signal(slices, surf)

    history = build_atm_history("data/derived/date=*/enriched_*.parquet", r, q)
    vols = [h["atm_vol"] for h in history if h["atm_vol"] is not None]
    front_vol = float(np.sqrt(slices[0]["theta"] / slices[0]["T"]))
    ivr_sig = iv_rank_signal(front_vol, vols)

    return {
        "snapshot_ts": str(s["snapshot_ts"]),
        "term_structure": ts_sig,
        "skew_richness": sk_sig,
        "iv_rank": ivr_sig,
    }

@app.get("/history")
def get_history(max_staleness_hours: float = 6.0):
    """
    Front-tenor ATM vol history across snapshots, filtered to TRADING sessions.

    A snapshot is a real trading observation if its option quotes are fresh —
    i.e. quote_ts is within `max_staleness_hours` of snapshot_ts. On weekends/
    holidays the collector still fires but captures stale Friday quotes (quote_ts
    lags snapshot_ts by many hours), so those are filtered out. No market-calendar
    library needed — the staleness of the data itself identifies closed sessions.
    """
    # Determine which snapshots are "fresh" (trading sessions) via quote staleness.
    con = duckdb.connect(); con.execute("SET TimeZone='UTC'")
    paths = sorted(glob.glob("data/derived/date=*/enriched_*.parquet"))

    fresh_files = set()
    staleness_info = []
    for p in paths:
        row = con.execute(f"""
            SELECT min(snapshot_ts_utc) AS snap_ts,
                   max(quote_ts)        AS latest_quote
            FROM read_parquet('{p}')
            WHERE status='ok' AND quote_ts IS NOT NULL
        """).fetchone()
        snap_ts, latest_quote = row[0], row[1]
        if snap_ts is None or latest_quote is None:
            continue
        stale_hours = (snap_ts - latest_quote).total_seconds() / 3600.0
        is_fresh = stale_hours <= max_staleness_hours
        if is_fresh:
            fresh_files.add(p)
        staleness_info.append({
            "file": p.split("/")[-1].split("\\")[-1],
            "stale_hours": round(stale_hours, 2),
            "trading_session": is_fresh,
        })
    con.close()

    # Build the ATM-vol history (all snapshots), then keep only fresh ones.
    r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD
    full = build_atm_history("data/derived/date=*/enriched_*.parquet", r, q)

    points = []
    for h in full:
        if h.get("atm_vol") is None:
            continue
        # match this history entry's file against the fresh set
        fname = h.get("file", "")
        matched = any(fname in fp or fp.endswith(fname) for fp in fresh_files)
        if matched:
            points.append({"ts": str(h["ts"]), "atm_vol": float(h["atm_vol"])})

    vols = [p["atm_vol"] for p in points]
    return {
        "n_total_snapshots": len(full),
        "n_trading_sessions": len(points),
        "max_staleness_hours": max_staleness_hours,
        "points": points,                      # the clean, trading-day-only series
        "range": {"low": min(vols), "high": max(vols)} if vols else None,
        "staleness_debug": staleness_info,     # per-file freshness, for inspection
    }