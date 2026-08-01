"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchSurface } from "../api";
import { SurfaceResponse } from "../types";
import { heatmapLegendStops, ivToColor } from "../lib/heatmapColor";

type HoverCell = { x: number; y: number; T: number; k: number; iv: number };

const TICK_STRIDE = 5;

export default function SurfacePanel() {
  const [data, setData] = useState<SurfaceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState<HoverCell | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchSurface());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const { min, max } = useMemo(() => {
    if (!data) return { min: 0, max: 0 };
    const all = data.surface_grid.flatMap((row) => row.ivs);
    return { min: Math.min(...all), max: Math.max(...all) };
  }, [data]);

  const legendStops = useMemo(() => heatmapLegendStops(min, max), [min, max]);

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
          <section className="rounded-lg bg-slate-900 border border-slate-800 p-5 mb-4">
            <div className="flex items-baseline justify-between">
              <h2 className="text-sm uppercase tracking-wide text-slate-400">
                SSVI Fit
              </h2>
              <span className="text-lg font-semibold text-slate-100">
                spot {data.spot.toFixed(2)}
              </span>
            </div>
            <div className="mt-2 text-sm text-slate-300 flex gap-6 font-mono">
              <span>rho {data.params.rho.toFixed(4)}</span>
              <span>eta {data.params.eta.toFixed(4)}</span>
              <span>gamma {data.params.gamma.toFixed(4)}</span>
            </div>
            <p className="mt-2 text-xs text-slate-600">
              snapshot {data.snapshot_ts}
            </p>
          </section>

          <section className="rounded-lg bg-slate-900 border border-slate-800 p-5 relative">
            <h2 className="text-sm uppercase tracking-wide text-slate-400 mb-4">
              Vol Surface — log-moneyness (x) × expiry T (y)
            </h2>

            <div className="overflow-x-auto">
              <div className="flex" style={{ minWidth: 640 }}>
                <div className="flex flex-col justify-between pr-2 shrink-0">
                  {data.surface_grid.map((row) => (
                    <div
                      key={row.T}
                      className="text-xs font-mono text-slate-500 flex items-center"
                      style={{ height: 20 }}
                    >
                      {row.T.toFixed(2)}
                    </div>
                  ))}
                </div>

                <div className="flex-1">
                  <div
                    className="grid gap-px bg-slate-950"
                    style={{
                      gridTemplateColumns: `repeat(${data.k_grid.length}, minmax(0, 1fr))`,
                    }}
                  >
                    {data.surface_grid.map((row, ri) =>
                      row.ivs.map((iv, ki) => (
                        <div
                          key={`${ri}-${ki}`}
                          className="aspect-square hover:ring-1 hover:ring-white/40 hover:z-10 relative"
                          style={{ backgroundColor: ivToColor(iv, min, max) }}
                          onMouseEnter={(e) => {
                            const rect = (
                              e.currentTarget as HTMLDivElement
                            ).getBoundingClientRect();
                            setHover({
                              x: rect.left + rect.width / 2,
                              y: rect.top,
                              T: row.T,
                              k: data.k_grid[ki],
                              iv,
                            });
                          }}
                          onMouseLeave={() => setHover(null)}
                        />
                      ))
                    )}
                  </div>

                  <div
                    className="grid mt-1"
                    style={{
                      gridTemplateColumns: `repeat(${data.k_grid.length}, minmax(0, 1fr))`,
                    }}
                  >
                    {data.k_grid.map((k, i) => (
                      <div
                        key={i}
                        className="text-[10px] font-mono text-slate-600 text-center"
                      >
                        {i % TICK_STRIDE === 0 ? k.toFixed(2) : ""}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {hover && (
              <div
                className="fixed z-20 pointer-events-none rounded bg-slate-900 border border-slate-800 text-xs font-mono px-2 py-1 text-slate-200"
                style={{
                  left: hover.x,
                  top: hover.y - 8,
                  transform: "translate(-50%, -100%)",
                }}
              >
                T={hover.T.toFixed(3)} k={hover.k.toFixed(3)} iv=
                {hover.iv.toFixed(4)}
              </div>
            )}

            <div className="mt-5 flex items-center gap-3">
              <span className="text-xs font-mono text-slate-500">
                {min.toFixed(3)}
              </span>
              <div
                className="h-2.5 flex-1 rounded border border-slate-800"
                style={{
                  background: `linear-gradient(to right, ${legendStops
                    .map((s) => s.color)
                    .join(", ")})`,
                }}
              />
              <span className="text-xs font-mono text-slate-500">
                {max.toFixed(3)}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-600 text-right">
              Implied Vol
            </p>
          </section>
        </>
      )}
    </>
  );
}
