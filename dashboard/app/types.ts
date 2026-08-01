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
  flags: SkewFlag[];
  summary: string;
  confidence: string;
  falsification: string;
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
  falsification: string;
}

export type IvRankSignal = IvRankScaffold | IvRankActive;

export interface SignalsResponse {
  snapshot_ts: string;
  term_structure: TermStructureSignal;
  skew_richness: SkewRichnessSignal;
  iv_rank: IvRankSignal;
}