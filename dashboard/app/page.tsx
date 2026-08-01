"use client";

import { useState } from "react";
import TabNav, { Tab } from "./components/TabNav";
import SignalsPanel from "./components/SignalsPanel";
import SurfacePanel from "./components/SurfacePanel";
import HistoryPanel from "./components/HistoryPanel";

export default function Home() {
  const [tab, setTab] = useState<Tab>("signals");
  // Panels mount lazily on first visit, then stay mounted — switching tabs
  // never refetches. (Eager-mounting all three up front made recharts'
  // ResponsiveContainer measure a 0x0 box inside a display:none container.)
  const [visited, setVisited] = useState<Set<Tab>>(new Set(["signals"]));

  function selectTab(t: Tab) {
    setTab(t);
    setVisited((prev) => (prev.has(t) ? prev : new Set(prev).add(t)));
  }

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-8">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-2xl font-semibold mb-6">derivatives-lab</h1>
        <TabNav active={tab} onChange={selectTab} />
        {visited.has("signals") && (
          <div className={tab === "signals" ? "" : "hidden"}>
            <SignalsPanel />
          </div>
        )}
        {visited.has("surface") && (
          <div className={tab === "surface" ? "" : "hidden"}>
            <SurfacePanel />
          </div>
        )}
        {visited.has("history") && (
          <div className={tab === "history" ? "" : "hidden"}>
            <HistoryPanel />
          </div>
        )}
      </div>
    </main>
  );
}
