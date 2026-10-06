import type { Memo, Metrics, Peer } from "./types";

export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

interface NumOpts {
  decimals?: number;
  prefix?: string;
  suffix?: string;
  signed?: boolean;
  na?: string;
}

/** Format a number, returning "N/A" for null/undefined/NaN so missing data never renders as "null". */
export function fmt(v: number | null | undefined, o: NumOpts = {}): string {
  if (!isNum(v)) return o.na ?? "N/A";
  const { decimals = 2, prefix = "", suffix = "", signed = false } = o;
  const body = Math.abs(v).toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  const sign = v < 0 ? "-" : signed && v > 0 ? "+" : "";
  return `${sign}${prefix}${body}${suffix}`;
}

/** 1.234e12 -> "$1.23T", 5.6e9 -> "$5.6B". */
export function fmtBig(v: number | null | undefined): string {
  if (!isNum(v)) return "N/A";
  const abs = Math.abs(v);
  const units: [number, string][] = [[1e12, "T"], [1e9, "B"], [1e6, "M"]];
  for (const [size, label] of units) {
    if (abs >= size) return `${v < 0 ? "-" : ""}$${(abs / size).toFixed(abs / size >= 100 ? 0 : 1)}${label}`;
  }
  return fmt(v, { decimals: 0, prefix: "$" });
}

/** Only http(s) links are rendered as links; anything else (javascript:, data:) is dropped. */
export function safeHttpUrl(uri: string): string | null {
  try {
    const u = new URL(uri);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

export interface Section {
  heading: string;
  body: string;
}

/** Split an earnings summary on its "## n. Title" headings (mirrors analyst/transcripts.py). */
export function parseSections(text: string): Section[] {
  const parts = text.split(/^##\s*\d*\.?\s*(.+?)\s*$/m);
  // [preamble, title1, body1, title2, body2, ...]
  const sections: Section[] = [];
  for (let i = 1; i + 1 < parts.length; i += 2) {
    const body = parts[i + 1].trim();
    if (body) sections.push({ heading: parts[i].trim(), body });
  }
  if (sections.length === 0) return [{ heading: "Earnings Call Summary", body: text.trim() }];
  const preamble = parts[0].trim();
  if (preamble) sections.unshift({ heading: "Call Overview", body: preamble });
  return sections;
}

export type Block = { kind: "p"; text: string } | { kind: "ul"; items: string[] };

/** A tiny markdown subset (paragraphs + bullet lists). Rendered through React, so it is XSS-safe. */
export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let list: string[] | null = null;
  const flush = () => {
    if (list) blocks.push({ kind: "ul", items: list });
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = /^([-*•])\s+(.*)$/.exec(line);
    if (bullet) {
      (list ??= []).push(bullet[2]);
    } else if (line === "") {
      flush();
    } else {
      flush();
      blocks.push({ kind: "p", text: line });
    }
  }
  flush();
  return blocks;
}

/** Split text on **bold** markers: [{text, bold}]. */
export function parseInline(text: string): { text: string; bold: boolean }[] {
  return text
    .split(/(\*\*[^*]+\*\*)/g)
    .filter(Boolean)
    .map((t) => (t.startsWith("**") && t.endsWith("**") ? { text: t.slice(2, -2), bold: true } : { text: t, bold: false }));
}

export function memoToMarkdown(ticker: string, memo: Memo, warnings: string[] = []): string {
  const title = memo.confidence.charAt(0) + memo.confidence.slice(1).toLowerCase();
  const lines = [`# ${ticker}: ${memo.rating} (${title} confidence)`, "", `**${memo.headline}**`, ""];
  if (isNum(memo.price_target)) lines.push(`**12-month price target:** ${fmt(memo.price_target, { prefix: "$" })}`, "");
  lines.push("## Quantitative case", memo.quantitative_case, "", "## 10-K vs. earnings call", memo.filing_vs_call, "");
  if (memo.key_risks.length) lines.push("## Key risks", ...memo.key_risks.map((r) => `- ${r}`), "");
  if (memo.catalysts.length) lines.push("## Catalysts", ...memo.catalysts.map((c) => `- ${c}`), "");
  lines.push("## Verdict", memo.verdict, "");
  if (memo.data_gaps.length) lines.push("## Data gaps", ...memo.data_gaps.map((g) => `- ${g}`), "");
  if (warnings.length) lines.push("## Automated checks", ...warnings.map((w) => `- ${w}`), "");
  lines.push("*Educational research only; not financial advice.*");
  return lines.join("\n");
}

// ── Peer table ────────────────────────────────────────────────────────────────

export interface PeerRow {
  label: string;
  key: keyof Metrics;
  kind: "money" | "pct" | "x" | "plain";
  higherIsBetter: boolean | null; // null: no judgement (e.g. price)
}

export const PEER_ROWS: PeerRow[] = [
  { label: "Price", key: "current_price", kind: "money", higherIsBetter: null },
  { label: "P/E", key: "pe_ratio", kind: "x", higherIsBetter: false },
  { label: "Gross margin", key: "gross_margin_pct", kind: "pct", higherIsBetter: true },
  { label: "Revenue growth", key: "yoy_revenue_growth_pct", kind: "pct", higherIsBetter: true },
  { label: "Debt / equity", key: "debt_to_equity", kind: "plain", higherIsBetter: false },
  { label: "Price / book", key: "price_to_book", kind: "x", higherIsBetter: false },
  { label: "ROE", key: "roe_pct", kind: "pct", higherIsBetter: true },
];

export function fmtByKind(v: number | null | undefined, kind: PeerRow["kind"]): string {
  switch (kind) {
    case "money": return fmt(v, { prefix: "$" });
    case "pct": return fmt(v, { decimals: 1, suffix: "%", signed: true });
    case "x": return fmt(v, { decimals: 1, suffix: "x" });
    default: return fmt(v);
  }
}

/** For one metric across columns, which indexes are best / worst (none when all equal or <2 values). */
export function rankCells(values: (number | null)[], higherIsBetter: boolean | null): { best: number[]; worst: number[] } {
  const present = values.filter(isNum);
  if (higherIsBetter === null || present.length < 2) return { best: [], worst: [] };
  const hi = Math.max(...present);
  const lo = Math.min(...present);
  if (hi === lo) return { best: [], worst: [] };
  const bestVal = higherIsBetter ? hi : lo;
  const worstVal = higherIsBetter ? lo : hi;
  const idx = (target: number) => values.map((v, i) => (v === target ? i : -1)).filter((i) => i >= 0);
  return { best: idx(bestVal), worst: idx(worstVal) };
}

export function median(values: (number | null | undefined)[]): number | null {
  const v = values.filter(isNum).sort((a, b) => a - b);
  if (v.length === 0) return null;
  const mid = Math.floor(v.length / 2);
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}

export function peerMedians(peers: Peer[]): Partial<Record<keyof Metrics, number | null>> {
  const ok = peers.filter((p) => p.metrics);
  const out: Partial<Record<keyof Metrics, number | null>> = {};
  for (const row of PEER_ROWS) out[row.key] = median(ok.map((p) => p.metrics![row.key] as number | null));
  return out;
}
