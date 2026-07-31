"""Run signals on the latest surface; attach M4 risk to any candidate structure."""
import glob
import numpy as np
import duckdb

from src.pricing.ssvi import fit_ssvi_surface
from src.risk.position import (stress_grid_surface, surface_iv, net_greeks,
                               fitted_k_range)
from src.signals.term_structure import term_structure_signal
from src.signals.skew_richness import skew_richness_signal
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
    surface = {"rho":fit["rho"],"eta":fit["eta"],"gamma":fit["gamma"],
               "theta_by_T":[(s["T"],s["theta"]) for s in slices],
               "k_range": fitted_k_range(slices)}
    return surface, S, slices


def leg(right, strike, T, qty, surface, S):
    F = S*np.exp((r-q)*T)
    iv = surface_iv(np.log(strike/F), T, surface)
    return {"type":"option","right":right,"strike":strike,"iv":iv,"T":T,"qty":qty}


surface, S, slices = load_surface()
Ts = [s["T"] for s in slices]

print("="*66)
print(f"SIGNAL RUN  |  S={S:.2f}  |  {len(slices)} expiries")
print("="*66)

# --- Term-structure regime signal ---
sig = term_structure_signal(slices)
print(f"\n[{sig['signal']}]  ->  {sig['regime']}")
print(f"  slope/yr: {sig['slope_per_year']:+.4f}   front {sig['front_vol']:.4f} "
      f"back {sig['back_vol']:.4f}   spread {sig['front_back_spread']:+.4f}")
print(f"  implication: {sig['implication']}")
print(f"  confidence:  {sig['confidence']}")
print(f"  falsifies if: {sig['falsification']}")

# --- Skew-richness signal ---
sk = skew_richness_signal(slices, surface)
print(f"\n[{sk['signal']}]")
print(f"  {sk['summary']}")
print(f"  skew term structure (T, skew_slope):")
for T, skew in sk["skew_by_T"]:
    print(f"    T={T:.3f}  skew={skew:+.3f}")
if sk["flags"]:
    print(f"  FLAGGED anomalies (|z| >= 2):")
    for f in sk["flags"]:
        print(f"    T={f['T']:.3f}: {f['kind']}  skew={f['skew']:+.3f} "
              f"vs fitted {f['fitted_skew']:+.3f}  (z={f['z']:+.2f})")
else:
    print(f"  (skew term structure is smooth — no dislocations)")
print(f"  confidence:  {sk['confidence']}")
print(f"  falsifies if: {sk['falsification']}")
print(f"  note: {sk['anchor_B_note']}")

# --- Candidate structure + M4 risk, if the signal suggests one ---
if sig["candidate_structure"] == "calendar_or_short_near_premium":
    T1 = min(Ts, key=lambda t: abs(t-0.12))
    T2 = min(Ts, key=lambda t: abs(t-0.35))
    Katm = round(S)
    calendar = [leg("call",Katm,T1,-1,surface,S), leg("call",Katm,T2,+1,surface,S)]
    grid, worst, base, extrap = stress_grid_surface(calendar, S, r, q, surface)
    g = net_greeks(calendar, S, r, q)
    print(f"\n  CANDIDATE STRUCTURE (unvalidated): calendar, short {T1:.2f}y / long {T2:.2f}y call @{Katm}")
    print(f"    net greeks: delta {g['delta']:+.1f}  vega {g['vega']:+.1f}  theta {g['theta']:+.1f}")
    print(f"    base cost/credit: {base:+.0f}")
    print(f"    stress worst case: {worst['pnl']:+.0f} at spot {worst['spot_shock']:+.0%} vol {worst['vol_shock']:+.0%}")
    if extrap:
        print(f"    ! some stress cells extrapolated — extreme shocks approximate")
    print(f"    -> This is a CANDIDATE only. Do not trade until M6 validates the signal.")
elif sig["candidate_structure"] == "avoid_short_vol_or_long_vol":
    print(f"\n  CANDIDATE POSTURE: avoid short-vol premium selling; term structure warns of near-term risk.")
else:
    print(f"\n  No candidate structure — term structure gives no clear edge today.")