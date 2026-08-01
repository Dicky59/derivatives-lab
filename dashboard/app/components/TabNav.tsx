export type Tab = "signals" | "surface" | "history";

const TABS: { id: Tab; label: string }[] = [
  { id: "signals", label: "Signals" },
  { id: "surface", label: "Surface" },
  { id: "history", label: "History" },
];

export default function TabNav({
  active,
  onChange,
}: {
  active: Tab;
  onChange: (t: Tab) => void;
}) {
  return (
    <nav className="flex gap-2 mb-6">
      {TABS.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`px-3 py-1.5 rounded text-sm border ${
            active === t.id
              ? "bg-slate-800 text-slate-100 border-slate-700"
              : "bg-slate-900 text-slate-400 border-slate-800 hover:bg-slate-800 hover:text-slate-200"
          }`}
        >
          {t.label}
        </button>
      ))}
    </nav>
  );
}
