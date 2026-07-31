"""Backtest definition for the term-structure signal (fixed outcome).

Falsification tested: BACKWARDATION should precede LARGER realized underlying
moves than CONTANGO. Outcome = realized vol over a forward window of TRADING
DAYS, from a real daily price series (not sparse snapshot prices).
"""
import numpy as np

from src.signals.term_structure import term_structure_signal
from src.backtest.price_history import realized_vol_over


def ts_signal_fn(history_upto_t):
    now = history_upto_t[-1]
    slices = now.get("slices")
    if not slices:
        return None
    sig = term_structure_signal(slices)
    if sig["regime"] == "FLAT":
        return None
    return sig


def make_ts_outcome_fn(price_history, horizon_days):
    """
    Returns an outcome_fn(snapshots, t, horizon_ignored) that measures realized
    vol over `horizon_days` trading days AFTER snapshot t's date, using the real
    daily price series. The framework's `horizon` arg is ignored here (kept for
    signature compatibility) — the real horizon is in trading days.
    """
    def outcome_fn(snapshots, t, horizon_ignored):
        snap_ts = snapshots[t]["ts"]
        snap_date = snap_ts.date() if hasattr(snap_ts, "date") else snap_ts
        rv = realized_vol_over(price_history, snap_date, horizon_days)
        if rv is None:
            return None
        return {"realized_vol": rv}
    return outcome_fn


def make_ts_success_fn(median_realized_vol):
    def success_fn(sig, outcome):
        rv = outcome["realized_vol"]
        if sig["regime"] == "BACKWARDATION":
            return rv > median_realized_vol
        else:  # CONTANGO
            return rv < median_realized_vol
    return success_fn