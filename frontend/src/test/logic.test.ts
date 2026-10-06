import { describe, expect, it } from "vitest";
import { fmt, fmtBig, median, memoToMarkdown, parseBlocks, parseInline, parseSections, peerMedians, rankCells, safeHttpUrl } from "../format";
import { addToHistory, loadHistory, MAX_HISTORY } from "../storage";
import { buildTimeline, describeError } from "../timeline";
import type { AgentEvent } from "../types";
import { result } from "./fixtures";

function memoryStorage(initial: Record<string, string> = {}): Storage {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
    removeItem: (k) => void data.delete(k),
    clear: () => data.clear(),
    key: (i) => [...data.keys()][i] ?? null,
    get length() { return data.size; },
  };
}

describe("fmt", () => {
  it("renders missing values as N/A, never 'null' or 'NaN'", () => {
    expect(fmt(null)).toBe("N/A");
    expect(fmt(undefined)).toBe("N/A");
    expect(fmt(NaN)).toBe("N/A");
    expect(fmt(Infinity)).toBe("N/A");
  });
  it("treats zero as a value", () => expect(fmt(0, { decimals: 1, suffix: "%" })).toBe("0.0%"));
  it("formats prefixes, thousands and signs", () => {
    expect(fmt(1234.5, { prefix: "$" })).toBe("$1,234.50");
    expect(fmt(-5.25, { prefix: "$" })).toBe("-$5.25");
    expect(fmt(3.14159, { decimals: 1, suffix: "%", signed: true })).toBe("+3.1%");
  });
  it("abbreviates large numbers", () => {
    expect(fmtBig(1.234e12)).toBe("$1.2T");
    expect(fmtBig(-5.6e9)).toBe("-$5.6B");
    expect(fmtBig(250e6)).toBe("$250M");
    expect(fmtBig(null)).toBe("N/A");
  });
});

describe("safeHttpUrl", () => {
  it("allows http(s) and rejects script-capable schemes", () => {
    expect(safeHttpUrl("https://example.com/a")).toBe("https://example.com/a");
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull();
    expect(safeHttpUrl("data:text/html,<script>")).toBeNull();
    expect(safeHttpUrl("not a url")).toBeNull();
  });
});

describe("text parsing", () => {
  it("splits earnings summaries on numbered headings and keeps a preamble", () => {
    const s = parseSections(result.earnings!.text);
    expect(s.map((x) => x.heading)).toEqual(["Call Overview", "Opening Remarks & Results", "Forward Guidance"]);
    expect(s[1].body).toBe("- Revenue up");
  });
  it("falls back to one block without headings", () => {
    expect(parseSections("just prose")).toEqual([{ heading: "Earnings Call Summary", body: "just prose" }]);
  });
  it("parses paragraphs and bullet lists", () => {
    expect(parseBlocks("Intro\n- a\n* b\n\nOutro")).toEqual([
      { kind: "p", text: "Intro" }, { kind: "ul", items: ["a", "b"] }, { kind: "p", text: "Outro" },
    ]);
  });
  it("parses bold and leaves HTML as inert text", () => {
    expect(parseInline("a **b** <script>")).toEqual([
      { text: "a ", bold: false }, { text: "b", bold: true }, { text: " <script>", bold: false },
    ]);
  });
});

describe("memoToMarkdown", () => {
  it("includes every section", () => {
    const md = memoToMarkdown("TEST", result.memo, ["careful"]);
    for (const needle of ["# TEST: BUY (Medium confidence)", "$130.00", "## Quantitative case", "## Key risks", "- Competition",
      "## Catalysts", "## Verdict", "## Data gaps", "careful", "not financial advice"]) {
      expect(md).toContain(needle);
    }
  });
});

