"""Compare sticky-strike vs sticky-moneyness stress on the same position."""
import glob
import numpy as np
import duckdb

from src.pricing.ssvi import fit_ssvi_surface
from src.risk.position import stress_grid, stress_grid_surface
import config

r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD

# --- Load latest derived snapshot and fit the surface (as fit_ssvi.py does) ---
PATH = sorted(glob.glob("data/derived/date=*/enriched_*.parquet"))[-1]
print(f"Surface from: {PATH}\n")
T_MIN, T_MAX, BAND_ABS_CAP, MIN_POINTS = 7/365, 365/365, 0.15, 15
con = duckdb.connect(); con.execute("SET TimeZone='UTC'")
expiries = con.execute(f"""SELECT DISTINCT expiry, T_used FROM read_parquet('{PATH}')
    WHERE status='ok' AND iv_mid IS NOT NULL ORDER BY expiry""").df()
slices, S = [], None
for _, row in expiries.iterrows():
    T = row["T_used"]
    if not (T_MIN <= T <= T_MAX): continue
    df = con.execute(f"""SELECT strike, iv_mid, underlying_price, (iv_ask-iv_bid) AS band
        FROM read_parquet('{PATH}') WHERE status='ok' AND expiry='{row["expiry"]}'
        AND iv_mid IS NOT NULL""").df()
    S = df["underlying_price"].iloc[0]
    df = df[(df["strike"]>=0.85*S)&(df["strike"]<=1.15*S)]
    thr = min(np.median(df["band"])*3.0, BAND_ABS_CAP); df = df[df["band"]<=thr]
    if len(df) < MIN_POINTS: continue
    F = S*np.exp((r-q)*T); k = np.log(df["strike"].values/F); w=(df["iv_mid"].values**2)*T
    near = np.abs(k)<0.03
    iv_atm = np.polyval(np.polyfit(k[near], df["iv_mid"].values[near],2),0.0) if near.sum()>=3 else df["iv_mid"].values[np.argmin(np.abs(k))]
    slices.append({"theta":(iv_atm**2)*T,"k":k,"w":w,"T":T})
slices.sort(key=lambda s:s["T"])
fit = fit_ssvi_surface(slices)
surface = {"rho":fit["rho"], "eta":fit["eta"], "gamma":fit["gamma"],
           "theta_by_T":[(s["T"], s["theta"]) for s in slices]}
print(f"Surface: rho={fit['rho']:+.3f} eta={fit['eta']:.3f} gamma={fit['gamma']:.3f}, "
      f"S={S:.2f}\n")

# --- Test position: a short strangle (sell OTM put + OTM call), the classic
#     short-vol trade whose risk sticky-moneyness reveals more honestly ---
# Use a ~45-day expiry near the middle of the surface.
T_test = 0.12
Kput, Kcall = round(S*0.95), round(S*1.05)
# grab approximate current IVs off the surface for the legs' base iv (sticky-strike needs it)
from src.risk.position import surface_iv
Ftest = S*np.exp((r-q)*T_test)
iv_put  = surface_iv(np.log(Kput/Ftest),  T_test, surface)
iv_call = surface_iv(np.log(Kcall/Ftest), T_test, surface)
position = [
    {"type":"option","right":"put","strike":Kput, "iv":iv_put, "T":T_test,"qty":-1},
    {"type":"option","right":"call","strike":Kcall,"iv":iv_call,"T":T_test,"qty":-1},
]
print(f"Short strangle: -1 put @{Kput} (iv {iv_put:.3f}), -1 call @{Kcall} (iv {iv_call:.3f})\n")

spot_shocks = (-0.05,-0.03,-0.01,0.0,0.01,0.03,0.05)
vol_shocks = (-0.05,-0.02,0.0,0.02,0.05)

def show(grid, worst, base, label):
    print(f"--- {label} (base {base:+.0f}) ---")
    print("          " + "".join(f"{ss:+.0%}".rjust(9) for ss in spot_shocks))
    for i,vs in enumerate(vol_shocks):
        print(f"  vol{vs:+.0%} " + "".join(f"{grid[i,j]:+9.0f}" for j in range(len(spot_shocks))))
    print(f"  worst: {worst['pnl']:+.0f} at spot {worst['spot_shock']:+.0%} vol {worst['vol_shock']:+.0%}\n")

g1,w1,b1 = stress_grid(position, S, r, q)
g2,w2,b2 = stress_grid_surface(position, S, r, q, surface)
show(g1, w1, b1, "STICKY-STRIKE (frozen IV)")
show(g2, w2, b2, "STICKY-MONEYNESS (surface-aware)")
print(f"Worst-case difference: sticky-strike {w1['pnl']:+.0f} vs surface {w2['pnl']:+.0f}")
print(f"  -> surface-aware worst case should be MORE NEGATIVE (captures smile moving)")