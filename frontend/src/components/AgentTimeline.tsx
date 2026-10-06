import { useEffect, useState } from "react";
import { buildTimeline, TOOL_LABELS } from "../timeline";
import type { AgentEvent } from "../types";

/** Live view of what the agent is doing: tool calls appear as the model makes them. */
export function AgentTimeline({ ticker, events }: { ticker: string; events: AgentEvent[] }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 500);
    return () => window.clearInterval(id);
  }, []);

  const rows = buildTimeline(events);
  return (
    <section className="card" aria-live="polite" aria-busy="true">
      <h2 className="card-title big">
        <span className="spinner" aria-hidden /> Agent researching {ticker}
        <span className="muted"> · {elapsed}s</span>
      </h2>
      <p className="muted small">The model decides which tools to call. Independent calls run in parallel.</p>
      {rows.length === 0 && <p className="muted">Starting…</p>}
      <ol className="timeline">
        {rows.map((r, i) =>
          r.kind === "reasoning" ? (
            <li key={i} className="tl reasoning">💭 {r.text}</li>
          ) : (
            <li key={i} className={`tl ${r.status}`}>
              <span className="tl-icon" aria-hidden>
                {r.status === "running" ? <span className="spinner small" /> : r.status === "ok" ? "✓" : "✗"}
              </span>
              <div>
                <div className="tl-title">
                  {TOOL_LABELS[r.tool] ?? r.tool} <code>{r.tool}</code>
                  {r.seconds !== undefined && <span className="muted"> · {r.seconds.toFixed(1)}s</span>}
                </div>
                {r.summary && <div className="muted small">{r.summary}</div>}
              </div>
            </li>
          ),
        )}
      </ol>
    </section>
  );
}
