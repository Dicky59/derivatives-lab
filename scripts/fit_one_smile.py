"""Fit SVI to a single expiry from a derived snapshot, print params + fit quality,
and save a plot of the fitted smile against observed IVs."""
import numpy as np
import duckdb
import matplotlib.pyplot as plt

from src.pricing.svi import svi_raw, fit_svi
import config

PATH = "data/derived/date=2026-07-28/enriched_20260728T142857Z.parquet"
r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD

con = duckdb.connect()
con.execute("SET TimeZone = 'UTC'")

# Pick an expiry ~20+ days out with a full chain (NOT the nearest — expiry-day
# IV is garbage). First future expiry beyond 20 days.
nearest = con.execute(f"""
    SELECT expiry FROM read_parquet('{PATH}')
    WHERE status='ok' AND expiry > CURRENT_DATE + INTERVAL 20 DAY
    GROUP BY expiry
    ORDER BY expiry
    LIMIT 1
""").fetchone()[0]

# Near-money only — wings on the indicative feed are noisy.
df = con.execute(f"""
    SELECT strike, iv_mid, underlying_price, T_used,
           (iv_ask - iv_bid) AS band
    FROM read_parquet('{PATH}')
    WHERE status='ok' AND expiry = '{nearest}'
      AND iv_mid IS NOT NULL
      AND strike BETWEEN {0.92*737} AND {1.08*737}
    ORDER BY strike
""").df()

S = df["underlying_price"].iloc[0]
T = df["T_used"].iloc[0]
F = S * np.exp((r - q) * T)                  # forward approximation

k = np.log(df["strike"].values / F)          # log-forward-moneyness
w = (df["iv_mid"].values ** 2) * T           # total variance

# --- Weighting: DIAGNOSTIC equal weights to check for weighting-induced bias ---
# band = df["band"].values
# weights = 1.0 / np.maximum(band, 1e-4)     # quote-quality weighting (original)
weights = np.ones_like(w)                     # equal weighting — diagnostic

print(f"Expiry {nearest} | S={S:.2f} F={F:.2f} T={T:.4f} | {len(df)} points")

fit = fit_svi(k, w, weights)
print("\nSVI parameters:")
for key in ["a", "b", "rho", "m", "c"]:
    print(f"  {key:4s} = {fit[key]:+.6f}")
print(f"  rmse (total-var) = {fit['rmse']:.6e}")

# Convert back to IV space and show fit at each point
print("\n  strike      k     iv_obs   iv_svi   diff")
w_fit = svi_raw(k, fit["a"], fit["b"], fit["rho"], fit["m"], fit["c"])
iv_fit = np.sqrt(np.maximum(w_fit, 1e-12) / T)
for i in range(0, len(df), max(1, len(df) // 15)):  # ~15 sample rows
    iv_obs = df["iv_mid"].values[i]
    print(f"  {df['strike'].values[i]:7.1f} {k[i]:+.4f} "
          f"{iv_obs:.4f}  {iv_fit[i]:.4f}  {iv_obs-iv_fit[i]:+.4f}")

# --- Plot: fitted curve vs observed points ---
kk = np.linspace(k.min(), k.max(), 200)
ww = svi_raw(kk, fit["a"], fit["b"], fit["rho"], fit["m"], fit["c"])
iv_curve = np.sqrt(np.maximum(ww, 1e-12) / T)

plt.figure(figsize=(9, 5))
plt.scatter(k, df["iv_mid"].values, s=12, alpha=0.5, label="observed iv_mid")
plt.plot(kk, iv_curve, "r-", lw=2, label="SVI fit")
plt.xlabel("log-forward-moneyness k")
plt.ylabel("implied vol")
plt.title(f"SVI smile fit — expiry {nearest}, T={T:.4f}")
plt.legend()
plt.grid(alpha=0.3)
plt.savefig("smile_fit.png", dpi=110, bbox_inches="tight")
print("saved smile_fit.png")