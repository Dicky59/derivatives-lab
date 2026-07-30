"""M4.3: verify the risk engine on real option structures.
Each structure has a KNOWN risk character; we confirm the stress grid matches it."""
import glob
import numpy as np
import duckdb

from src.pricing.ssvi import fit_ssvi_surface
from src.risk.position import (stress_grid_surface, stress_grid, surface_iv,
                               net_greeks, fitted_k_range)
import config

r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD


def load_surface():
    PATH = sorted(glob.glob("data/derived/date=*/enriched_*.parquet"))[-1]
    T_MIN, T_MAX, CAP, MINP = 7/365, 365/365, 0.15, 15
    con = duckdb.connect(); con.execute("SET TimeZone='UTC'")
    exp = con.execute(f"""SELECT DISTINCT expiry,T_used FROM read_parquet('{PATH}')
        WHERE status='ok' AND iv_mid IS NOT NULL ORDER BY expiry""").df()
    slices, S = [], None
    for _, row in exp.iterrows():
        T = row["T_used"]
        if not (T_MIN <= T <= T_MAX): continue
        df = con.execute(f"""SELECT strike,iv_mid,underlying_price,(iv_ask-iv_bid) AS band
            FROM read_parquet('{PATH}') WHERE status='ok' AND expiry='{row["expiry"]}'
            AND iv_mid IS NOT NULL""").df()
        S = df["underlying_price"].iloc[0]
        df = df[(df["strike"]>=0.85*S)&(df["strike"]<=1.15*S)]
        thr = min(np.median(df["band"])*3.0, CAP); df = df[df["band"]<=thr]
        if len(df) < MINP: continue
        F = S*np.exp((r-q)*T); k=np.log(df["strike"].values/F); w=(df["iv_mid"].values**2)*T
        near=np.abs(k)<0.03
        iv=np.polyval(np.polyfit(k[near],df["iv_mid"].values[near],2),0.0) if near.sum()>=3 else df["iv_mid"].values[np.argmin(np.abs(k))]
        slices.append({"theta":(iv**2)*T,"k":k,"w":w,"T":T})
    slices.sort(key=lambda s:s["T"])
    fit = fit_ssvi_surface(slices)
    surface = {"rho": fit["rho"], "eta": fit["eta"], "gamma": fit["gamma"],
               "theta_by_T": [(s["T"], s["theta"]) for s in slices],
               "k_range": fitted_k_range(slices)}
    return surface, S, [s["T"] for s in slices]


def leg(right, strike, T, qty, surface, S):
    F = S*np.exp((r-q)*T)
    iv = surface_iv(np.log(strike/F), T, surface)
    return {"type":"option","right":right,"strike":strike,"iv":iv,"T":T,"qty":qty}


SPOT = (-0.15, -0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10, 0.15)
VOL = (-0.05,-0.02,0.0,0.02,0.05)


def show(name, position, surface, S, expect):
    grid, worst, base, extrap = stress_grid_surface(position, S, r, q, surface)
    g = net_greeks(position, S, r, q)
    print(f"\n===== {name} =====")
    print(f"expect: {expect}")
    print(f"net greeks: delta {g['delta']:+.1f}  vega {g['vega']:+.1f}  theta {g['theta']:+.1f}")
    print(f"base value: {base:+.0f}")
    print("          " + "".join(f"{ss:+.0%}".rjust(8) for ss in SPOT))
    for i, vs in enumerate(VOL):
        print(f"  vol{vs:+.0%} " + "".join(f"{grid[i,j]:+8.0f}" for j in range(len(SPOT))))
    print(f"  range: worst {np.min(grid):+.0f}  best {np.max(grid):+.0f}")
    if extrap:
        print("  ! WARNING: some cells priced with EXTRAPOLATED IV "
              "(legs outside fitted moneyness range) - treat extreme shocks as approximate")


surface, S, Ts = load_surface()
print(f"Surface loaded: S={S:.2f}, expiries T={[round(t,3) for t in Ts]}")
T1 = min(Ts, key=lambda t: abs(t-0.12))   # ~45d expiry
T2 = min(Ts, key=lambda t: abs(t-0.35))   # ~far expiry for the calendar

