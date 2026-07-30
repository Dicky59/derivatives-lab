"""Position risk: net greeks and a spot x vol P&L stress grid.

A position is a list of legs. Option legs reprice through the Black-Scholes
engine; net greeks are the signed-quantity-weighted sum. Contract multiplier
is 100 (one option controls 100 shares) — applied to every option leg.

Sticky-strike stress (M4.1): under a spot/vol shock, each option keeps its
current IV. Sticky-moneyness (surface-aware) comes in M4.2.
"""
import numpy as np

from src.pricing.black_scholes import bs_price, bs_greeks

MULT = 100  # option contract multiplier


def _option_T(expiry, snapshot_date):
    """Year-fraction to expiry, act/365."""
    return (np.datetime64(expiry) - np.datetime64(snapshot_date)).astype(int) / 365.0


def price_leg(leg, S, r, q, spot_shock=0.0, vol_shock=0.0):
    """
    Price a single leg (per-unit, before qty/multiplier), given shocks.
    leg option: {"type":"option","right","strike","iv","T","qty"}
    leg stock:  {"type":"underlying","qty"}
    spot_shock: fractional (e.g. -0.05 for -5%). vol_shock: absolute vol points.
    """
    S_shocked = S * (1.0 + spot_shock)
    if leg["type"] == "underlying":
        return S_shocked                      # one share worth S_shocked
    sigma = leg["iv"] + vol_shock
    sigma = max(sigma, 1e-6)                  # vol can't go <= 0
    return bs_price(S_shocked, leg["strike"], leg["T"], r, sigma, q, leg["right"])


def net_greeks(position, S, r, q):
    """Signed-quantity-weighted, multiplier-scaled net greeks of the position."""
    tot = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    for leg in position:
        qty = leg["qty"]
        if leg["type"] == "underlying":
            tot["delta"] += qty              # 1 share = 1 delta, no multiplier
            continue
        g = bs_greeks(S, leg["strike"], leg["T"], r, leg["iv"], q, leg["right"])
        for key in tot:
            tot[key] += qty * MULT * g[key]  # options: x100 x qty
    return tot


def position_value(position, S, r, q, spot_shock=0.0, vol_shock=0.0):
    """Total position value under a given shock (signed qty, multiplier applied)."""
    val = 0.0
    for leg in position:
        px = price_leg(leg, S, r, q, spot_shock, vol_shock)
        mult = 1 if leg["type"] == "underlying" else MULT
        val += leg["qty"] * mult * px
    return val


def stress_grid(position, S, r, q,
                spot_shocks=(-0.05, -0.03, -0.01, 0.0, 0.01, 0.03, 0.05),
                vol_shocks=(-0.05, -0.02, 0.0, 0.02, 0.05)):
    """
    P&L grid: for each (spot_shock, vol_shock), P&L = value(shocked) - value(base).
    Returns (grid array [len(vol) x len(spot)], worst_case dict).
    """
    base = position_value(position, S, r, q, 0.0, 0.0)
    grid = np.zeros((len(vol_shocks), len(spot_shocks)))
    worst = {"pnl": np.inf}
    for i, vs in enumerate(vol_shocks):
        for j, ss in enumerate(spot_shocks):
            pnl = position_value(position, S, r, q, ss, vs) - base
            grid[i, j] = pnl
            if pnl < worst["pnl"]:
                worst = {"pnl": pnl, "spot_shock": ss, "vol_shock": vs}
    return grid, worst, base