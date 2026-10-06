"""Typed data models shared across the data, valuation, agent and UI layers."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# period (ISO date string) -> line item -> value
Statement = dict[str, dict[str, float | None]]


@dataclass
class FinancialData:
    ticker: str
    current_price: float | None
    income_statement: Statement
    balance_sheet: Statement
    cash_flow: Statement
    beta: float | None = None
    trailing_eps: float | None = None
    shares_outstanding: float | None = None
    market_cap: float | None = None
    sector: str = "Unknown"
    industry: str = "Unknown"
    industry_key: str | None = None
    risk_free_rate: float | None = None


@dataclass
class Metrics:
    ticker: str
    fiscal_year: str
    prior_year: str
    current_price: float | None
    pe_ratio: float | None = None
    eps_basis: str = "annual"  # "TTM" when Yahoo's trailing EPS was used
    debt_to_equity: float | None = None
    gross_margin_pct: float | None = None
    yoy_revenue_growth_pct: float | None = None
    price_to_book: float | None = None
    roe_pct: float | None = None
    diluted_eps: float | None = None
    total_debt: float | None = None
    stockholders_equity: float | None = None
    gross_profit: float | None = None
    net_income: float | None = None
    revenue_current: float | None = None
    revenue_prior: float | None = None


@dataclass
class DCFResult:
    available: bool
    reason: str = ""
    ticker: str = ""
    wacc_pct: float = 0.0
    cost_of_equity_pct: float = 0.0
    terminal_growth_pct: float = 0.0
    raw_growth_pct: float = 0.0       # historical FCF growth before capping
    starting_growth_pct: float = 0.0  # growth used in year 1 (fades to terminal)
    fcf_history: dict[str, float] = field(default_factory=dict)
    base_fcf: float = 0.0             # unlevered FCF the projection starts from
    projected_fcf: list[float] = field(default_factory=list)
    pv_projected_fcf: list[float] = field(default_factory=list)
    terminal_value: float = 0.0
    pv_terminal_value: float = 0.0
    terminal_value_share_pct: float = 0.0
    enterprise_value: float = 0.0
    net_debt: float = 0.0
    equity_value: float = 0.0
    shares_outstanding: float = 0.0
    intrinsic_value: float = 0.0
    current_price: float | None = None
    upside_pct: float | None = None             # intrinsic / price - 1
    margin_of_safety_pct: float | None = None   # (intrinsic - price) / intrinsic
    sensitivity: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def unavailable(cls, reason: str, ticker: str = "") -> DCFResult:
        return cls(available=False, reason=reason, ticker=ticker)


@dataclass
class Peer:
    ticker: str
    name: str = ""
    market_weight: float = 0.0
    market_cap: float | None = None
    metrics: Metrics | None = None
    error: str | None = None


@dataclass
class EarningsSummary:
    ticker: str
    text: str
    sources: list[dict[str, str]] = field(default_factory=list)  # [{"title", "uri"}]

    @property
    def is_grounded(self) -> bool:
        return bool(self.sources)


@dataclass
class SecFiling:
    ticker: str
    accession: str
    section: str
    text: str


class Memo(BaseModel):
    """Structured investment memo. Also serves as the schema of the agent's submit_memo tool."""

    rating: Literal["BUY", "HOLD", "SELL"]
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = Field(
        description="How strongly the evidence supports the rating."
    )
    price_target: float | None = Field(
        default=None, description="12-month price target in USD, if one can be justified."
    )
    headline: str = Field(description="One-sentence summary of the call.")
    quantitative_case: str = Field(
        description="Valuation, margins, growth, leverage and peer positioning, citing tool numbers."
    )
    filing_vs_call: str = Field(
        description="Compare risks disclosed in the 10-K with management's tone on the earnings call."
    )
    key_risks: list[str] = Field(description="Top risks to the thesis.")
    catalysts: list[str] = Field(description="Potential positive catalysts.")
    verdict: str = Field(description="Final recommendation and what would change it.")
    data_gaps: list[str] = Field(
        default_factory=list,
        description="Data that was unavailable, unverified or not applicable (e.g. DCF for a bank).",
    )

    @field_validator("rating", "confidence", mode="before")
    @classmethod
    def _upper(cls, v):
        return v.strip().upper() if isinstance(v, str) else v

    def word_count(self) -> int:
        text = " ".join(
            [self.headline, self.quantitative_case, self.filing_vs_call, self.verdict]
            + self.key_risks + self.catalysts
        )
        return len(text.split())


@dataclass
class TraceStep:
    step: int
    tool: str
    args: dict[str, Any]
    ok: bool
    seconds: float
    summary: str


@dataclass
class AnalysisContext:
    """Mutable state the agent's tools write into; the UI renders from it afterwards."""

    ticker: str
    data: FinancialData | None = None
    metrics: Metrics | None = None
    dcf: DCFResult | None = None
    filing: SecFiling | None = None
    earnings: EarningsSummary | None = None
    peers: list[Peer] = field(default_factory=list)
    other_metrics: dict[str, Metrics] = field(default_factory=dict)
    memo: Memo | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


@dataclass
class AnalysisResult:
    ticker: str
    memo: Memo
    metrics: Metrics | None
    dcf: DCFResult | None
    earnings: EarningsSummary | None
    peers: list[Peer]
    filing_excerpt: str = ""
    trace: list[TraceStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["memo"] = self.memo.model_dump()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AnalysisResult:
        def build(klass, payload):
            if payload is None:
                return None
            names = {f.name for f in fields(klass)}
            return klass(**{k: v for k, v in payload.items() if k in names})

        peers = []
        for p in d.get("peers", []):
            p = dict(p)
            p["metrics"] = build(Metrics, p.get("metrics"))
            peers.append(build(Peer, p))
        return cls(
            ticker=d["ticker"],
            memo=Memo.model_validate(d["memo"]),
            metrics=build(Metrics, d.get("metrics")),
            dcf=build(DCFResult, d.get("dcf")),
            earnings=build(EarningsSummary, d.get("earnings")),
            peers=peers,
            filing_excerpt=d.get("filing_excerpt", ""),
            trace=[build(TraceStep, t) for t in d.get("trace", [])],
            warnings=d.get("warnings", []),
            elapsed_seconds=d.get("elapsed_seconds", 0.0),
            created_at=d.get("created_at", ""),
        )