describe("peer ranking", () => {
  it("marks best and worst respecting direction", () => {
    expect(rankCells([10, 20, 30], true)).toEqual({ best: [2], worst: [0] });
    expect(rankCells([10, 20, 30], false)).toEqual({ best: [0], worst: [2] });
  });
  it("makes no judgement for ties, single values, nulls or neutral rows", () => {
    expect(rankCells([5, 5], true)).toEqual({ best: [], worst: [] });
    expect(rankCells([5, null], true)).toEqual({ best: [], worst: [] });
    expect(rankCells([1, 2], null)).toEqual({ best: [], worst: [] });
  });
  it("computes medians ignoring nulls and failed peers", () => {
    expect(median([1, 3, null, 2])).toBe(2);
    expect(median([1, 2, 3, 4])).toBe(2.5);
    expect(median([null])).toBeNull();
    expect(peerMedians(result.peers).pe_ratio).toBe(30); // only the successful peer counts
  });
});

describe("history storage", () => {
  it("round-trips, dedupes by ticker and strips the bulky excerpt", () => {
    const s = memoryStorage();
    let h = addToHistory([], result, s);
    h = addToHistory(h, { ...result, elapsed_seconds: 99 }, s);
    expect(h).toHaveLength(1);
    const loaded = loadHistory(s);
    expect(loaded[0].elapsed_seconds).toBe(99);
    expect(loaded[0].filing_excerpt).toBe("");
  });
  it("caps the list, newest first", () => {
    const s = memoryStorage();
    let h: typeof result[] = [];
    for (let i = 0; i < MAX_HISTORY + 5; i++) h = addToHistory(h, { ...result, ticker: `T${i}` }, s);
    expect(h).toHaveLength(MAX_HISTORY);
    expect(h[0].ticker).toBe(`T${MAX_HISTORY + 4}`);
  });
  it("survives corrupt, wrong-shaped or unavailable storage", () => {
    expect(loadHistory(memoryStorage({ "analyst.history.v1": "{not json" }))).toEqual([]);
    expect(loadHistory(memoryStorage({ "analyst.history.v1": JSON.stringify([{ nope: 1 }, result]) }))).toHaveLength(1);
    const throwing = { ...memoryStorage(), setItem: () => { throw new Error("quota"); } } as Storage;
    expect(() => addToHistory([], result, throwing)).not.toThrow();
  });
});

describe("timeline", () => {
  const events: AgentEvent[] = [
    { type: "started", ticker: "T", t: 0 },
    { type: "tool_start", tool: "get_financial_metrics", args: {}, t: 0.1 },
    { type: "tool_end", tool: "get_financial_metrics", ok: true, summary: "done", seconds: 1, t: 1.1 },
    { type: "tool_start", tool: "run_dcf_valuation", args: {}, t: 1.2 },
    { type: "tool_start", tool: "get_risk_factors", args: {}, t: 1.2 },
    { type: "tool_end", tool: "get_risk_factors", ok: false, summary: "no 10-K", seconds: 0.5, t: 1.7 },
  ];
  it("shows parallel calls as simultaneous running rows and pairs completions by tool", () => {
    const rows = buildTimeline(events);
    expect(rows.map((r) => (r.kind === "tool" ? `${r.tool}:${r.status}` : r.kind))).toEqual([
      "get_financial_metrics:ok", "run_dcf_valuation:running", "get_risk_factors:failed",
    ]);
  });
  it("completes the earliest running call when the same tool is called twice", () => {
    const rows = buildTimeline([
      { type: "tool_start", tool: "get_peer_comparison", args: {}, t: 0 },
      { type: "tool_end", tool: "get_peer_comparison", ok: true, summary: "first", seconds: 1, t: 1 },
      { type: "tool_start", tool: "get_peer_comparison", args: {}, t: 2 },
    ]);
    expect(rows.map((r) => r.kind === "tool" && r.status)).toEqual(["ok", "running"]);
  });
  it("explains known error codes", () => {
    expect(describeError("llm_quota", "x")).toMatch(/quota/i);
    expect(describeError("unknown", "boom")).toBe("boom");
  });
});
