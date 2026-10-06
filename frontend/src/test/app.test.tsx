import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { Results } from "../components/Results";
import type { AgentEvent, AnalysisResult } from "../types";
import { result, sparse } from "./fixtures";

// ── A controllable EventSource ───────────────────────────────────────────────
class FakeEventSource {
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];
  readyState = 1;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, ((e: MessageEvent) => void)[]>();
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }
  close() {
    this.readyState = FakeEventSource.CLOSED;
  }
  emit(event: AgentEvent) {
    for (const fn of this.listeners.get(event.type) ?? []) fn({ data: JSON.stringify(event) } as MessageEvent);
  }
}

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } }));
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const job = (status: string, extra: object = {}) => ({
  id: "job1", ticker: "TEST", status, created_at: 0, finished_at: null, error: null, error_code: null, result: null, ...extra,
});

async function submit(ticker: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Ticker symbol"), ticker);
  await user.click(screen.getByRole("button", { name: /run analysis/i }));
}

describe("App end to end (mocked backend)", () => {
  it("streams agent activity live, then shows the memo and saves it to history", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/analyses" && init?.method === "POST") return jsonResponse({ id: "job1", ticker: "TEST", status: "queued", cached: false }, 202);
      if (url === "/api/analyses/job1") return jsonResponse(job("done", { result }));
      throw new Error(`unexpected fetch ${url}`);
    });
    render(<App />);
    await submit("test");

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const es = FakeEventSource.instances[0];
    expect(es.url).toBe("/api/analyses/job1/events");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ ticker: "TEST", refresh: false });

    // Two tools start together (parallel), then one finishes.
    act(() => {
      es.emit({ type: "tool_start", tool: "get_financial_metrics", args: {}, t: 0 });
      es.emit({ type: "tool_start", tool: "run_dcf_valuation", args: {}, t: 0 });
      es.emit({ type: "tool_end", tool: "get_financial_metrics", ok: true, summary: "TEST: price 100", seconds: 1.2, t: 1.2 });
    });
    expect(await screen.findByText(/Agent researching TEST/)).toBeInTheDocument();
    expect(screen.getByText("TEST: price 100")).toBeInTheDocument();
    expect(screen.getByText("Running DCF valuation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /researching/i })).toBeDisabled();

    act(() => es.emit({ type: "done", t: 5 }));
    expect(await screen.findByText("Strong franchise at a fair price.")).toBeInTheDocument();
    expect(es.readyState).toBe(FakeEventSource.CLOSED); // we close the stream ourselves; no reconnect loop
    expect(within(screen.getByRole("main")).getByText("BUY")).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("analyst.history.v1")!)[0].ticker).toBe("TEST");
    expect(within(screen.getByRole("complementary")).getByText("TEST")).toBeInTheDocument();
  });

  it("shows a helpful message when the agent fails", async () => {
    fetchMock.mockImplementation(() => jsonResponse({ id: "job1", ticker: "TEST", status: "queued", cached: false }, 202));
    render(<App />);
    await submit("TEST");
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => FakeEventSource.instances[0].emit({ type: "error", code: "llm_quota", message: "quota", t: 3 }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/quota is exhausted/i);
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("surfaces rate limiting from the API", async () => {
    fetchMock.mockImplementation(() => jsonResponse({ detail: "Rate limit reached. Try again in 120 seconds." }, 429, { "Retry-After": "120" }));
    render(<App />);
    await submit("TEST");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/rate limit reached/i);
    expect(alert).toHaveTextContent(/120s/);
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("reports an unreachable backend instead of hanging", async () => {
    fetchMock.mockRejectedValue(new TypeError("network"));
    render(<App />);
    await submit("TEST");
    expect(await screen.findByRole("alert")).toHaveTextContent(/cannot reach the server/i);
  });

  it("restores a previous analysis from history without calling the server", async () => {
    localStorage.setItem("analyst.history.v1", JSON.stringify([result]));
    render(<App />);
    await userEvent.setup().click(screen.getByRole("button", { name: /TEST/ }));
    expect(await screen.findByText("Strong franchise at a fair price.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("falls back to polling if the event stream dies for good", async () => {
    let polls = 0;
    fetchMock.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") return jsonResponse({ id: "job1", ticker: "TEST", status: "queued", cached: false }, 202);
      polls++;
      return jsonResponse(job("done", { result }));
    });
    render(<App />);
    await submit("TEST");
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const es = FakeEventSource.instances[0];
    es.readyState = FakeEventSource.CLOSED;
    act(() => es.onerror?.());
    expect(await screen.findByText("Strong franchise at a fair price.")).toBeInTheDocument();
    expect(polls).toBe(1);
  });
});

describe("Results rendering", () => {
  it("renders every tab for a full result", async () => {
    render(<Results result={result} />);
    const user = userEvent.setup();
    expect(screen.getByText("Check the DCF")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /valuation/i }));
    expect(screen.getByText("$120.00")).toBeInTheDocument();
    expect(screen.getByText(/20.0% implied upside/)).toBeInTheDocument();
    expect(screen.getByText("n/a")).toBeInTheDocument(); // a sensitivity cell the model could not compute
    expect(screen.getByRole("img", { name: /line chart/i })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /earnings/i }));
    expect(screen.getByRole("link", { name: "Good source" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByText("Evil source")).not.toBeInTheDocument(); // javascript: link dropped

    await user.click(screen.getByRole("tab", { name: /peers/i }));
    expect(screen.getByText(/Skipped: BAD/)).toBeInTheDocument();
    expect(screen.getByText("$500B")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /agent/i }));
    expect(screen.getByText("get_financial_metrics")).toBeInTheDocument();
  });

  it("never renders null/undefined/NaN when data is missing", async () => {
    const { container } = render(<Results result={sparse} />);
    const user = userEvent.setup();
    for (const name of [/valuation/i, /earnings/i, /peers/i, /agent/i, /memo/i]) {
      await user.click(screen.getByRole("tab", { name }));
      expect(container.textContent).not.toMatch(/\b(null|undefined|NaN)\b/);
    }
  });

  it("explains when a DCF is not applicable and offers P/B and ROE instead", async () => {
    const bank: AnalysisResult = { ...result, dcf: { ...result.dcf!, available: false, reason: "Not meaningful for banks." } };
    render(<Results result={bank} />);
    await userEvent.setup().click(screen.getByRole("tab", { name: /valuation/i }));
    expect(screen.getByText(/DCF not applicable/)).toBeInTheDocument();
    expect(screen.getByText("Price / book")).toBeInTheDocument();
  });

  it("renders LLM text as inert text, never as HTML", () => {
    const hostile = { ...result, memo: { ...result.memo, headline: "<img src=x onerror=alert(1)>", verdict: "<script>alert(1)</script>" } };
    const { container } = render(<Results result={hostile} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
  });
});
