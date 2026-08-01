// Types matching the FastAPI /signals response shape.

export interface TermStructureSignal {
  signal: string;
  regime: "CONTANGO" | "BACKWARDATION" | "FLAT";
  slope_per_year: number;
  front_vol: number;
  back_vol: number;
  front_back_spread: number;
  implication: string;
  candidate_structure: string;
  confidence: string;
  falsification: string;
}

export interface SkewFlag {
  T: number;
  skew: number;
  fitted_skew: number;
  residual: number;
  z: number;
  kind: string;
}

export interface SkewRichnessSignal {
  signal: string;
  n_expiries: number;
  skew_by_T: [number, number][]; // [T, skew_slope] pairs
  fit_coeffs: [number, number]; // [slope_coeff, intercept] from np.polyfit
  residual_std: number | null;
  flags: SkewFlag[];
  summary: string;
  confidence: string;
  falsification: string;
  anchor_B_note: string;
}

// IV rank is either scaffold (inactive) or active — a discriminated union.
export interface IvRankScaffold {
  signal: string;
  status: "scaffold";
  have: number;
  need: number;
  message: string;
  confidence: string;
}

export interface IvRankActive {
  signal: string;
  status: "active";
  regime: "HIGH" | "LOW" | "NEUTRAL";
  iv_rank: number;
  iv_percentile: number;
  current_vol: number;
  hist_low: number;
  hist_high: number;
  n: number;
  implication: string;
  candidate_structure: string;
  confidence: string;
  confidence_depth: number;
  falsification: string;
}

export type IvRankSignal = IvRankScaffold | IvRankActive;

export interface SignalsResponse {
  snapshot_ts: string;
  term_structure: TermStructureSignal;
  skew_richness: SkewRichnessSignal;
  iv_rank: IvRankSignal;
}

// Types matching the FastAPI /history response shape.

export interface HistoryPoint {
  ts: string; // stringified pandas Timestamp w/ tz offset, e.g. "2026-07-27 17:11:30.169506+00:00"
  atm_vol: number;
}

export interface StalenessDebugEntry {
  file: string;
  stale_hours: number;
  trading_session: boolean;
}

export interface HistoryResponse {
  n_total_snapshots: number;
  n_trading_sessions: number;
  max_staleness_hours: number;
  points: HistoryPoint[];
  range: { low: number; high: number } | null;
  staleness_debug: StalenessDebugEntry[];
}

// Types matching the FastAPI /surface response shape.

export interface SurfaceExpirySummary {
  T: number;
  theta: number;
  atm_vol: number;
}

export interface SurfaceGridRow {
  T: number;
  ivs: number[]; // ivs[i] aligns positionally with k_grid[i]
}

export interface SurfaceParams {
  rho: number;
  eta: number;
  gamma: number;
}

export interface SurfaceResponse {
  snapshot_ts: string;
  spot: number;
  params: SurfaceParams;
  k_grid: number[];
  expiries: SurfaceExpirySummary[];
  surface_grid: SurfaceGridRow[];
}