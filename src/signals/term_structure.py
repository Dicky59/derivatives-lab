"""Term-structure regime signal.

Rule: classify ATM vol term structure as contango / backwardation / flat,
measure slope and front-back spread.

Economic rationale: contango (upward) is the calm/normal state — sell near-term
premium, favors calendars. Backwardation (inverted) is abnormal — the market
prices near-term event risk; warns against short-vol, may favor long-vol.

Falsification (tested in M6): if backwardation regimes do NOT precede larger
realized moves than contango, this signal has no edge.
"""
import numpy as np


def term_structure_signal(slices, flat_threshold=0.005):
    """
    slices: list of {"T": float, "theta": float}, sorted by T.
    flat_threshold: |slope per year| below this is treated as FLAT.

    Returns a signal dict: regime, slope, front/back vols, spread, rationale,
    a candidate structure hint, and a confidence tag.
    """
    Ts = np.array([s["T"] for s in slices])
    thetas = np.array([s["theta"] for s in slices])
    atm_vols = np.sqrt(thetas / Ts)

    front_vol, back_vol = float(atm_vols[0]), float(atm_vols[-1])
    slope = float(np.polyfit(Ts, atm_vols, 1)[0])   # per-year slope
    spread = back_vol - front_vol                    # >0 contango, <0 backwardation

    if slope > flat_threshold:
        regime = "CONTANGO"
        implication = ("Calm/normal. Near-term premium relatively rich vs long-dated; "
                       "favors selling near-term premium and calendar structures.")
        candidate = "calendar_or_short_near_premium"
    elif slope < -flat_threshold:
        regime = "BACKWARDATION"
        implication = ("ABNORMAL / stress. Near-term vol bid above long-dated — market "
                       "pricing imminent event risk. Warns AGAINST short-vol; may favor "
                       "long volatility or standing aside.")
        candidate = "avoid_short_vol_or_long_vol"
    else:
        regime = "FLAT"
        implication = ("Neither clear contango nor backwardation. No strong term-structure "
                       "edge; look to other signals (skew, IV rank).")
        candidate = "none"

    return {
        "signal": "term_structure_regime",
        "regime": regime,
        "slope_per_year": slope,
        "front_vol": front_vol,
        "back_vol": back_vol,
        "front_back_spread": spread,
        "implication": implication,
        "candidate_structure": candidate,
        "confidence": "UNVALIDATED (needs M6 backtest)",
        "falsification": ("Backwardation should precede larger realized moves than "
                          "contango; if not, signal has no edge."),
    }