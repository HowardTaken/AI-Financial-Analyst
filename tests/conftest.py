"""Shared fixtures: synthetic company data so tests never touch the network or an API key."""

import pytest

from analyst.models import FinancialData


def make_data(
    *,
    fcf=(100e9, 95e9, 90e9),          # newest first
    price=100.0,
    shares=1e9,
    debt=20e9,
    cash=10e9,
    beta=1.0,
    interest=0.0,
    industry="Software - Application",
    market_cap=100e9,
    sbc=0.0,
    equity=50e9,
) -> FinancialData:
    periods = ["2025-09-30", "2024-09-30", "2023-09-30", "2022-09-30"]
    income = {
        p: {"Total Revenue": 400e9 - i * 20e9, "Gross Profit": (400e9 - i * 20e9) * 0.45,
            "Net Income": 90e9 - i * 5e9, "Diluted EPS": 6.0 - i * 0.3, "Interest Expense": interest}
        for i, p in enumerate(periods)
    }
    balance = {
        p: {"Total Debt": debt, "Stockholders Equity": equity, "Ordinary Shares Number": shares,
            "Cash Cash Equivalents And Short Term Investments": cash}
        for p in periods
    }
    cash_flow = {
        p: {"Free Cash Flow": v, "Stock Based Compensation": sbc} for p, v in zip(periods, fcf, strict=False)
    }
    return FinancialData(
        ticker="TEST", current_price=price, income_statement=income, balance_sheet=balance,
        cash_flow=cash_flow, beta=beta, trailing_eps=None, shares_outstanding=shares,
        market_cap=market_cap, sector="Technology", industry=industry, industry_key="software-application",
        risk_free_rate=0.04,
    )


@pytest.fixture
def data():
    return make_data()
