import type { AgentEvent } from "./types";

export type Row =
  | { kind: "tool"; tool: string; status: "running" | "ok" | "failed"; summary: string; seconds?: number; startedAt: number }
  | { kind: "reasoning"; text: string; at: number };

/**
 * Turn the raw event stream into display rows. A tool_start creates a "running" row; the matching
 * tool_end (first running row for that tool) completes it. Parallel calls therefore show as several
 * running rows at once, which is exactly what the agent is doing.
 */
export function buildTimeline(events: AgentEvent[]): Row[] {
  const rows: Row[] = [];
  for (const e of events) {
    if (e.type === "tool_start") {
      rows.push({ kind: "tool", tool: e.tool, status: "running", summary: "", startedAt: e.t });
    } else if (e.type === "tool_end") {
      const row = rows.find((r): r is Extract<Row, { kind: "tool" }> => r.kind === "tool" && r.tool === e.tool && r.status === "running");
      if (row) {
        row.status = e.ok ? "ok" : "failed";
        row.summary = e.summary;
        row.seconds = e.seconds;
      }
    } else if (e.type === "reasoning") {
      rows.push({ kind: "reasoning", text: e.text, at: e.t });
    }
  }
  return rows;
}

export const TOOL_LABELS: Record<string, string> = {
  get_financial_metrics: "Fetching fundamentals",
  run_dcf_valuation: "Running DCF valuation",
  get_risk_factors: "Reading 10-K risk factors",
  get_earnings_call_summary: "Summarising latest earnings call",
  get_peer_comparison: "Comparing peers",
  submit_memo: "Writing the memo",
};

export function describeError(code: string | undefined, message: string): string {
  switch (code) {
    case "llm_quota":
      return "The AI provider's quota is exhausted right now. Wait a minute and try again.";
    case "no_data":
      return `${message} Double-check the ticker symbol.`;
    case "no_filing":
      return `${message} Some companies (foreign issuers, new listings) don't file a standard 10-K.`;
    default:
      return message;
  }
}
