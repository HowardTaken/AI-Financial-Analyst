import { useState, type FormEvent } from "react";
import { AgentTimeline } from "./components/AgentTimeline";
import { Results } from "./components/Results";
import { describeError } from "./timeline";
import { useAnalysis } from "./useAnalysis";

const EXAMPLES = ["AAPL", "NVDA", "JPM", "KO"];

export default function App() {
  const { phase, ticker, events, result, failure, history, start, show } = useAnalysis();
  const [input, setInput] = useState("");
  const busy = phase === "running";

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!busy) void start(input);
  };
  const run = (t: string) => {
    setInput(t);
    if (!busy) void start(t);
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <h1 className="brand">📊 AI Market Analyst</h1>
        <p className="muted small">
          A tool-calling Gemini agent that researches a company and writes a Buy / Hold / Sell memo.
        </p>
        <h2 className="side-title">Recent</h2>
        {history.length === 0 && <p className="muted small">Your analyses appear here (stored only in this browser).</p>}
        <ul className="history">
          {history.map((h) => (
            <li key={h.ticker}>
              <button className={`hist ${result?.ticker === h.ticker && phase === "done" ? "active" : ""}`} onClick={() => show(h)}>
                <span className={`dot dot-${h.memo.rating.toLowerCase()}`} aria-hidden />
                <span>{h.ticker}</span>
                <span className="muted small">{h.memo.rating}</span>
              </button>
            </li>
          ))}
        </ul>
        <p className="muted tiny side-foot">Data: Yahoo Finance · SEC EDGAR · Gemini. Not financial advice.</p>
      </aside>

      <main className="main">
        <form className="search" onSubmit={submit} role="search">
          <input
            aria-label="Ticker symbol"
            placeholder="Enter a ticker, e.g. AAPL"
            value={input}
            maxLength={10}
            autoFocus
            onChange={(e) => setInput(e.target.value.toUpperCase())}
          />
          <button className="btn" type="submit" disabled={busy || !input.trim()}>
            {busy ? "Researching…" : "Run analysis"}
          </button>
        </form>

        {phase === "idle" && (
          <section className="empty hero-empty">
            <div className="big-emoji">📈</div>
            <p>
              Enter a ticker. The agent decides which data to pull, runs a DCF, reads the latest 10-K and earnings
              call, compares peers, and writes the memo.
            </p>
            <div className="chips">
              {EXAMPLES.map((t) => (
                <button key={t} className="chip" onClick={() => run(t)}>{t}</button>
              ))}
            </div>
          </section>
        )}

        {phase === "running" && <AgentTimeline ticker={ticker} events={events} />}

        {phase === "error" && failure && (
          <section className="notice notice-error" role="alert">
            <strong>Analysis failed.</strong> {describeError(failure.code, failure.message)}
            {failure.retryAfter !== undefined && <> You can retry in about {failure.retryAfter}s.</>}
            <div>
              <button className="btn btn-secondary" onClick={() => void start(ticker, true)}>Try again</button>
            </div>
          </section>
        )}

        {phase === "done" && result && (
          <>
            <Results key={result.ticker + result.created_at} result={result} />
            <button className="btn btn-link" onClick={() => void start(result.ticker, true)}>↻ Re-run with fresh data</button>
          </>
        )}
      </main>
    </div>
  );
}
