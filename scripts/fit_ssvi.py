"""Fit SSVI (shared rho, eta, gamma) across all slices of a derived snapshot,
with robust ATM-theta extraction and monotone-theta enforcement (SSVI's
calendar-arbitrage-free precondition)."""
import numpy as np
import duckdb
from sklearn.isotonic import IsotonicRegression

from src.pricing.ssvi import fit_ssvi_surface, ssvi_surface, phi_powerlaw
import config

PATH = "data/derived/date=2026-07-28/enriched_20260728T142857Z.parquet"
r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD
T_MIN, T_MAX = 7 / 365, 365 / 365
BAND_ABS_CAP = 0.15
MIN_POINTS = 15

con = duckdb.connect()
con.execute("SET TimeZone = 'UTC'")

expiries = con.execute(f"""
    SELECT DISTINCT expiry, T_used FROM read_parquet('{PATH}')
    WHERE status='ok' AND iv_mid IS NOT NULL
    ORDER BY expiry
""").df()

slices = []
for _, row in expiries.iterrows():
    T = row["T_used"]
    if not (T_MIN <= T <= T_MAX):
        continue
    df = con.execute(f"""
        SELECT strike, iv_mid, underlying_price, (iv_ask - iv_bid) AS band
        FROM read_parquet('{PATH}')
        WHERE status='ok' AND expiry = '{row["expiry"]}' AND iv_mid IS NOT NULL
    """).df()
    S = df["underlying_price"].iloc[0]
    df = df[(df["strike"] >= 0.85 * S) & (df["strike"] <= 1.15 * S)]
    thr = min(np.median(df["band"]) * 3.0, BAND_ABS_CAP)
    df = df[df["band"] <= thr]
    if len(df) < MIN_POINTS:
        continue
    F = S * np.exp((r - q) * T)
    k = np.log(df["strike"].values / F)
    w = (df["iv_mid"].values ** 2) * T

    # Robust ATM total variance: fit a local quadratic in k near the money and
    # read off k=0, instead of grabbing one noisy nearest-strike quote.
    near = np.abs(k) < 0.03
    if near.sum() >= 3:
        coeffs = np.polyfit(k[near], df["iv_mid"].values[near], 2)
        iv_atm = np.polyval(coeffs, 0.0)
    else:
        iv_atm = df["iv_mid"].values[np.argmin(np.abs(k))]
    theta = (iv_atm ** 2) * T

    slices.append({"theta": theta, "k": k, "w": w, "T": T, "expiry": row["expiry"]})

# Enforce monotone-increasing theta(T) — SSVI's calendar-arb-free precondition.
# Isotonic regression: smallest adjustment that makes theta non-decreasing in T.
slices.sort(key=lambda s: s["T"])
Ts = np.array([s["T"] for s in slices])
raw_theta = np.array([s["theta"] for s in slices])
iso = IsotonicRegression(increasing=True)
mono_theta = iso.fit_transform(Ts, raw_theta)
print("Theta monotonicity pass:")
any_adj = False
for s, th_new, th_old in zip(slices, mono_theta, raw_theta):
    if not np.isclose(th_new, th_old):
        print(f"  theta adjusted {str(s['expiry'])[:10]}: {th_old:.5f} -> {th_new:.5f}")
        any_adj = True
    s["theta"] = th_new
if not any_adj:
    print("  (theta already monotone — no adjustments)")

print(f"\nFitting SSVI jointly across {len(slices)} slices...")
fit = fit_ssvi_surface(slices)
print("\nShared SSVI parameters (ONE set for the whole surface):")
print(f"  rho   = {fit['rho']:+.4f}   (single skew — was zigzagging per slice)")
print(f"  eta   = {fit['eta']:.4f}")
print(f"  gamma = {fit['gamma']:.4f}")
print(f"  total RMSE (variance) = {fit['rmse']:.6e}")
print(f"  butterfly arbitrage-free: {fit['butterfly_ok']}")

print("\n  expiry        T     theta     n     slice_rmse")
for s in slices:
    model = ssvi_surface(s["k"], s["theta"], fit["rho"], fit["eta"], fit["gamma"])
    srmse = np.sqrt(np.mean((model - s["w"]) ** 2))
    print(f"  {str(s['expiry'])[:10]}  {s['T']:.3f}  {s['theta']:.5f}  "
          f"{len(s['k']):4d}   {srmse:.6e}")

# Step 4 — calendar arbitrage scan on the SSVI surface
k_grid = np.linspace(-0.15, 0.15, 61)
ssvi_slices = sorted(slices, key=lambda s: s["T"])
violations = 0
for a, b in zip(ssvi_slices[:-1], ssvi_slices[1:]):
    wa = ssvi_surface(k_grid, a["theta"], fit["rho"], fit["eta"], fit["gamma"])
    wb = ssvi_surface(k_grid, b["theta"], fit["rho"], fit["eta"], fit["gamma"])
    violations += int(np.sum(wb < wa))
print(f"\nCalendar-arbitrage scan (SSVI): {violations} violations "
      f"(was 17 with independent SVI)")