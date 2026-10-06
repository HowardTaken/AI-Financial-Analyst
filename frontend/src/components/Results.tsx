import { useState } from "react";
import { fmt } from "../format";
import type { AnalysisResult } from "../types";
import { RatingBadge, Stat } from "./common";
import { EarningsTab, MemoTab, PeersTab, TraceTab } from "./Tabs";
import { ValuationTab } from "./ValuationTab";

const TABS = [
  { id: "memo", label: "📋 Memo" },
  { id: "valuation", label: "💰 Valuation" },
  { id: "earnings", label: "🎙 Earnings call" },
  { id: "peers", label: "🏆 Peers" },
  { id: "agent", label: "🤖 Agent activity" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export function Results({ result }: { result: AnalysisResult }) {
  const [tab, setTab] = useState<TabId>("memo");
  const m = result.metrics;
  return (
    <article>
      <header className="result-head">
        <div>
          <h2 className="ticker">
            {result.ticker} {m && <span className="muted fy">FY {m.fiscal_year}</span>}
          </h2>
        </div>
        <RatingBadge rating={result.memo.rating} confidence={result.memo.confidence} />
      </header>

      {m && (
        <div className="stats">
          <Stat label="Price" value={fmt(m.current_price, { prefix: "$" })} />
          <Stat label={`P/E (${m.eps_basis})`} value={fmt(m.pe_ratio, { decimals: 1, suffix: "x" })} />
          <Stat label="Gross margin" value={fmt(m.gross_margin_pct, { decimals: 1, suffix: "%" })} />
          <Stat label="Debt / equity" value={fmt(m.debt_to_equity)} />
          <Stat
            label="Revenue growth"
            value={fmt(m.yoy_revenue_growth_pct, { decimals: 1, suffix: "%", signed: true })}
            tone={m.yoy_revenue_growth_pct === null ? undefined : m.yoy_revenue_growth_pct >= 0 ? "up" : "down"}
          />
        </div>
      )}

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={`tab ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="panel" role="tabpanel">
        {tab === "memo" && <MemoTab result={result} />}
        {tab === "valuation" && <ValuationTab dcf={result.dcf} metrics={result.metrics} />}
        {tab === "earnings" && <EarningsTab earnings={result.earnings} />}
        {tab === "peers" && <PeersTab metrics={result.metrics} peers={result.peers} />}
        {tab === "agent" && <TraceTab trace={result.trace} elapsed={result.elapsed_seconds} />}
      </div>
      <p className="muted small disclaimer">Educational research only; not financial advice.</p>
    </article>
  );
}
