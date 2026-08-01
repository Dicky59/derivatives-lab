"use client";

import { useEffect, useState } from "react";
import { fetchSignals } from "../api";
import { SignalsResponse } from "../types";

// small helper for regime colour
function regimeColor(regime: string): string {
  switch (regime) {
    case "CONTANGO":
    case "LOW":
    case "NEUTRAL":
      return "text-emerald-400";
    case "BACKWARDATION":
    case "HIGH":
      return "text-amber-400";
    default:
      return "text-slate-300";
  }
}

export default function SignalsPanel() {
  const [data, setData] = useState<SignalsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchSignals());
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
        <>
          <p className="text-xs text-slate-500 mb-4">
            snapshot {data.snapshot_ts}
          </p>

          {/* Term structure */}
          <section className="rounded-lg bg-slate-900 border border-slate-800 p-5 mb-4">
            <div className="flex items-baseline justify-between">
              <h2 className="text-sm uppercase tracking-wide text-slate-400">
                Term Structure
              </h2>
              <span
                className={`text-lg font-semibold ${regimeColor(
                  data.term_structure.regime
                )}`}
              >
                {data.term_structure.regime}
              </span>
            </div>
            <div className="mt-2 text-sm text-slate-300 flex gap-6">
              <span>slope/yr {data.term_structure.slope_per_year.toFixed(4)}</span>
              <span>front {data.term_structure.front_vol.toFixed(4)}</span>
              <span>back {data.term_structure.back_vol.toFixed(4)}</span>
            </div>
            <p className="mt-3 text-sm text-slate-400">
              {data.term_structure.implication}
            </p>
            <p className="mt-2 text-xs text-slate-600">
              {data.term_structure.confidence}
            </p>
          </section>

          {/* Skew richness — shows flag detail when it fires */}
          <section
            className={`rounded-lg border p-5 mb-4 ${data.skew_richness.flags.length > 0
                ? "bg-amber-950/30 border-amber-700/50"
                : "bg-slate-900 border-slate-800"
              }`}
          >
            <div className="flex items-baseline justify-between">
              <h2 className="text-sm uppercase tracking-wide text-slate-400">
                Skew Richness
              </h2>
              <span
                className={`text-lg font-semibold ${data.skew_richness.flags.length > 0
                    ? "text-amber-400"
                    : "text-emerald-400"
                  }`}
              >
                {data.skew_richness.flags.length === 0
                  ? "SMOOTH"
                  : `${data.skew_richness.flags.length} FLAGGED`}
              </span>
            </div>

            <p className="mt-2 text-sm text-slate-400">
              {data.skew_richness.summary}
            </p>

            {/* Flag detail table — only when something fired */}
            {data.skew_richness.flags.length > 0 && (
              <div className="mt-3 rounded bg-slate-950/50 border border-slate-800 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs uppercase tracking-wide text-slate-500 border-b border-slate-800">
                      <th className="text-left px-3 py-2">Expiry (T, yrs)</th>
                      <th className="text-left px-3 py-2">Kind</th>
                      <th className="text-right px-3 py-2">Skew</th>
                      <th className="text-right px-3 py-2">Fitted</th>
                      <th className="text-right px-3 py-2">z-score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.skew_richness.flags.map((f, i) => (
                      <tr key={i} className="border-b border-slate-800/50 last:border-0">
                        <td className="px-3 py-2 font-mono">{f.T.toFixed(3)}</td>
                        <td className="px-3 py-2">
                          <span
                            className={
                              f.kind.startsWith("RICH")
                                ? "text-amber-400"
                                : "text-sky-400"
                            }
                          >
                            {f.kind}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {f.skew.toFixed(3)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono text-slate-400">
                          {f.fitted_skew.toFixed(3)}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">
                          {f.z >= 0 ? "+" : ""}
                          {f.z.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <p className="mt-2 text-xs text-slate-600">
              {data.skew_richness.confidence}
            </p>
          </section>

          {/* IV rank — handles scaffold vs active */}
          <section className="rounded-lg bg-slate-900 border border-slate-800 p-5">
            <div className="flex items-baseline justify-between">
              <h2 className="text-sm uppercase tracking-wide text-slate-400">
                IV Rank
              </h2>
              {data.iv_rank.status === "active" ? (
                <span className={`text-lg font-semibold ${regimeColor(data.iv_rank.regime)}`}>
                  {data.iv_rank.regime} · {(data.iv_rank.iv_rank * 100).toFixed(0)}
                </span>
              ) : (
                <span className="text-lg font-semibold text-slate-500">
                  {data.iv_rank.have}/{data.iv_rank.need}
                </span>
              )}
            </div>
            {data.iv_rank.status === "active" ? (
              <p className="mt-2 text-sm text-slate-400">
                {data.iv_rank.implication}
              </p>
            ) : (
              <p className="mt-2 text-sm text-slate-400">
                {data.iv_rank.message}
              </p>
            )}
            <p className="mt-2 text-xs text-slate-600">
              {data.iv_rank.confidence}
            </p>
          </section>
        </>
      )}
    </>
  );
}
