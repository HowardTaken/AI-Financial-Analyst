import type { AnalysisResult, DCFResult, Metrics } from "../types";

export const metrics: Metrics = {
  ticker: "TEST", fiscal_year: "2025-09-30", prior_year: "2024-09-30", current_price: 100,
  pe_ratio: 20, eps_basis: "TTM", debt_to_equity: 0.4, gross_margin_pct: 45, yoy_revenue_growth_pct: 5.2,
  price_to_book: 8, roe_pct: 30, diluted_eps: 5, total_debt: 20e9, stockholders_equity: 50e9,
  gross_profit: 180e9, net_income: 90e9, revenue_current: 400e9, revenue_prior: 380e9,
};

export const dcf: DCFResult = {
  available: true, reason: "", ticker: "TEST", wacc_pct: 9, cost_of_equity_pct: 9, terminal_growth_pct: 2,
  raw_growth_pct: 4, starting_growth_pct: 4, fcf_history: { "2025-09-30": 100e9 }, base_fcf: 100e9,
  projected_fcf: [104e9, 107e9, 110e9, 112e9, 114e9], pv_projected_fcf: [95e9, 90e9, 85e9, 80e9, 74e9],
  terminal_value: 1.7e12, pv_terminal_value: 1.1e12, terminal_value_share_pct: 66.1, enterprise_value: 1.5e12,
  net_debt: 10e9, equity_value: 1.49e12, shares_outstanding: 1e9, intrinsic_value: 120, current_price: 100,
  upside_pct: 20, margin_of_safety_pct: 16.7,
  sensitivity: {
    wacc_pct: [7, 8, 9, 10, 11], terminal_growth_pct: [1, 1.5, 2, 2.5, 3],
    values: [0, 1, 2, 3, 4].map((r) => [0, 1, 2, 3, 4].map((c) => (r === 4 && c === 0 ? null : 80 + r * 5 + c * 8))),
  },
  warnings: ["Terminal value is 66% of enterprise value."],
};

export const result: AnalysisResult = {
  ticker: "TEST",
  memo: {
    rating: "BUY", confidence: "MEDIUM", price_target: 130, headline: "Strong franchise at a fair price.",
    quantitative_case: "Margins are **excellent**.\n- Revenue +5%\n- ROE 30%", filing_vs_call: "Consistent.",
    key_risks: ["Competition"], catalysts: ["New product"], verdict: "Buy it.", data_gaps: ["No transcript"],
  },
  metrics, dcf,
  earnings: {
    ticker: "TEST",
    text: "CALL DATE: 2026-01-30\n\n## 1. Opening Remarks & Results\n- Revenue up\n## 2. Forward Guidance\n- Guide higher",
    sources: [
      { title: "Good source", uri: "https://example.com/call" },
      { title: "Evil source", uri: "javascript:alert(1)" },
    ],
  },
  peers: [
    { ticker: "PEER", name: "Peer Co", market_weight: 1, market_cap: 5e11, error: null, metrics: { ...metrics, ticker: "PEER", pe_ratio: 30, gross_margin_pct: 35 } },
    { ticker: "BAD", name: "Bad", market_weight: 1, market_cap: null, metrics: null, error: "DataUnavailableError: nope" },
  ],
  filing_excerpt: "risk text",
  trace: [{ step: 1, tool: "get_financial_metrics", args: {}, ok: true, seconds: 1.2, summary: "TEST: price 100" }],
  warnings: ["Check the DCF"],
  elapsed_seconds: 42,
  created_at: "2026-01-01T00:00:00+00:00",
};

/** Same result with every optional piece missing, to prove nothing renders "null"/crashes. */
export const sparse: AnalysisResult = {
  ...result,
  metrics: { ...metrics, current_price: null, pe_ratio: null, debt_to_equity: null, gross_margin_pct: null, yoy_revenue_growth_pct: null, price_to_book: null, roe_pct: null },
  dcf: null, earnings: null, peers: [], trace: [], warnings: [],
  memo: { ...result.memo, price_target: null, key_risks: [], catalysts: [], data_gaps: [] },
};
