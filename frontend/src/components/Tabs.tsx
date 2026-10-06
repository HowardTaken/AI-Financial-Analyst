import { fmt, fmtBig, fmtByKind, memoToMarkdown, parseSections, PEER_ROWS, peerMedians, rankCells, safeHttpUrl } from "../format";
import type { AnalysisResult, EarningsSummary, Metrics, Peer, TraceStep } from "../types";
import { Empty, Notice, RichText, Stat } from "./common";

// ── Memo ─────────────────────────────────────────────────────────────────────

function download(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function MemoTab({ result }: { result: AnalysisResult }) {
  const { memo } = result;
  return (
    <div>
      {result.warnings.map((w) => (
        <Notice key={w} kind="warn">{w}</Notice>
      ))}
      <h2 className="headline">{memo.headline}</h2>
      {memo.price_target !== null && (
        <div className="stats">
          <Stat label="12-month price target" value={fmt(memo.price_target, { prefix: "$" })} />
        </div>
      )}
      <h3 className="section">Quantitative case</h3>
      <RichText text={memo.quantitative_case} />
      <h3 className="section">10-K vs. earnings call</h3>
      <RichText text={memo.filing_vs_call} />
      {(memo.key_risks.length > 0 || memo.catalysts.length > 0) && (
        <div className="two-col">
          {memo.key_risks.length > 0 && (
            <div>
              <h3 className="section">Key risks</h3>
              <ul className="list">{memo.key_risks.map((r) => <li key={r}>{r}</li>)}</ul>
            </div>
          )}
          {memo.catalysts.length > 0 && (
            <div>
              <h3 className="section">Catalysts</h3>
              <ul className="list">{memo.catalysts.map((c) => <li key={c}>{c}</li>)}</ul>
            </div>
          )}
        </div>
      )}
      <h3 className="section">Verdict</h3>
      <RichText text={memo.verdict} />
      {memo.data_gaps.length > 0 && (
        <Notice kind="info">
          <strong>Data gaps:</strong> {memo.data_gaps.join("; ")}
        </Notice>
      )}
      <button
        className="btn btn-secondary"
        onClick={() => download(`${result.ticker}_memo.md`, memoToMarkdown(result.ticker, memo, result.warnings))}
      >
        ⬇ Download memo (.md)
      </button>
    </div>
  );
}

// ── Earnings ─────────────────────────────────────────────────────────────────

export function EarningsTab({ earnings }: { earnings: EarningsSummary | null }) {
  if (!earnings) return <Empty>No earnings-call summary was retrieved for this run.</Empty>;
  const sources = earnings.sources.map((s) => ({ ...s, href: safeHttpUrl(s.uri) })).filter((s) => s.href);
  return (
    <div>
      {sources.length > 0 ? (
        <Notice kind="ok">Summary backed by {sources.length} cited web source(s).</Notice>
      ) : (
        <Notice kind="warn">No grounding sources were returned. Treat this summary as unverified.</Notice>
      )}
      <p className="muted small">This is an AI-generated summary assembled from web search results, not a verbatim transcript.</p>
      {parseSections(earnings.text).map((s) => (
        <section key={s.heading} className="card accent">
          <h4 className="card-title">{s.heading}</h4>
          <RichText text={s.body} />
        </section>
      ))}
      {sources.length > 0 && (
        <details className="details">
          <summary>Sources</summary>
          <ul className="list">
            {sources.map((s) => (
              <li key={s.href}>
                <a href={s.href!} target="_blank" rel="noopener noreferrer">{s.title}</a>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// ── Peers ────────────────────────────────────────────────────────────────────

export function PeersTab({ metrics, peers }: { metrics: Metrics | null; peers: Peer[] }) {
  const ok = peers.filter((p) => p.metrics);
  if (!metrics || ok.length === 0) return <Empty>No peer data was retrieved for this run.</Empty>;
  const columns = [{ ticker: metrics.ticker, m: metrics, cap: null as number | null }, ...ok.map((p) => ({ ticker: p.ticker, m: p.metrics!, cap: p.market_cap }))];
  const medians = peerMedians(peers);
  const failed = peers.filter((p) => !p.metrics);
  return (
    <div>
      <div className="table-wrap">
        <table className="grid peers">
          <thead>
            <tr>
              <th>Metric</th>
              {columns.map((c, i) => (
                <th key={c.ticker} className={i === 0 ? "target" : ""}>{c.ticker}</th>
              ))}
              <th>Peer median</th>
            </tr>
          </thead>
          <tbody>
            {PEER_ROWS.map((row) => {
              const values = columns.map((c) => c.m[row.key] as number | null);
              const { best, worst } = rankCells(values, row.higherIsBetter);
              return (
                <tr key={row.key}>
                  <th>{row.label}</th>
                  {values.map((v, i) => (
                    <td key={columns[i].ticker} className={`${i === 0 ? "target" : ""} ${best.includes(i) ? "best" : ""} ${worst.includes(i) ? "worst" : ""}`}>
                      {best.includes(i) && "▲ "}
                      {worst.includes(i) && "▼ "}
                      {fmtByKind(v, row.kind)}
                    </td>
                  ))}
                  <td>{fmtByKind(medians[row.key], row.kind)}</td>
                </tr>
              );
            })}
            <tr>
              <th>Market cap</th>
              {columns.map((c) => <td key={c.ticker}>{c.cap === null ? "–" : fmtBig(c.cap)}</td>)}
              <td>–</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="muted small">
        ▲ best / ▼ worst per row (lower is better for P/E, D/E, P/B). Check the market caps: peers should be
        genuine competitors, and the agent re-selects them when Yahoo's industry list is a poor match.
      </p>
      {failed.length > 0 && (
        <p className="muted small">Skipped: {failed.map((p) => `${p.ticker} (${p.error})`).join(", ")}</p>
      )}
    </div>
  );
}

// ── Agent activity ───────────────────────────────────────────────────────────

export function TraceTab({ trace, elapsed }: { trace: TraceStep[]; elapsed: number }) {
  if (trace.length === 0) return <Empty>No agent activity was recorded for this analysis.</Empty>;
  return (
    <div>
      <p className="muted small">
        The model chose these tool calls itself. Independent calls are issued together and run in parallel.
        Total time {elapsed.toFixed(0)}s.
      </p>
      {trace.map((s) => {
        const args = Object.entries(s.args).filter(([k]) => k !== "text").map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
        return (
          <div key={s.step} className={`trace ${s.ok ? "" : "trace-fail"}`}>
            <div>
              <code className="tool">{s.tool}</code>
              {s.tool !== "submit_memo" && args && <span className="muted"> ({args.slice(0, 120)})</span>}
              <span className="muted"> · {s.seconds.toFixed(1)}s</span>
              {!s.ok && <span className="fail"> failed</span>}
            </div>
            <div className="muted">{s.summary}</div>
          </div>
        );
      })}
    </div>
  );
}
