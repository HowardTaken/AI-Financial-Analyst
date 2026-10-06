import type { AnalysisResult } from "./types";

// History lives in the visitor's own browser. The server keeps results for an hour at most and never
// lists them, so this is also what keeps one visitor's research private from another's.
const KEY = "analyst.history.v1";
export const MAX_HISTORY = 10;

function isResult(x: unknown): x is AnalysisResult {
  const r = x as AnalysisResult;
  return !!r && typeof r.ticker === "string" && !!r.memo && typeof r.memo.rating === "string" && Array.isArray(r.peers);
}

export function loadHistory(storage: Storage = localStorage): AnalysisResult[] {
  try {
    const parsed = JSON.parse(storage.getItem(KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter(isResult) : [];
  } catch {
    return [];
  }
}

/** Newest first, one entry per ticker, capped. Returns the new list (also persisted when possible). */
export function addToHistory(
  history: AnalysisResult[],
  result: AnalysisResult,
  storage: Storage = localStorage,
): AnalysisResult[] {
  const slim = { ...result, filing_excerpt: "" }; // keep localStorage small
  const next = [slim, ...history.filter((h) => h.ticker !== result.ticker)].slice(0, MAX_HISTORY);
  try {
    storage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage full or disabled: history just won't persist */
  }
  return next;
}

export function clearHistory(storage: Storage = localStorage): void {
  try {
    storage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
