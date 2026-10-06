// The JSON contract of the backend. Mirrors analyst/models.py (dataclasses serialised with asdict).

export type Rating = "BUY" | "HOLD" | "SELL";
export type Confidence = "LOW" | "MEDIUM" | "HIGH";

export interface Memo {
  rating: Rating;
  confidence: Confidence;
  price_target: number | null;
  headline: string;
  quantitative_case: string;
  filing_vs_call: string;
  key_risks: string[];
  catalysts: string[];
  verdict: string;
  data_gaps: string[];
}

export interface Metrics {
  ticker: string;
  fiscal_year: string;
  prior_year: string;
  current_price: number | null;
  pe_ratio: number | null;
  eps_basis: string;
  debt_to_equity: number | null;
  gross_margin_pct: number | null;
  yoy_revenue_growth_pct: number | null;
  price_to_book: number | null;
  roe_pct: number | null;
  diluted_eps: number | null;
  total_debt: number | null;
  stockholders_equity: number | null;
  gross_profit: number | null;
  net_income: number | null;
  revenue_current: number | null;
  revenue_prior: number | null;
}

export interface Sensitivity {
  wacc_pct: number[];
  terminal_growth_pct: number[];
  values: (number | null)[][]; // rows: WACC, columns: terminal growth
}

export interface DCFResult {
  available: boolean;
  reason: string;
  ticker: string;
  wacc_pct: number;
  cost_of_equity_pct: number;
  terminal_growth_pct: number;
  raw_growth_pct: number;
  starting_growth_pct: number;
  fcf_history: Record<string, number>;
  base_fcf: number;
  projected_fcf: number[];
  pv_projected_fcf: number[];
  terminal_value: number;
  pv_terminal_value: number;
  terminal_value_share_pct: number;
  enterprise_value: number;
  net_debt: number;
  equity_value: number;
  shares_outstanding: number;
  intrinsic_value: number;
  current_price: number | null;
  upside_pct: number | null;
  margin_of_safety_pct: number | null;
  sensitivity: Partial<Sensitivity>;
  warnings: string[];
}

export interface Peer {
  ticker: string;
  name: string;
  market_weight: number;
  market_cap: number | null;
  metrics: Metrics | null;
  error: string | null;
}

export interface EarningsSummary {
  ticker: string;
  text: string;
  sources: { title: string; uri: string }[];
}

export interface TraceStep {
  step: number;
  tool: string;
  args: Record<string, unknown>;
  ok: boolean;
  seconds: number;
  summary: string;
}

export interface AnalysisResult {
  ticker: string;
  memo: Memo;
  metrics: Metrics | null;
  dcf: DCFResult | null;
  earnings: EarningsSummary | null;
  peers: Peer[];
  filing_excerpt: string;
  trace: TraceStep[];
  warnings: string[];
  elapsed_seconds: number;
  created_at: string;
}

export type JobStatus = "queued" | "running" | "done" | "error";

export interface Job {
  id: string;
  ticker: string;
  status: JobStatus;
  created_at: number;
  finished_at: number | null;
  error: string | null;
  error_code: string | null;
  result: AnalysisResult | null;
}

/** Events streamed over SSE while the agent works. `t` is seconds since the job started. */
export type AgentEvent =
  | { type: "started"; ticker: string; t: number }
  | { type: "tool_start"; tool: string; args: Record<string, unknown>; t: number }
  | { type: "tool_end"; tool: string; ok: boolean; summary: string; seconds: number; t: number }
  | { type: "reasoning"; text: string; t: number }
  | { type: "memo"; rating: Rating; t: number }
  | { type: "done"; t: number }
  | { type: "error"; code: string; message: string; t: number };

export interface StartResponse {
  id: string;
  ticker: string;
  status: JobStatus;
  cached: boolean;
}
