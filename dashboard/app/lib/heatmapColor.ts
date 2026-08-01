// value -> css color. One hue (~199, matches the sky-400 accent already used
// for skew flags in this app), lightness/saturation increase monotonically
// with magnitude. Near-surface at the low end so "cheap" cells recede into
// bg-slate-950 instead of competing visually with the high end.
export function ivToColor(value: number, min: number, max: number): string {
  const t = max > min ? (value - min) / (max - min) : 0.5;
  const sat = 40 + t * 45; // 40% -> 85%
  const light = 12 + t * 50; // 12% -> 62%
  return `hsl(199 ${sat}% ${light}%)`;
}

export function heatmapLegendStops(
  min: number,
  max: number,
  n = 6
): { t: number; value: number; color: string }[] {
  return Array.from({ length: n }, (_, i) => {
    const t = n > 1 ? i / (n - 1) : 0;
    const value = min + t * (max - min);
    return { t, value, color: ivToColor(value, min, max) };
  });
}
