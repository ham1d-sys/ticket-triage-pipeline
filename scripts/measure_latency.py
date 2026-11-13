"""Measure single-call API latency to pick a client timeout.

Run from the repo root (uses real API calls and your OPENAI_API_KEY):
    python scripts/measure_latency.py --passes 3
"""
import argparse
import asyncio
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ticket_io import load_support_tickets  # noqa: E402
from triage import TriageProcessor  # noqa: E402


def percentile(sorted_values: list[float], p: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, math.ceil(p / 100 * len(sorted_values)) - 1)]


async def measure(processor, tickets, passes, durations, errors):
    single_call = TriageProcessor.triage_ticket.__wrapped__  # skip tenacity so retries don't skew timings
    total = passes * len(tickets)
    calls = (ticket for _ in range(passes) for ticket in tickets)
    for number, ticket in enumerate(calls, start=1):
        print(f"[{number}/{total}] {ticket['ticket_id']} ... ", end="", flush=True)
        start = time.perf_counter()
        try:
            await single_call(processor, ticket)
        except Exception as error:
            errors.append(type(error).__name__)
            print(f"error: {type(error).__name__}")
            continue
        durations.append(time.perf_counter() - start)
        print(f"{durations[-1]:.2f}s")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "input" / "support_tickets_test.csv")
    parser.add_argument("--passes", type=int, default=3, help="times to run the whole file")
    args = parser.parse_args()

    tickets = load_support_tickets(args.input)
    processor = TriageProcessor(tickets, ("ticket_id", "sender", "subject", "body", "received_at"), set())

    durations, errors = [], []
    try:
        asyncio.run(measure(processor, tickets, args.passes, durations, errors))
    except KeyboardInterrupt:
        print("\ninterrupted, reporting what was collected so far")

    if not durations:
        sys.exit("No successful calls to report on.")
    durations.sort()
    print(f"\ncalls: {len(durations)} ok, {len(errors)} errors")
    print(f"p50 {statistics.median(durations):.2f}s | p95 {percentile(durations, 95):.2f}s | "
          f"p99 {percentile(durations, 99):.2f}s | max {durations[-1]:.2f}s")
    if len(durations) < 100:
        print("note: under 100 samples, so p99 is effectively the max")
    print(f"suggested timeout (2 x p99): {math.ceil(2 * percentile(durations, 99))}s")


if __name__ == "__main__":
    main()
