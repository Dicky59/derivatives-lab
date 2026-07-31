"""Walk-forward, point-in-time signal backtesting framework.

Cardinal rule: when a signal is evaluated at snapshot time T, it sees ONLY
data at times <= T. The outcome is measured over T+1..T+horizon. These never
overlap — that is the no-lookahead guarantee.

Reports results ONLY when there are enough signal instances; otherwise returns
INSUFFICIENT_DATA. With few observations, a point estimate is noise, so we also
report a confidence interval and refuse conclusions below MIN_INSTANCES.
"""
import numpy as np

MIN_INSTANCES = 30     # below this, no conclusions — a backtest of <30 is noise


def walk_forward(snapshots, signal_fn, outcome_fn, success_fn,
                 horizon, min_instances=MIN_INSTANCES):
    """
    snapshots: chronological list of point-in-time states, each a dict the
               signal_fn and outcome_fn understand. MUST be time-ordered.
    signal_fn(history_upto_t) -> signal state dict, or None if signal doesn't
               fire / can't evaluate. Receives ONLY snapshots[0..t] (no future).
    outcome_fn(snapshots, t, horizon) -> realized outcome using snapshots[t+1..t+horizon].
               Returns None if the forward window runs off the end of the data.
    success_fn(signal_state, outcome) -> True/False: did the prediction come true?
    horizon: forward window length (in snapshots) to measure the outcome.

    Returns a results dict with instances, hit rate, confidence interval, and
    a status that is INSUFFICIENT_DATA until min_instances is reached.
    """
    instances = []
    for t in range(len(snapshots)):
        # POINT-IN-TIME: signal sees only up to and including t
        history_upto_t = snapshots[:t + 1]
        sig = signal_fn(history_upto_t)
        if sig is None:
            continue                      # signal didn't fire here

        # OUTCOME: measured strictly in the FUTURE, t+1..t+horizon
        outcome = outcome_fn(snapshots, t, horizon)
        if outcome is None:
            continue                      # not enough forward data — skip honestly

        instances.append({
            "t": t,
            "ts": snapshots[t].get("ts"),
            "signal": sig,
            "outcome": outcome,
            "success": bool(success_fn(sig, outcome)),
        })

    n = len(instances)
    if n < min_instances:
        return {
            "status": "INSUFFICIENT_DATA",
            "instances": n,
            "need": min_instances,
            "message": f"Only {n} usable signal instances (need {min_instances}). "
                       f"No conclusion — result would be noise. Accumulates with history.",
            "detail": instances,        # kept for inspection, NOT for conclusions
        }

    hits = sum(1 for x in instances if x["success"])
    hit_rate = hits / n
    # Wald-ish 95% CI on the hit rate (rough; honest about width at small n)
    se = np.sqrt(hit_rate * (1 - hit_rate) / n)
    ci = (max(0.0, hit_rate - 1.96 * se), min(1.0, hit_rate + 1.96 * se))

    return {
        "status": "OK",
        "instances": n,
        "hits": hits,
        "hit_rate": hit_rate,
        "ci_95": ci,
        "horizon": horizon,
        "detail": instances,
    }