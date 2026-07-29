"""Surface SVI (SSVI) — Gatheral-Jacquier. Couples all expiries through a
shared skew rho and a curvature function phi(theta), anchored to the ATM
total-variance term structure theta.

For a single slice with ATM total variance theta:
    w(k, theta) = (theta/2) * [1 + rho*phi*k + sqrt((phi*k + rho)^2 + (1 - rho^2))]

By construction w(0, theta) = theta, so every slice passes through its ATM
point exactly. This anchoring is what prevents the free-wandering that raw
per-slice SVI suffered from.
"""
import numpy as np
from scipy.optimize import differential_evolution, minimize


def ssvi_raw(k, theta, rho, phi):
    """
    SSVI total-variance smile for a single slice.

    k     : log-forward-moneyness (scalar or array)
    theta : ATM total variance for this slice (theta = sigma_atm^2 * T), > 0
    rho   : shared skew parameter, |rho| < 1
    phi   : curvature for this slice (function of theta in the full surface), > 0

    Returns total variance w(k).
    """
    k = np.asarray(k, float)
    return 0.5 * theta * (
        1.0 + rho * phi * k + np.sqrt((phi * k + rho) ** 2 + (1.0 - rho ** 2))
    )

def phi_powerlaw(theta, eta, gamma):
    """Curvature function phi(theta) = eta / theta^gamma (Gatheral power-law)."""
    return eta / np.power(theta, gamma)


def ssvi_surface(k, theta, rho, eta, gamma):
    """SSVI total variance using the power-law phi. theta is per-slice ATM total var."""
    phi = phi_powerlaw(theta, eta, gamma)
    return ssvi_raw(k, theta, rho, phi)


def butterfly_ok(theta, rho, eta, gamma):
    """
    Gatheral-Jacquier butterfly no-arbitrage sufficient condition:
        theta * phi * (1 + |rho|) < 4     (and a second: theta*phi*(1+|rho|) <= 4/(1+|rho|))
    Returns True if the tighter condition holds for all supplied thetas.
    """
    phi = phi_powerlaw(np.asarray(theta, float), eta, gamma)
    cond = theta * phi * (1.0 + abs(rho))
    return np.all(cond < 4.0) and np.all(theta * phi * (1.0 + abs(rho)) <= 4.0 / (1.0 + abs(rho)))


def fit_ssvi_surface(slices):
    """
    Jointly fit shared (rho, eta, gamma) across all slices.

    slices: list of dicts, each {"theta": float, "k": array, "w": array}
            theta is the FIXED ATM total variance anchor for that slice;
            k, w are that slice's observed log-moneyness and total variances.

    Returns dict {rho, eta, gamma, rmse, butterfly_ok}.
    """
    thetas = np.array([s["theta"] for s in slices])

    def objective(params):
        rho, eta, gamma = params
        # Penalize any parameters that violate the butterfly condition — keeps
        # the optimizer inside the arbitrage-free region.
        if not butterfly_ok(thetas, rho, eta, gamma):
            return 1e6
        total = 0.0
        for s in slices:
            model = ssvi_surface(s["k"], s["theta"], rho, eta, gamma)
            total += np.sum((model - s["w"]) ** 2)
        return total

    bounds = [
        (-0.999, 0.999),   # rho: shared skew
        (1e-4, 10.0),      # eta: curvature scale
        (0.0, 1.0),        # gamma: curvature decay (0.5 is Gatheral's common value)
    ]
    res = differential_evolution(objective, bounds, seed=42, tol=1e-12, maxiter=500)
    res = minimize(objective, res.x, method="Nelder-Mead",
                   options={"xatol": 1e-10, "fatol": 1e-14, "maxiter": 5000})

    rho, eta, gamma = res.x
    # Total RMSE across all points
    n = sum(len(s["k"]) for s in slices)
    rmse = np.sqrt(res.fun / n) if res.fun < 1e5 else float("inf")
    return {
        "rho": rho, "eta": eta, "gamma": gamma, "rmse": rmse,
        "butterfly_ok": bool(butterfly_ok(thetas, rho, eta, gamma)),
    }

if __name__ == "__main__":
    theta, rho, phi = 0.04, -0.3, 2.0   # e.g. atm total var 0.04, skew -0.3

    # CHECK 1 — ATM anchor: w(0) must equal theta exactly, for ANY rho/phi.
    w0 = ssvi_raw(0.0, theta, rho, phi)
    print(f"w(0)   = {w0:.10f}   theta = {theta:.10f}   match: {np.isclose(w0, theta)}")

    # Confirm the anchor holds regardless of rho and phi (try a few)
    for rr in (-0.8, 0.0, 0.5):
        for pp in (0.5, 2.0, 5.0):
            assert np.isclose(ssvi_raw(0.0, theta, rr, pp), theta), (rr, pp)
    print("ATM anchor holds for all tested (rho, phi): OK")

    # CHECK 2 — symmetry: with rho = 0, the smile must be symmetric in k.
    ks = np.array([-0.1, -0.05, 0.05, 0.1])
    w_sym = ssvi_raw(ks, theta, 0.0, phi)
    left, right = w_sym[:2][::-1], w_sym[2:]   # mirror the negatives
    print(f"rho=0 symmetry: {np.allclose(left, right)}")

    # CHECK 3 — positivity: total variance must be > 0 across a wide k range.
    kk = np.linspace(-0.5, 0.5, 101)
    w_all = ssvi_raw(kk, theta, rho, phi)
    print(f"all w > 0 over k in [-0.5, 0.5]: {np.all(w_all > 0)}")