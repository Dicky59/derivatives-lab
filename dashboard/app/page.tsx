"use client";

import { useEffect, useState } from "react";
import { fetchSignals } from "./api";
import { SignalsResponse } from "./types";

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

export default function Home() {
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
    <main className="min-h-screen bg-slate-950 text-slate-100 p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-semibold">derivatives-lab · signals</h1>
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

            {/* Skew richness */}
            <section className="rounded-lg bg-slate-900 border border-slate-800 p-5 mb-4">
              <div className="flex items-baseline justify-between">
                <h2 className="text-sm uppercase tracking-wide text-slate-400">
                  Skew Richness
                </h2>
                <span className="text-lg font-semibold text-slate-200">
                  {data.skew_richness.flags.length === 0
                    ? "SMOOTH"
                    : `${data.skew_richness.flags.length} FLAGGED`}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-400">
                {data.skew_richness.summary}
              </p>
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
      </div>
    </main>
  );
}