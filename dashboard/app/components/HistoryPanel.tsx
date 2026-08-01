"use client";

import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchHistory } from "../api";
import { HistoryResponse } from "../types";

// ts is a stringified pandas Timestamp ("2026-07-27 17:11:30.169506+00:00"),
// not epoch millis — needs a "T" separator before Date can parse it.
function parseTs(ts: string): string {
  const d = new Date(ts.replace(" ", "T"));
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function HistoryPanel() {
  const [data, setData] = useState<HistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchHistory());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <>
      <div className="flex justify-end mb-4">
        <button
          onClick={load}
          className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-sm"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="rounded bg-red-900/40 border border-red-700 p-4 mb-4 text-sm">
          {error} — is the backend running on :8000?
        </div>
      )}

      {data && (
        <section className="rounded-lg bg-slate-900 border border-slate-800 p-5">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm uppercase tracking-wide text-slate-400">
              Front-Tenor ATM Vol
            </h2>
            <span className="text-lg font-semibold text-slate-100">
              {data.n_trading_sessions} sessions
            </span>
          </div>

          <div className="mt-2 text-sm text-slate-300 flex gap-6">
            <span>
              range{" "}
              {data.range
                ? `${data.range.low.toFixed(4)} – ${data.range.high.toFixed(4)}`
                : "—"}
            </span>
            <span>
              filtered {data.n_total_snapshots - data.n_trading_sessions}
            </span>
            <span>max staleness {data.max_staleness_hours}h</span>
          </div>

          <div className="mt-4" style={{ height: 300 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={data.points}
                margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis
                  dataKey="ts"
                  stroke="#475569"
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  tickFormatter={parseTs}
                />
                <YAxis
                  stroke="#475569"
                  tick={{ fill: "#64748b", fontSize: 11 }}
                  domain={["auto", "auto"]}
                  tickFormatter={(v: number) => v.toFixed(3)}
                />
                <Tooltip
                  contentStyle={{
                    background: "#0f172a",
                    border: "1px solid #1e293b",
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "#94a3b8" }}
                  labelFormatter={(ts) => parseTs(String(ts))}
                  formatter={(v) => [Number(v).toFixed(4), "ATM Vol"]}
                />
                <Line
                  type="monotone"
                  dataKey="atm_vol"
                  stroke="#34d399"
                  strokeWidth={2}
                  dot={{ r: 3, fill: "#34d399", strokeWidth: 0 }}
                  activeDot={{ r: 5 }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <p className="mt-3 text-xs text-slate-600">
            Weekend/holiday snapshots are filtered out — a session counts as
            &quot;trading&quot; only if its option quotes were fresh within{" "}
            {data.max_staleness_hours}h of the snapshot; stale (closed-market)
            snapshots are excluded from the series above.
          </p>
        </section>
      )}
    </>
  );
}
