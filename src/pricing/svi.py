"""Raw SVI smile fitting (Gatheral). Fits total variance w = t*sigma^2.

Raw SVI parametrization:
    w(k) = a + b * (rho*(k - m) + sqrt((k - m)^2 + c^2))
where k is log-forward-moneyness, w is total implied variance, and
(a, b, rho, m, c) are the five parameters with b >= 0, c > 0, |rho| <= 1.

Raw SVI is notoriously awkward to calibrate directly (coupled parameters,
a nasty objective surface). We use a global optimizer (differential_evolution)
with data-scaled bounds to find the right basin, then a derivative-free local
polish (Nelder-Mead) to nail the minimum.
"""
import numpy as np
from scipy.optimize import differential_evolution, minimize


def svi_raw(k, a, b, rho, m, c):
    """Raw SVI total-variance smile. k = log-forward-moneyness."""
    return a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + c ** 2))


def fit_svi(k, w, weights=None):
    """
    Fit raw SVI to observed total variances w at log-moneyness k.

    k       : array of log-forward-moneyness, ln(K/F)
    w       : array of total implied variances, iv_mid**2 * T
    weights : optional per-point weights (e.g. inverse of IV band width)

    Returns dict of the 5 params plus the fit RMSE (in total-variance space).
    """
    k = np.asarray(k, float)
    w = np.asarray(w, float)
    if weights is None:
        weights = np.ones_like(w)
    weights = np.asarray(weights, float)

    def objective(params):
        a, b, rho, m, c = params
        model = a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + c ** 2))
        return np.sum(weights * (model - w) ** 2)

    # Data-scaled bounds. w here is tiny (total variance at short T),
    # so b and c must be bounded to the scale of the data, NOT left to
    # roam up to O(1) where a degenerate flat-but-elevated fit hides.
    w_max = np.max(w)
    k_range = np.max(k) - np.min(k)
    bounds = [
        (0.0, w_max),                                   # a: floor of the smile
        (0.0, 2.0 * w_max / max(k_range, 1e-3)),        # b: slope, scaled to data
        (-0.999, 0.999),                                # rho: skew tilt
        (np.min(k), np.max(k)),                         # m: shift, within k range
        (1e-4, 0.5 * k_range),                          # c: curvature ~ scale of k
    ]

    # Global search: finds the right basin without a starting guess to snag on.
    res = differential_evolution(
        objective, bounds, seed=42, tol=1e-12,
        maxiter=1000, polish=True,
    )

    # Local polish: Nelder-Mead is derivative-free (won't choke on the sqrt)
    # and, seeded from DE's basin, walks to the actual minimum.
    res_polish = minimize(
        objective, res.x, method="Nelder-Mead",
        options={"xatol": 1e-10, "fatol": 1e-14, "maxiter": 5000},
    )
    if res_polish.fun < res.fun:
        res = res_polish

    a, b, rho, m, c = res.x
    model = svi_raw(k, a, b, rho, m, c)
    rmse = np.sqrt(np.mean((model - w) ** 2))
    return {"a": a, "b": b, "rho": rho, "m": m, "c": c, "rmse": rmse}