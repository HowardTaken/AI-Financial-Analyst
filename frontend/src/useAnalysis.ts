import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getAnalysis, startAnalysis, subscribe, type Subscription } from "./api";
import { addToHistory, loadHistory } from "./storage";
import type { AgentEvent, AnalysisResult } from "./types";

export type Phase = "idle" | "running" | "done" | "error";

export interface Failure {
  message: string;
  code?: string;
  retryAfter?: number;
}

const POLL_MS = 2000;

/** Owns the whole analysis lifecycle: start, live event stream, result, errors, history. */
export function useAnalysis() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [ticker, setTicker] = useState("");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [history, setHistory] = useState<AnalysisResult[]>(() => loadHistory());

  const runId = useRef(0);
  const sub = useRef<Subscription | null>(null);
  const pollTimer = useRef<number | null>(null);

  const stopFollowing = useCallback(() => {
    sub.current?.close();
    sub.current = null;
    if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
    pollTimer.current = null;
  }, []);

  useEffect(() => stopFollowing, [stopFollowing]);

  const finish = useCallback((id: number, res: AnalysisResult) => {
    if (id !== runId.current) return;
    setResult(res);
    setPhase("done");
    setHistory((h) => addToHistory(h, res));
  }, []);

  const fail = useCallback((id: number, f: Failure) => {
    if (id !== runId.current) return;
    setFailure(f);
    setPhase("error");
  }, []);

  const start = useCallback(
    async (rawTicker: string, refresh = false) => {
      const symbol = rawTicker.trim().toUpperCase();
      if (!symbol) return;
      stopFollowing();
      const id = ++runId.current;
      setTicker(symbol);
      setEvents([]);
      setResult(null);
      setFailure(null);
      setPhase("running");

      try {
        const job = await startAnalysis(symbol, refresh);
        if (id !== runId.current) return;
        setTicker(job.ticker);

        const fetchOutcome = async () => {
          const j = await getAnalysis(job.id);
          if (j.status === "done" && j.result) finish(id, j.result);
          else if (j.status === "error") fail(id, { message: j.error ?? "Analysis failed.", code: j.error_code ?? undefined });
          else pollTimer.current = window.setTimeout(fetchOutcome, POLL_MS);
        };

        sub.current = subscribe(
          job.id,
          (event) => {
            if (id !== runId.current) return;
            setEvents((prev) => [...prev, event]);
            if (event.type === "done") void fetchOutcome().catch((e) => fail(id, { message: String(e.message ?? e) }));
            if (event.type === "error") fail(id, { message: event.message, code: event.code });
          },
          // The stream died for good: fall back to polling the job so the user still gets the result.
          () => void fetchOutcome().catch((e) => fail(id, { message: String(e.message ?? e) })),
        );
      } catch (e) {
        if (e instanceof ApiError) fail(id, { message: e.message, retryAfter: e.retryAfter });
        else fail(id, { message: "Something went wrong starting the analysis." });
      }
    },
    [fail, finish, stopFollowing],
  );

  /** Show a previously completed analysis from history without touching the server. */
  const show = useCallback(
    (entry: AnalysisResult) => {
      stopFollowing();
      runId.current++;
      setTicker(entry.ticker);
      setEvents([]);
      setFailure(null);
      setResult(entry);
      setPhase("done");
    },
    [stopFollowing],
  );

  return { phase, ticker, events, result, failure, history, start, show };
}
