import { fmt, fmtBig, isNum } from "../format";
import type { DCFResult, Metrics } from "../types";
import { Empty, Notice, Stat } from "./common";
import { LineChart } from "./LineChart";

function SensitivityTable({ dcf }: { dcf: DCFResult }) {
  const { wacc_pct: waccs, terminal_growth_pct: growths, values } = dcf.sensitivity;
  if (!waccs || !growths || !values) return null;
  const price = dcf.current_price;
  return (
    <div className="table-wrap">
      <table className="grid">
        <caption>Intrinsic value per share. Green cells are above today's price, red cells below.</caption>
        <thead>
          <tr>
            <th>WACC ↓ / growth →</th>
            {growths.map((g) => (
              <th key={g}>{g.toFixed(1)}%</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {values.map((row, r) => (
            <tr key={waccs[r]}>
              <th>{waccs[r].toFixed(1)}%</th>
              {row.map((v, c) => {
                const tone = !isNum(v) || !isNum(price) ? "" : v >= price ? "cell-up" : "cell-down";
                const base = r === 2 && c === 2 ? "cell-base" : "";
                return (
                  <td key={c} className={`${tone} ${base}`}>
                    {isNum(v) ? fmt(v, { decimals: 0, prefix: "$" }) : "n/a"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ValuationTab({ dcf, metrics }: { dcf: DCFResult | null; metrics: Metrics | null }) {
  if (!dcf) return <Empty>The agent did not run a DCF for this company.</Empty>;

  if (!dcf.available) {
    return (
      <div>
        <Notice kind="warn">
          <strong>DCF not applicable.</strong> {dcf.reason}
        </Notice>
        {metrics && (isNum(metrics.price_to_book) || isNum(metrics.roe_pct)) && (
          <div className="stats">
            <Stat label="Price / book" value={fmt(metrics.price_to_book, { decimals: 2, suffix: "x" })} />
            <Stat label="ROE" value={fmt(metrics.roe_pct, { decimals: 1, suffix: "%" })} />
          </div>
        )}
      </div>
    );
  }

  const up = (dcf.upside_pct ?? 0) > 0;
  const tone = up ? "up" : "down";
  const years = dcf.projected_fcf.map((_, i) => `Year +${i + 1}`);
  return (
    <div>
      <div className="hero">
        <div className="hero-label">DCF intrinsic value per share (base case)</div>
        <div className={`hero-value ${tone}`}>{fmt(dcf.intrinsic_value, { prefix: "$" })}</div>
        <div className="hero-vs">vs. current market price</div>
        <div className="hero-price">{fmt(dcf.current_price, { prefix: "$" })}</div>
        <span className={`pill pill-${tone}`}>
          {up ? "▲" : "▼"} {fmt(Math.abs(dcf.upside_pct ?? 0), { decimals: 1 })}% implied {up ? "upside" : "downside"}
        </span>
      </div>
      <p className="muted small">
        A mechanical model that extrapolates historical free cash flow. It tends to be harsh on fast-growing,
        high-multiple companies; read the sensitivity table before trusting the gap.
      </p>

      <div className="stats">
        <Stat label="WACC" value={`${dcf.wacc_pct.toFixed(1)}%`} hint="CAPM cost of equity blended with after-tax cost of debt" />
        <Stat label="Terminal growth" value={`${dcf.terminal_growth_pct.toFixed(1)}%`} />
        <Stat
          label="Year-1 FCF growth"
          value={`${dcf.starting_growth_pct.toFixed(1)}%`}
          hint={`Historical ${dcf.raw_growth_pct.toFixed(1)}%, capped; fades to terminal growth by year 5`}
        />
        <Stat label="Terminal value share" value={`${dcf.terminal_value_share_pct.toFixed(0)}%`} hint="Share of enterprise value from beyond year 5" />
        <Stat
          label="Margin of safety"
          value={fmt(dcf.margin_of_safety_pct, { decimals: 1, suffix: "%", signed: true })}
          hint="(Intrinsic value − price) ÷ intrinsic value. Not the same as upside."
        />
      </div>
      {dcf.warnings.map((w) => (
        <p key={w} className="muted small">⚠️ {w}</p>
      ))}

      <h3 className="section">Sensitivity</h3>
      <SensitivityTable dcf={dcf} />

      <h3 className="section">Projected free cash flow</h3>
      <LineChart
        labels={years}
        unit="$B"
        series={[
          { name: "Projected FCF", color: "var(--accent)", values: dcf.projected_fcf.map((v) => v / 1e9) },
          { name: "Present value", color: "var(--green)", values: dcf.pv_projected_fcf.map((v) => v / 1e9) },
        ]}
      />

      <details className="details">
        <summary>Equity bridge</summary>
        <table className="kv">
          <tbody>
            <tr><th>PV of 5-year cash flows</th><td>{fmtBig(dcf.pv_projected_fcf.reduce((a, b) => a + b, 0))}</td></tr>
            <tr><th>PV of terminal value</th><td>{fmtBig(dcf.pv_terminal_value)}</td></tr>
            <tr><th>Enterprise value</th><td>{fmtBig(dcf.enterprise_value)}</td></tr>
            <tr><th>Net debt</th><td>{fmtBig(dcf.net_debt)}</td></tr>
            <tr><th>Equity value</th><td>{fmtBig(dcf.equity_value)}</td></tr>
            <tr><th>Shares outstanding</th><td>{dcf.shares_outstanding.toLocaleString("en-US")}</td></tr>
          </tbody>
        </table>
      </details>
    </div>
  );
}