# 1) BULL CALL SPREAD: long lower call, short higher call. DEFINED RISK both ways.
Klo, Khi = round(S*1.00), round(S*1.05)
bull_call = [leg("call",Klo,T1,+1,surface,S), leg("call",Khi,T1,-1,surface,S)]
show("BULL CALL SPREAD (long %d / short %d call)"%(Klo,Khi), bull_call, surface, S,
     "capped profit AND capped loss - both bounded, no runaway cell")

# 2) IRON CONDOR: short strangle + long protective wings. CAPPED loss.
Kp_s, Kc_s = round(S*0.95), round(S*1.05)   # short inner
Kp_l, Kc_l = round(S*0.90), round(S*1.10)   # long outer wings
condor = [leg("put",Kp_s,T1,-1,surface,S), leg("call",Kc_s,T1,-1,surface,S),
          leg("put",Kp_l,T1,+1,surface,S), leg("call",Kc_l,T1,+1,surface,S)]
show("IRON CONDOR (short %d/%d, long wings %d/%d)"%(Kp_s,Kc_s,Kp_l,Kc_l), condor, surface, S,
     "loss CAPPED by long wings - worst case far smaller than a naked strangle's -2084")

# 3) CALENDAR SPREAD: short near, long far, same strike. VEGA / TERM-STRUCTURE risk.
Katm = round(S)
calendar = [leg("call",Katm,T1,-1,surface,S), leg("call",Katm,T2,+1,surface,S)]
show("CALENDAR SPREAD (short %.2fy / long %.2fy call @%d)"%(T1,T2,Katm), calendar, surface, S,
     "net LONG vega (long the far leg); profits from vol UP, hurt by big spot moves")

# Wider shocks to reach the condor's protective wings, now +/-15% via default
wide_spot = (-0.15,-0.12,-0.08,-0.05,0.0,0.05,0.08,0.12,0.15)
grid, worst, base, extrap = stress_grid_surface(condor, S, r, q, surface,
                                                spot_shocks=wide_spot, vol_shocks=VOL)
print("\n=== IRON CONDOR, WIDER spot ===")
print("          " + "".join(f"{ss:+.0%}".rjust(8) for ss in wide_spot))
for i,vs in enumerate(VOL):
    print(f"  vol{vs:+.0%} " + "".join(f"{grid[i,j]:+8.0f}" for j in range(len(wide_spot))))
print(f"  worst {np.min(grid):+.0f}  best {np.max(grid):+.0f}")
if extrap:
    print("  ! WARNING: extrapolated IV in some cells - extreme shocks approximate")

# ===== LESSON 2 DIAGNOSTIC: sticky-strike vs sticky-moneyness at wide shocks =====
wide_spot = (-0.12, -0.10, -0.08, -0.05, 0.0, 0.05, 0.08, 0.10, 0.12)

print("\n\n########## LESSON 2: does the condor loss CAP at the wings? ##########")

# Sticky-strike (frozen IV) - textbook defined-risk should flatten past the wings
gk, _, _ = stress_grid(condor, S, r, q, spot_shocks=wide_spot, vol_shocks=(0.0,))
print("\n--- STICKY-STRIKE (frozen IV), vol+0% row ---")
print("        " + "".join(f"{ss:+.0%}".rjust(8) for ss in wide_spot))
print("  pnl   " + "".join(f"{gk[0,j]:+8.0f}" for j in range(len(wide_spot))))

# Sticky-moneyness (surface) - same row for direct comparison (4-value unpack)
gm, _, _, _ = stress_grid_surface(condor, S, r, q, surface,
                                  spot_shocks=wide_spot, vol_shocks=(0.0,))
print("\n--- STICKY-MONEYNESS (surface), vol+0% row ---")
print("        " + "".join(f"{ss:+.0%}".rjust(8) for ss in wide_spot))
print("  pnl   " + "".join(f"{gm[0,j]:+8.0f}" for j in range(len(wide_spot))))

# Where does each leg sit on the surface at -12%? Are we past the fitted range?
print("\n--- Leg moneyness at spot -12% (fitted surface covers ~ +/-0.16 in k) ---")
S_shock = S * (1 - 0.12)
for lg in condor:
    F = S_shock * np.exp((r - q) * lg["T"])
    k = np.log(lg["strike"] / F)
    iv = surface_iv(k, lg["T"], surface)
    flag = "  <-- OUTSIDE fitted range" if abs(k) > 0.16 else ""
    print(f"  {lg['right']:4s} K={lg['strike']} qty{lg['qty']:+d}: k={k:+.3f}  iv={iv:.3f}{flag}")