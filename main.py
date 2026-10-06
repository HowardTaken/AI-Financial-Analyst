"""Command-line interface: `python main.py AAPL NVDA` or run without arguments for an interactive prompt."""

from __future__ import annotations

import argparse
import logging
import sys

from analyst.formatting import result_to_markdown
from analyst.pipeline import analyze

RULE = "-" * 64


def print_event(event: dict) -> None:
    kind = event["type"]
    if kind == "tool_start":
        print(f"  -> {event['tool']}", flush=True)
    elif kind == "tool_end":
        print(f"  {'ok ' if event['ok'] else 'ERR'} {event['tool']} ({event['seconds']:.1f}s): {event['summary']}",
              flush=True)
    elif kind == "reasoning":
        print(f"  .. {event['text'][:200]}", flush=True)


def run(ticker: str) -> None:
    print(f"\n{RULE}\n  Analysing {ticker.upper()}\n{RULE}")
    result = analyze(ticker, on_event=print_event)
    print(f"\n{RULE}\n{result_to_markdown(result)}\n{RULE}")
    print(f"  Completed in {result.elapsed_seconds:.0f}s using {len(result.trace)} tool calls.")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Market Analyst: agent-written equity memos.")
    parser.add_argument("tickers", nargs="*", help="Ticker symbols to analyse (omit for interactive mode).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show debug logging.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.tickers:
        for t in args.tickers:
            try:
                run(t)
            except Exception as exc:
                print(f"\n  [ERROR] {t}: {exc}", file=sys.stderr)
        return

    print("AI Market Analyst. Type a ticker, or 'exit' to quit.")
    while True:
        try:
            t = input("Ticker > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if t.lower() in ("exit", "quit"):
            return
        if t:
            try:
                run(t)
            except Exception as exc:
                print(f"\n  [ERROR] {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
