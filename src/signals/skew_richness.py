"""Skew-richness signal (cross-sectional / Anchor A).

Rule: fit a smooth skew term structure (skew vs T), compute each expiry's
residual from the fit, flag expiries whose skew deviates significantly (rich =
steeper than trend, cheap = flatter than trend).

Economic rationale: skew term structures are usually smooth (coherent risk
pricing across maturities). A local kink is often a temporary supply/demand
dislocation in one expiry that mean-reverts toward the smooth curve.

Falsification (M6): flagged-rich expiries should see skew FALL toward the curve
subsequently; if anomalies don't revert, no edge.

Anchor B (skew vs realized downside) needs return history — scaffolded, not live.
"""
import numpy as np

from src.pricing.ssvi import ssvi_surface


def _atm_skew_slope(T, theta, rho, eta, gamma, h=1e-4):
    """d sigma / d k at k=0 for one slice, from the SSVI surface."""
    def sig(k):
        w = ssvi_surface(np.array([k]), theta, rho, eta, gamma)[0]
        return np.sqrt(max(w, 1e-12) / T)
    return (sig(h) - sig(-h)) / (2 * h)


def skew_richness_signal(slices, surface, z_threshold=2.0):
    """
    slices: list of {"T","theta"} sorted by T.
    surface: {"rho","eta","gamma", ...} (shared params).
    z_threshold: residual z-score beyond which an expiry is flagged.

    Returns signal dict: per-expiry skew, the smooth fit, residuals, and any
    flagged (rich/cheap) expiries with a rationale + confidence + falsification.
    """
    rho, eta, gamma = surface["rho"], surface["eta"], surface["gamma"]
    Ts = np.array([s["T"] for s in slices])
    skews = np.array([_atm_skew_slope(s["T"], s["theta"], rho, eta, gamma)
                      for s in slices])

    # Fit smooth skew term structure. Skew ~ a/sqrt(T) + b is a common shape;
    # fit skew vs 1/sqrt(T) linearly (robust, few params).
    x = 1.0 / np.sqrt(Ts)
    coeffs = np.polyfit(x, skews, 1)          # skew ≈ coeffs[0]/sqrt(T) + coeffs[1]
    fitted = np.polyval(coeffs, x)
    resid = skews - fitted
    resid_std = np.std(resid) if len(resid) > 2 else np.inf

    flags = []
    if np.isfinite(resid_std) and resid_std > 1e-9:
        z = resid / resid_std
        for i, s in enumerate(slices):
            if abs(z[i]) >= z_threshold:
                flags.append({
                    "T": float(s["T"]),
                    "skew": float(skews[i]),
                    "fitted_skew": float(fitted[i]),
                    "residual": float(resid[i]),
                    "z": float(z[i]),
                    # steeper-than-trend skew = MORE negative slope = "rich" downside
                    "kind": "RICH (steeper than trend)" if resid[i] < 0
                            else "CHEAP (flatter than trend)",
                })

    return {
        "signal": "skew_richness_cross_sectional",
        "n_expiries": len(slices),
        "skew_by_T": list(zip(Ts.tolist(), skews.tolist())),
        "fit_coeffs": coeffs.tolist(),
        "residual_std": float(resid_std) if np.isfinite(resid_std) else None,
        "flags": flags,
        "summary": (f"{len(flags)} expiry(ies) flagged as skew anomalies"
                    if flags else
                    "No skew anomalies — skew is in line with its term structure."),
        "confidence": "UNVALIDATED (needs M6 backtest)",
        "falsification": ("Flagged-rich expiries should see skew revert toward the "
                          "smooth curve; if not, no edge."),
        "anchor_B_note": ("Skew-vs-realized-downside (is fear overpriced?) needs return "
                          "history — scaffolded, live in ~3 weeks."),
    }