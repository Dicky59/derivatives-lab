"""Verify the risk engine on positions with known behaviour."""
import numpy as np
from src.risk.position import net_greeks, stress_grid, position_value

# Base market: SPY-like
S, r, q = 737.0, 0.039, 0.012

# --- TEST 1: single long call. Net greeks must equal bs_greeks * 100. ---
long_call = [{"type": "option", "right": "call", "strike": 740,
              "iv": 0.16, "T": 0.25, "qty": 1}]
g = net_greeks(long_call, S, r, q)
print("Long 1 call, net greeks (x100):")
for k, v in g.items():
    print(f"  {k:6s} {v:+.4f}")
print("  -> delta should be ~+ (long call), vega +, theta - (decay)")

# --- TEST 2: sign flips for a SHORT call ---
short_call = [{"type": "option", "right": "call", "strike": 740,
               "iv": 0.16, "T": 0.25, "qty": -1}]
gs = net_greeks(short_call, S, r, q)
print(f"\nShort 1 call: delta {gs['delta']:+.4f} (should be NEGATIVE, mirror of long)")
print(f"              vega  {gs['vega']:+.4f} (should be NEGATIVE — short vol)")

# --- TEST 3: stress grid for the long call. ---
grid, worst, base = stress_grid(long_call, S, r, q)
print(f"\nLong call base value: {base:.2f}")
print("Stress P&L grid (rows=vol shock, cols=spot shock):")
spot_shocks = (-0.05, -0.03, -0.01, 0.0, 0.01, 0.03, 0.05)
vol_shocks = (-0.05, -0.02, 0.0, 0.02, 0.05)
print("          " + "".join(f"{ss:+.0%}".rjust(9) for ss in spot_shocks))
for i, vs in enumerate(vol_shocks):
    row = "".join(f"{grid[i,j]:+9.0f}" for j in range(len(spot_shocks)))
    print(f"  vol{vs:+.0%} {row}")
print(f"\nWorst case: {worst['pnl']:+.0f} at spot {worst['spot_shock']:+.0%}, "
      f"vol {worst['vol_shock']:+.0%}")
print("  -> for a LONG call, worst case should be spot DOWN + vol DOWN")