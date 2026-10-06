import type { AgentEvent, Job, StartResponse } from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryAfter?: number,
  ) {
    super(message);
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url, init);
  } catch {
    throw new ApiError("Cannot reach the server. Is the backend running?", 0);
  }
  if (!resp.ok) {
    let detail = `Request failed (${resp.status})`;
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = "Please enter a valid ticker symbol.";
    } catch {
      /* non-JSON error body */
    }
    const retry = resp.headers.get("Retry-After");
    throw new ApiError(detail, resp.status, retry ? Number(retry) : undefined);
  }
  return resp.json() as Promise<T>;
}

export function startAnalysis(ticker: string, refresh = false): Promise<StartResponse> {
  return request<StartResponse>("/api/analyses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, refresh }),
  });
}

export function getAnalysis(id: string): Promise<Job> {
  return request<Job>(`/api/analyses/${id}`);
}

export interface Subscription {
  close(): void;
}

const EVENT_TYPES = ["started", "tool_start", "tool_end", "reasoning", "memo", "done", "error"] as const;

/**
 * Follow a job's event stream. The server closes the stream after a terminal event; EventSource would
 * otherwise reconnect forever, so we close it ourselves on `done` / `error`.
 */
export function subscribe(
  id: string,
  onEvent: (event: AgentEvent) => void,
  onConnectionLost: () => void,
): Subscription {
  const source = new EventSource(`/api/analyses/${id}/events`);
  for (const type of EVENT_TYPES) {
    source.addEventListener(type, (e) => {
      const event = JSON.parse((e as MessageEvent).data) as AgentEvent;
      onEvent(event);
      if (event.type === "done" || event.type === "error") source.close();
    });
  }
  source.onerror = () => {
    // EventSource retries on its own (sending Last-Event-ID); only give up if it is fully closed.
    if (source.readyState === EventSource.CLOSED) onConnectionLost();
  };
  return { close: () => source.close() };
}
