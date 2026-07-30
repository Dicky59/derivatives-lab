"""Compute tradeable metrics from the fitted SSVI surface of the latest derived snapshot."""
import glob
import numpy as np
import duckdb

from src.pricing.ssvi import fit_ssvi_surface
from src.pricing.metrics import term_structure_metrics, skew_metrics, iv_rank
import config

# --- Use the most recent derived snapshot, not a hardcoded one ---
_derived = sorted(glob.glob("data/derived/date=*/enriched_*.parquet"))
if not _derived:
    raise SystemExit("No derived snapshots found under data/derived/")
PATH = _derived[-1]
print(f"Analyzing latest surface: {PATH}\n")

r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD
T_MIN, T_MAX = 7/365, 365/365
BAND_ABS_CAP, MIN_POINTS = 0.15, 15

con = duckdb.connect()
con.execute("SET TimeZone='UTC'")

expiries = con.execute(f"""
    SELECT DISTINCT expiry, T_used FROM read_parquet('{PATH}')
    WHERE status='ok' AND iv_mid IS NOT NULL ORDER BY expiry
""").df()

slices = []
for _, row in expiries.iterrows():
    T = row["T_used"]
    if not (T_MIN <= T <= T_MAX):
        continue
    df = con.execute(f"""
        SELECT strike, iv_mid, underlying_price, (iv_ask-iv_bid) AS band
        FROM read_parquet('{PATH}')
        WHERE status='ok' AND expiry='{row["expiry"]}' AND iv_mid IS NOT NULL
    """).df()
    S = df["underlying_price"].iloc[0]
    df = df[(df["strike"] >= 0.85*S) & (df["strike"] <= 1.15*S)]
    thr = min(np.median(df["band"])*3.0, BAND_ABS_CAP)
    df = df[df["band"] <= thr]
    if len(df) < MIN_POINTS:
        continue
    F = S*np.exp((r-q)*T)
    k = np.log(df["strike"].values/F)
    w = (df["iv_mid"].values**2)*T
    near = np.abs(k) < 0.03
    if near.sum() >= 3:
        iv_atm = np.polyval(np.polyfit(k[near], df["iv_mid"].values[near], 2), 0.0)
    else:
        iv_atm = df["iv_mid"].values[np.argmin(np.abs(k))]
    slices.append({"theta": (iv_atm**2)*T, "k": k, "w": w, "T": T, "expiry": row["expiry"]})

slices.sort(key=lambda s: s["T"])
fit = fit_ssvi_surface(slices)

# --- Metrics ---
print("=== TERM STRUCTURE ===")
ts = term_structure_metrics(slices)
print(f"  front ATM vol: {ts['front_atm_vol']:.4f}  back ATM vol: {ts['back_atm_vol']:.4f}")
print(f"  slope/yr: {ts['slope_per_year']:+.4f}   regime: {ts['regime'].upper()}")

print("\n=== SKEW (per expiry) ===")
print("  T       atm_skew   rr_proxy   put_wing  call_wing")
for m in skew_metrics(fit, slices):
    print(f"  {m['T']:.3f}  {m['atm_skew_slope']:+.4f}   "
          f"{m['rr_proxy_10pct']:+.4f}   {m['put_wing_vol']:.4f}   {m['call_wing_vol']:.4f}")

print("\n=== IV RANK (scaffold) ===")
# History will come from past snapshots later; for now, just today's front vol.
rank = iv_rank(ts["front_atm_vol"], history_atm_vols=[ts["front_atm_vol"]])
print(f"  {rank}")