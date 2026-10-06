# AI Market Analyst

![CI](https://github.com/HowardTaken/AI-Financial-Analyst/actions/workflows/ci.yml/badge.svg)

A tool-calling LLM agent that researches a public company and writes a structured Buy / Hold / Sell memo.
Give it a ticker; a Gemini agent decides which tools to call (fundamentals, DCF, SEC 10-K risk factors,
earnings-call summary, peer comparison), reads what comes back, and submits a schema-validated memo.

It ships with a Streamlit dashboard, a CLI, a 95-test offline suite, and an evaluation harness that
measures whether the signals are actually any good (spoiler: see [Evaluation](#evaluation)).

> Educational project. Not financial advice.

---

## How it works

```
                 ┌────────────────────────── Gemini (function calling) ──────────────────────────┐
  ticker ──────▶ │  loop: model picks tools → tools run (in parallel) → results fed back → repeat  │
                 └───────┬───────────────────────────────────────────────────────────────┬────────┘
                         │ calls                                                          │ finishes with
        ┌────────────────┼───────────────┬──────────────────┬──────────────────┐          ▼
 get_financial_metrics  run_dcf_valuation  get_risk_factors  get_earnings_call_  get_peer_   submit_memo(Memo)
 (Yahoo Finance)        (own DCF engine)   (SEC EDGAR 10-K)  summary (Search)    comparison  pydantic-validated
```

* **The model drives.** It always starts with fundamentals (to learn what kind of company it is), then
  issues independent calls together (executed concurrently), and can re-plan: skip the DCF for banks and
  use P/B and ROE instead, re-run the DCF with different assumptions as a scenario check, or reject
  Yahoo's default peers and supply real competitors itself.
* **Errors are observations.** A failed tool (no 10-K, quota hit, bad ticker) is returned to the model as
  data; it notes the gap and lowers its confidence instead of the run crashing.
* **Structured output, no regex.** The final action is a `submit_memo` tool call validated against a
  pydantic schema. Invalid memos are rejected with the validation error so the model can fix them.
* **Guardrails in code.** After the run, deterministic checks compare the memo with the numbers the tools
  actually returned (e.g. "BUY but the DCF implies -82% downside", "price target below price on a BUY",
  "earnings summary has no cited sources") and surface warnings in the UI.
* **Bounded.** Step budget with a forced final `submit_memo`; tickers validated; tool output treated as
  untrusted data in the system prompt; model output never rendered as raw HTML.

### Tools

| Tool | What it does |
|---|---|
| `get_financial_metrics` | Yahoo Finance statements → price, TTM P/E, D/E, gross margin, revenue growth, P/B, ROE |
| `run_dcf_valuation` | Unlevered-FCF DCF with CAPM WACC; accepts scenario overrides; returns upside, terminal-value share, sensitivity grid |
| `get_risk_factors` | Latest 10-K from SEC EDGAR → clean Item 1A text |
| `get_earnings_call_summary` | Gemini + Google Search grounding → sectioned summary **with cited source URLs** |
| `get_peer_comparison` | Yahoo industry peers (or model-chosen tickers) with market caps and peer medians |
| `submit_memo` | Terminal action; schema-validated structured memo |

### Example run (condensed from a real AAPL run, 2026-10-06)

```
  -> get_financial_metrics
  ok  get_financial_metrics (1.2s): AAPL: price 332.89, P/E 38.18x, Consumer Electronics
  -> run_dcf_valuation   -> get_risk_factors   -> get_earnings_call_summary   -> get_peer_comparison
  ok  run_dcf_valuation (0.0s): AAPL: intrinsic $66.46 vs $332.89 (-80.0% upside, WACC 10.6%)
  ok  get_risk_factors (1.5s): AAPL: 10-K 0000320193-25-000079, 70,800 chars (truncated for the model)
  ok  get_earnings_call_summary (22.1s): AAPL: 5,028 chars, 7 sources
  ok  get_peer_comparison (1.0s): 4/4 peers (top companies in Yahoo's 'Consumer Electronics' industry): SONO, FXHO, TBCH, UEIC
  -> get_peer_comparison                     # the model judged those peers poor matches and re-called with its own
  ok  get_peer_comparison (1.2s): 3/3 peers (chosen by the analyst): MSFT, GOOGL, AMZN
  ok  submit_memo (0.0s): HOLD (MEDIUM confidence)
```

> Apple trades at a premium P/E of 38.18x compared to a peer median of 20.24x, and an exceptionally high
> Price/Book of 66.7x versus the peer median of 8.82x ... The DCF suggests an intrinsic value of $66.46,
> implying an 80.04% downside ... the DCF may not fully capture Apple's growth potential.

Typical runtime is 50-100 s, dominated by the grounded web search (which occasionally takes minutes; it is now capped at 90 s, after which the agent proceeds without it). The agent also correctly skips the DCF
for banks (JPM: used P/B, ROE and bank peers BAC/RY/WFC/C) and flags when it rates against the DCF (NVDA).

---

## Valuation methodology

All in [analyst/valuation.py](analyst/valuation.py): pure functions, no I/O, unit-tested against a
hand-calculated reference.

* **Unlevered FCF**: reported FCF plus after-tax interest, so discounting at WACC and then subtracting net
  debt doesn't double-count debt.
* **WACC from CAPM**: `risk-free (live 10y, ^TNX) + beta × 5% ERP`, blended with after-tax cost of debt at
  market-value weights; beta clamped to [0.6, 2.0], WACC to [6%, 14%], and every clamp is reported.
* **Growth fades**: starts at the historical FCF CAGR (capped at +10% / floored at -10%) and fades linearly
  to the terminal rate (2%) by year 5, rather than compounding a high rate and then dropping off a cliff.
* **EV → equity → per share** via net debt and share count.
* **Always reported**: terminal-value share of EV, a 5×5 WACC × terminal-growth sensitivity grid, and warnings
  (SBC not deducted, negative-FCF years, capped growth). *Upside* (`value / price − 1`) and *margin of
  safety* (`(value − price) / value`) are shown separately and labelled, since they are easy to confuse.
* **Not applicable, with a reason**, for banks/insurers and negative FCF. Unexpected errors are **not**
  swallowed (an earlier version caught every exception and reported it as "financial institution").

---

## Evaluation

An LLM stock-rater is only interesting if you measure it, so there are two harnesses.

**1. Point-in-time backtest of the DCF signal** (`python -m analyst.backtest --asof 2024-04-01 --asof 2025-04-01`)

Statements are filtered to what was public at the as-of date (90-day reporting lag, unit-tested against
look-ahead) and DCF upside is compared with the next 12 months of return vs SPY, on 61 large caps.
Result from the run on 2026-10-06:

| Observations | Info. coefficient (Spearman) | Top-third excess return | Bottom-third excess return | Median DCF upside |
|---|---|---|---|---|
| 100 (22 skipped) | **+0.03** | -1.0% | -1.6% | **-40%** |

**Honest reading:** no detectable predictive power (with n=100 the noise on an IC is about ±0.1), and the
model calls the median stock 40% overvalued. A mechanical FCF-extrapolation DCF is a poor standalone
signal, which is why the agent is told to treat large gaps as a possible model limitation and to run scenarios.
Caveats: today's large-cap universe (survivorship/size bias), only two as-of dates are possible with ~4 years
of Yahoo statements, beta and share count are not point-in-time.

**2. Forward test of the agent's real ratings** (`python -m analyst.evaluate`)

The LLM itself can't be backtested honestly (its training data, web search and Yahoo all contain the
future). Instead every rating is appended to `data/predictions.jsonl` at the moment it is issued; the
evaluator scores BUY/SELL calls against SPY once they are ≥30 days old. No look-ahead is possible.
This needs time and dozens of ratings before it means anything; there are no results to report yet.

---

## Engineering notes

* **95 offline tests** (`pytest`): DCF vs hand calculation, bank/negative-FCF/zero-debt edge cases, SEC parser
  on synthetic filings, the agent loop driven by a **scripted fake LLM** (parallel calls, invalid-memo retry,
  tool failure, step-budget forcing, never-submits), look-ahead guard, history/JSON round-trips, and headless
  Streamlit `AppTest` runs including "every metric missing". CI runs ruff + pytest on every push.
* **SEC parsing**: heading detection is structural, with no per-company rules; it handles split headings
  (`ITEM 1A. RIS` / `K FACTORS`), dash variants, TOC rows, and inline "see Item 1A" cross-references.
  Extracted correctly for 24 of 26 large-cap filers tried; INTC (non-standard layout) and XOM (SEC maps the
  ticker to a new registrant with no 10-K yet) fail *loudly* rather than returning wrong text.
* **Reliability**: TTL caches, SEC rate-limit throttle + retries, Gemini retry with exponential backoff,
  90 s timeout on web-search grounding, per-tool error isolation, atomic history writes.
* **Security/privacy**: tickers validated; secrets via `.env`/Streamlit secrets; history is per-session by
  default (set `ANALYST_PERSIST_HISTORY=1` for local persistence, never on a shared deployment);
  LLM text is not rendered as HTML.

---

## Limitations

* The DCF is mechanical and backward-looking; see the backtest. Treat it as one input.
* The earnings-call "transcript" is an LLM summary assembled from web search, not a verbatim transcript.
  The UI shows cited sources and warns when there are none; quotes can still be wrong.
* Yahoo's industry peers are often poor matches; the agent checks and substitutes, but its own picks are
  model judgement.
* Only annual statements (~4 years) from Yahoo Finance, a free unofficial source that can be flaky.
* 10-K extraction is heuristic (see above). Foreign issuers (20-F/40-F) aren't supported.
* The memo is only as good as Gemini 2.5 Flash; a 429 (free-tier quota) fails the run with a clear message.
* No stock-based-compensation deduction by default, no forward estimates, no sector-specific models.

---

## Setup

```bash
git clone https://github.com/HowardTaken/AI-Financial-Analyst.git
cd AI-Financial-Analyst
python -m venv venv && source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:

```env
GEMINI_API_KEY=your_key              # required: https://aistudio.google.com
SEC_USER_AGENT=YourApp you@email.com # recommended: SEC asks for a real contact address
ANALYST_PERSIST_HISTORY=1            # optional: keep history across restarts (local use only)
ANALYST_MODEL=gemini-2.5-flash       # optional
```

```bash
streamlit run app.py                 # web dashboard
python main.py AAPL NVDA             # CLI (or `python main.py` for a prompt)
pip install -r requirements-dev.txt && pytest && ruff check .
python -m analyst.backtest --asof 2024-04-01 --asof 2025-04-01
python -m analyst.evaluate
```

On Streamlit Cloud set the same keys in the Secrets dashboard.

## Project structure

```
app.py                  Streamlit UI (rendering only)
main.py                 CLI
assets/style.css        Dashboard styling
analyst/
  agent.py              Function-calling loop, system prompt, forced-submit fallback
  tools.py              Tool implementations, JSON-schema declarations, parallel dispatcher
  models.py             Typed dataclasses + the pydantic Memo schema
  valuation.py          Metrics, WACC, DCF, sensitivity (pure)
  market_data.py        Yahoo Finance access, peers, risk-free rate
  sec.py                EDGAR: CIK → 10-K → Item 1A extraction
  transcripts.py        Grounded earnings-call summary + section parser
  guardrails.py         Deterministic memo-vs-data checks
  llm.py                Gemini client with retry/backoff
  pipeline.py           Single entry point used by UI and CLI
  history.py            Session/optional on-disk history
  predictions.py        Append-only log of every rating
  backtest.py           Point-in-time DCF backtest
  evaluate.py           Forward test of logged ratings vs SPY
  formatting.py         Presentation helpers (UI/CLI shared, testable)
  cache.py config.py
tests/                  95 offline tests
```
