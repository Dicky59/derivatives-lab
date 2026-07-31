"""IV-rank signal (volatility mean-reversion).

Rule: fire SELL_PREMIUM when front-month IV rank is high (vol elevated vs its
own trailing range, tends to revert down); fire AVOID_SELLING when low (vol
cheap, selling collects little and risks a spike). NEUTRAL in between.

Economic rationale: volatility mean-reverts — one of the more robust empirical
regularities. High IV rank => premium rich => selling has edge as vol falls.

Falsification (M6): high-IV-rank days should be followed by vol DECLINES; if
not, no edge.

Confidence scales with history depth: convention assumes ~252d lookback. With
fewer snapshots the rank is provisional (narrow, jumpy range) — reported
honestly, firms up as history matures.
"""
import numpy as np

MIN_HISTORY = 20          # below this: scaffold only, no signal
FULL_CONFIDENCE = 120     # snapshots at which we treat the rank as solid


def iv_rank_signal(current_atm_vol, history_atm_vols,
                   high=0.70, low=0.20):
    """
    current_atm_vol: today's front-tenor ATM vol.
    history_atm_vols: chronological trailing series (from build_atm_history).
    high/low: IV-rank thresholds for fire/avoid.

    Returns a signal dict. Below MIN_HISTORY it returns status 'scaffold'
    (not enough history to fire), with 'have'/'need' so you can see progress.
    """
    hist = np.asarray(history_atm_vols, float)
    hist = hist[np.isfinite(hist)]
    n = len(hist)

    if n < MIN_HISTORY:
        return {
            "signal": "iv_rank_mean_reversion",
            "status": "scaffold",
            "have": int(n), "need": MIN_HISTORY,
            "message": f"IV-rank signal inactive — {n}/{MIN_HISTORY} snapshots. "
                       f"Activates automatically as history accumulates.",
            "confidence": "INACTIVE (insufficient history)",
        }

    lo, hi = float(np.min(hist)), float(np.max(hist))
    iv_rank = (current_atm_vol - lo) / (hi - lo) if hi > lo else 0.0
    iv_rank = float(np.clip(iv_rank, 0.0, 1.0))
    iv_pctile = float(np.mean(hist <= current_atm_vol))

    # Confidence scales with how much history backs the rank
    depth = min(n / FULL_CONFIDENCE, 1.0)
    if n >= FULL_CONFIDENCE:
        conf = "SOLID"
    elif n >= 60:
        conf = "MODERATE (history maturing)"
    else:
        conf = "PROVISIONAL (thin history — rank jumpy, treat as indicative)"

    if iv_rank >= high:
        regime, implication, candidate = ("HIGH",
            "Vol elevated vs its trailing range; mean-reversion favors SELLING premium "
            "(rich options that decay as vol falls). Prefer DEFINED-RISK short premium.",
            "short_premium_defined_risk")
    elif iv_rank <= low:
        regime, implication, candidate = ("LOW",
            "Vol cheap vs its range; selling premium collects little and risks a vol "
            "spike. AVOID short premium; if directional, long options are relatively cheap.",
            "avoid_short_premium")
    else:
        regime, implication, candidate = ("NEUTRAL",
            "Vol mid-range; no strong mean-reversion edge from IV rank alone.",
            "none")

    return {
        "signal": "iv_rank_mean_reversion",
        "status": "active",
        "regime": regime,
        "iv_rank": iv_rank,
        "iv_percentile": iv_pctile,
        "current_vol": float(current_atm_vol),
        "hist_low": lo, "hist_high": hi, "n": int(n),
        "implication": implication,
        "candidate_structure": candidate,
        "confidence": conf,
        "confidence_depth": round(depth, 2),
        "falsification": "High IV-rank days should be followed by vol declines; if not, no edge.",
    }