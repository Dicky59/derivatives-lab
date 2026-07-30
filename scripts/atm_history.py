"""Assemble and plot the front-tenor ATM vol history across all derived snapshots."""
import numpy as np
import matplotlib.pyplot as plt

from src.pricing.metrics import build_atm_history, iv_rank
import config

r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD
GLOB = "data/derived/date=*/enriched_*.parquet"

history = build_atm_history(GLOB, r, q)

print(f"Assembled {len(history)} snapshots:\n")
print("  timestamp (UTC)                 front_atm_vol   file")
for h in history:
    vol_str = f"{h['atm_vol']:.4f}" if h["atm_vol"] is not None else "   None"
    print(f"  {str(h['ts'])}   {vol_str}       {h['file']}")

# The series that will feed IV rank (drop any None)
vols = [h["atm_vol"] for h in history if h["atm_vol"] is not None]

print(f"\nUsable ATM-vol points: {len(vols)}")
if vols:
    print(f"  range: {min(vols):.4f} - {max(vols):.4f}")

# IV rank on the REAL assembled history now (still 'insufficient' until 20)
if vols:
    rank = iv_rank(vols[-1], history_atm_vols=vols)
    print(f"\nIV rank (latest vs assembled history):\n  {rank}")

# Plot the nascent history
if len(vols) >= 2:
    ts_list = [h["ts"] for h in history if h["atm_vol"] is not None]
    plt.figure(figsize=(9, 5))
    plt.plot(ts_list, vols, "o-", lw=1.5)
    plt.xlabel("snapshot time (UTC)")
    plt.ylabel("front-tenor ATM vol")
    plt.title(f"Front ATM vol history ({len(vols)} snapshots — the bank filling)")
    plt.grid(alpha=0.3)
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig("atm_history.png", dpi=110)
    print("\nsaved atm_history.png")