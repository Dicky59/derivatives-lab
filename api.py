"""FastAPI backend: serves the engine's outputs as JSON for the dashboard.

Thin wrapper — all real work lives in the engine. Fits the surface per request
for now (simple, always fresh); caching comes later.
"""
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