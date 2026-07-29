"""Fit the full SVI surface for a derived snapshot: one slice per viable expiry,
term-structure / skew / 3D diagnostic plots, and a calendar-arbitrage scan."""
import argparse

import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 (registers 3D projection)

import config
from src.pricing.svi import svi_raw
from src.pricing.surface import fit_surface, scan_calendar_arbitrage


def find_latest_derived():
    files = sorted((config.DATA_DIR / "derived").glob("date=*/enriched_*.parquet"))
    if not files:
        raise FileNotFoundError(f"No derived snapshots found under {config.DATA_DIR / 'derived'}")
    return files[-1]


def plot_term_structure(surface):
    plt.figure(figsize=(9, 5))
    plt.plot(surface["T"] * 365, surface["atm_vol"], "o-", lw=2)
    plt.xlabel("T (days)")
    plt.ylabel("ATM implied vol")
    plt.title("ATM vol term structure")
    plt.grid(alpha=0.3)
    plt.savefig("term_structure.png", dpi=110, bbox_inches="tight")
    print("saved term_structure.png")


def plot_rho_term_structure(surface):
    plt.figure(figsize=(9, 5))
    plt.plot(surface["T"] * 365, surface["rho"], "o-", lw=2)
    plt.axhline(0, color="gray", ls="--")
    plt.xlabel("T (days)")
    plt.ylabel("SVI rho")
    plt.title("SVI rho vs expiry (skew tilt)")
    plt.grid(alpha=0.3)
    plt.savefig("rho_term_structure.png", dpi=110, bbox_inches="tight")
    print("saved rho_term_structure.png")


def plot_surface_3d(surface, path):
    import duckdb
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")

    k_grid = np.linspace(-0.15, 0.15, 61)
    T_vals = surface["T"].values
    K_mesh, T_mesh = np.meshgrid(k_grid, T_vals)
    IV_mesh = np.empty_like(K_mesh)
    for i, row in surface.reset_index(drop=True).iterrows():
        w = svi_raw(k_grid, row["a"], row["b"], row["rho"], row["m"], row["c"])
        IV_mesh[i, :] = np.sqrt(np.maximum(w, 1e-12) / row["T"])

    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_subplot(111, projection="3d")
    ax.plot_surface(K_mesh, T_mesh * 365, IV_mesh, cmap="viridis", alpha=0.7, linewidth=0)

    # Overlay observed iv_mid points per fitted expiry.
    for _, row in surface.iterrows():
        obs = con.execute(f"""
            SELECT strike, iv_mid, underlying_price
            FROM read_parquet('{path}')
            WHERE status='ok' AND iv_mid IS NOT NULL AND expiry = '{row['expiry']}'
        """).df()
        if obs.empty:
            continue
        k_obs = np.log(obs["strike"].values / row["F"])
        mask = (k_obs >= k_grid.min()) & (k_obs <= k_grid.max())
        ax.scatter(
            k_obs[mask], np.full(mask.sum(), row["T"] * 365), obs["iv_mid"].values[mask],
            color="k", s=8, depthshade=False,
        )

    ax.set_xlabel("log-forward-moneyness k")
    ax.set_ylabel("T (days)")
    ax.set_zlabel("implied vol")
    ax.set_title("SVI implied volatility surface")
    plt.savefig("surface_3d.png", dpi=110, bbox_inches="tight")
    print("saved surface_3d.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default=None, help="derived snapshot parquet path (default: latest)")
    args = parser.parse_args()

    path = args.file or str(find_latest_derived())
    print(f"Fitting surface from {path}\n")

    surface = fit_surface(path)

    plot_term_structure(surface)
    plot_rho_term_structure(surface)
    plot_surface_3d(surface, path)

    arb = scan_calendar_arbitrage(surface)
    if arb["n_violations"] == 0:
        print("\nCalendar-arbitrage scan: 0 violations")
    else:
        lo, hi = arb["violation_T_range"]
        print(
            f"\nCalendar-arbitrage scan: {arb['n_violations']} violations "
            f"(T range: [{lo*365:.1f}, {hi*365:.1f}] days)"
        )


if __name__ == "__main__":
    main()
