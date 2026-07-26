"""Implied volatility by robust root-finding (Brent's method)."""
import numpy as np
from scipy.optimize import brentq

from src.pricing.black_scholes import bs_price


def implied_vol(market_price, S, K, T, r, q=0.0, option_type="call",
                lo=1e-6, hi=5.0):
    """
    Back out the volatility that makes bs_price match market_price.

    Returns the implied vol, or None if it can't be solved (see notes).

    lo, hi : the volatility bracket to search within (0.0001% to 500%).
    """
    # --- Sanity gates: reject inputs that CAN'T have a valid IV ---
    if market_price is None or market_price <= 0 or T <= 0:
        return None

    # Intrinsic value = the option's value at zero volatility (floor).
    # A market price below intrinsic is an arbitrage / bad quote — no real IV exists.
    if option_type == "call":
        intrinsic = max(S * np.exp(-q * T) - K * np.exp(-r * T), 0.0)
    else:
        intrinsic = max(K * np.exp(-r * T) - S * np.exp(-q * T), 0.0)
    if market_price < intrinsic:
        return None

    # The function we want to zero out: model price minus market price.
    def objective(sigma):
        return bs_price(S, K, T, r, sigma, q, option_type) - market_price

    # brentq requires the objective to have OPPOSITE signs at lo and hi.
    # If it doesn't, the target price is outside what any vol in range can produce.
    try:
        if objective(lo) * objective(hi) > 0:
            return None
        return brentq(objective, lo, hi, xtol=1e-6, maxiter=100)
    except (ValueError, RuntimeError):
        return None

if __name__ == "__main__":
    S, K, T, r, q = 100, 100, 1.0, 0.05, 0.0
    true_sigma = 0.20

    # Forward: known vol -> price
    price = bs_price(S, K, T, r, true_sigma, q, "call")
    # Backward: that price -> recovered vol
    recovered = implied_vol(price, S, K, T, r, q, "call")

    print(f"true sigma:      {true_sigma:.6f}")
    print(f"recovered sigma: {recovered:.6f}")
    print(f"round-trip ok:   {np.isclose(true_sigma, recovered, atol=1e-6)}")

    # And a deliberately broken input: price below intrinsic -> should be None
    bad = implied_vol(0.01, S, K=50, T=T, r=r, q=q, option_type="call")
    print(f"below-intrinsic returns None: {bad is None}")