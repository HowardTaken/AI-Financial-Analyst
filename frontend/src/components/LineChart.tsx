export interface Series {
  name: string;
  color: string;
  values: number[];
}

interface Props {
  labels: string[];
  series: Series[];
  unit?: string; // e.g. "$B"
}

const W = 640;
const H = 260;
const PAD = { top: 16, right: 20, bottom: 36, left: 52 };

/** Dependency-free SVG line chart: y-axis ticks, x labels, point markers, legend. */
export function LineChart({ labels, series, unit = "" }: Props) {
  const all = series.flatMap((s) => s.values);
  if (all.length === 0) return null;
  const min = Math.min(0, ...all);
  const max = Math.max(...all);
  const span = max - min || 1;
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (labels.length === 1 ? innerW / 2 : (i / (labels.length - 1)) * innerW);
  const y = (v: number) => PAD.top + innerH - ((v - min) / span) * innerH;
  const ticks = Array.from({ length: 5 }, (_, i) => min + (span * i) / 4);

  const summary = series.map((s) => `${s.name}: ${s.values.map((v) => v.toFixed(1)).join(", ")}`).join("; ");
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Line chart. ${summary}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" className="chart-axis">
              {t.toFixed(span < 10 ? 1 : 0)}
            </text>
          </g>
        ))}
        {labels.map((l, i) => (
          <text key={l} x={x(i)} y={H - 12} textAnchor="middle" className="chart-axis">
            {l}
          </text>
        ))}
        {series.map((s) => (
          <g key={s.name}>
            <polyline fill="none" stroke={s.color} strokeWidth={2.5} points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ")} />
            {s.values.map((v, i) => (
              <circle key={i} cx={x(i)} cy={y(v)} r={3.5} fill={s.color}>
                <title>{`${s.name}, ${labels[i]}: ${v.toFixed(2)}${unit}`}</title>
              </circle>
            ))}
          </g>
        ))}
      </svg>
      <figcaption className="chart-legend">
        {series.map((s) => (
          <span key={s.name}>
            <i style={{ background: s.color }} />
            {s.name}
          </span>
        ))}
        {unit && <span className="chart-unit">Values in {unit}</span>}
      </figcaption>
    </figure>
  );
}
