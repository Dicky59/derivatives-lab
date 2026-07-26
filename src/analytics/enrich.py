"""M2b: derived-analytics module.

Applies the M2 Black-Scholes engine (src/pricing) to a real M0 option-chain snapshot,
backing out implied vol from bid/ask/mid and computing our own greeks. Writes an
enriched, recomputable derived table alongside (never modifying) the raw snapshot.

Known approximation: r and q are flat, hardcoded constants (config.RISK_FREE_RATE,
config.DIVIDEND_YIELD) rather than a real rate/dividend curve. The Alpaca cross-check
(see scripts/verify_enrich_checks.py or the verification steps in the M2b plan) is how
the cost of that approximation gets measured against Alpaca's own greeks/IV.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config

from src.pricing.black_scholes import bs_greeks
from src.pricing.implied_vol import implied_vol

STATUSES = ["ok", "zero_bid", "below_intrinsic", "no_solution", "expired", "no_underlying"]


def setup_logging() -> logging.Logger:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("enrich")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = logging.FileHandler(config.LOG_DIR / "enrich.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger


def find_latest_snapshot(date_str: str | None = None) -> Path:
    glob_pattern = f"date={date_str}/snapshot_*.parquet" if date_str else "date=*/snapshot_*.parquet"
    files = sorted((config.DATA_DIR / "snapshots").glob(glob_pattern))
    if not files:
        scope = f"date={date_str}" if date_str else "any date="
        raise FileNotFoundError(f"No snapshot files found under data/snapshots/{scope}")
    return files[-1]


def read_snapshot(path: Path) -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    df = con.execute("SELECT * FROM read_parquet(?)", [str(path)]).fetchdf()
    df["expiry"] = pd.to_datetime(df["expiry"])
    df["snapshot_ts_utc"] = pd.to_datetime(df["snapshot_ts_utc"], utc=True)
    return df


def _is_valid_positive(x) -> bool:
    return x is not None and not pd.isna(x) and x > 0


def _intrinsic(S: float, K: float, T: float, r: float, q: float, option_type: str) -> float:
    if option_type == "call":
        return max(S * np.exp(-q * T) - K * np.exp(-r * T), 0.0)
    return max(K * np.exp(-r * T) - S * np.exp(-q * T), 0.0)


def enrich_row(rec: dict, r: float, q: float) -> dict:
    S = rec["underlying_price"]
    K = rec["strike"]
    option_type = rec["right"]

    expiry_date = rec["expiry"].date()
    snapshot_date = rec["snapshot_ts_utc"].date()
    T_used = (expiry_date - snapshot_date).days / 365.0

    out = {
        "iv_bid": None, "iv_mid": None, "iv_ask": None,
        "delta_bs": None, "gamma_bs": None, "vega_bs": None, "theta_bs": None, "rho_bs": None,
        "moneyness": None,
        "status": None,
        "r_used": r, "q_used": q, "T_used": T_used,
    }

    if T_used <= 0:
        out["status"] = "expired"
        return out

    if not _is_valid_positive(S):
        out["status"] = "no_underlying"
        return out

    out["moneyness"] = float(np.log(K / S))

    bid, ask = rec["bid"], rec["ask"]
    bid_ok, ask_ok = _is_valid_positive(bid), _is_valid_positive(ask)

    out["iv_bid"] = implied_vol(bid, S, K, T_used, r, q, option_type) if bid_ok else None
    out["iv_ask"] = implied_vol(ask, S, K, T_used, r, q, option_type) if ask_ok else None

    mid = (bid + ask) / 2.0 if (bid_ok and ask_ok) else None
    iv_mid = implied_vol(mid, S, K, T_used, r, q, option_type) if mid is not None else None
    out["iv_mid"] = iv_mid

    if not bid_ok or not ask_ok:
        out["status"] = "zero_bid"
    elif iv_mid is not None:
        out["status"] = "ok"
    elif mid < _intrinsic(S, K, T_used, r, q, option_type):
        out["status"] = "below_intrinsic"
    else:
        out["status"] = "no_solution"

    if iv_mid is not None:
        greeks = bs_greeks(S, K, T_used, r, iv_mid, q, option_type)
        out["delta_bs"] = greeks["delta"]
        out["gamma_bs"] = greeks["gamma"]
        out["vega_bs"] = greeks["vega"]
        out["theta_bs"] = greeks["theta"]
        out["rho_bs"] = greeks["rho"]

    return out


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    r, q = config.RISK_FREE_RATE, config.DIVIDEND_YIELD
    enriched_rows = [enrich_row(rec, r, q) for rec in df.to_dict("records")]
    enriched_df = pd.DataFrame(enriched_rows)
    return pd.concat([df.reset_index(drop=True), enriched_df], axis=1)


def write_derived(df: pd.DataFrame) -> Path:
    snapshot_ts = df["snapshot_ts_utc"].iloc[0]
    date_str = snapshot_ts.strftime("%Y-%m-%d")
    ts_str = snapshot_ts.strftime("%Y%m%dT%H%M%SZ")
    partition_dir = config.DATA_DIR / "derived" / f"date={date_str}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    out_path = partition_dir / f"enriched_{ts_str}.parquet"
    df.to_parquet(out_path, engine="pyarrow", index=False)
    return out_path


def run(logger: logging.Logger, file_arg: str | None, date_arg: str | None) -> None:
    target = Path(file_arg) if file_arg else find_latest_snapshot(date_arg)
    if not target.exists():
        raise FileNotFoundError(f"Snapshot file not found: {target}")

    df = read_snapshot(target)
    enriched = enrich(df)
    out_path = write_derived(enriched)

    counts = enriched["status"].value_counts().to_dict()
    breakdown = ", ".join(f"{s}={counts.get(s, 0)}" for s in STATUSES)
    logger.info(
        "Enriched %s | contracts=%d | %s | wrote %s",
        target.name,
        len(enriched),
        breakdown,
        out_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default=None, help="Path to a specific snapshot parquet file")
    parser.add_argument("--date", default=None, help="Process the latest snapshot under data/snapshots/date=<date>")
    args = parser.parse_args()

    logger = setup_logging()
    run(logger, args.file, args.date)


if __name__ == "__main__":
    main()
