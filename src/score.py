"""Score ticket-triage-pipeline output against gold_labels.csv.

Usage (from the repo root, after running the pipeline on support_tickets_test.csv):
    python score.py --gold gold_labels.csv --output-dir data/output

Rule: a valid ticket is correct only if category AND urgency both match.
Targets: overall >= 90%, edge >= 80%.
"""
import argparse
import ast
import csv
from pathlib import Path

OVERALL_TARGET = 0.90
EDGE_TARGET = 0.80


def key_of(d):
    """Match tickets across files by ticket_id."""
    return str(d.get("ticket_id", ""))


def read_output(path):
    """Return {ticket_key: row} from a pipeline output CSV (empty if the file is missing)."""
    out = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out[key_of(ast.literal_eval(row["content"]))] = row
    return out


def norm(x):
    return (x or "").strip().lower()


def pct(n, d):
    return f"{n}/{d} = {100 * n / d:.1f}%" if d else "n/a"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gold", default="gold_labels.csv")
    p.add_argument("--output-dir", default="data/output")
    a = p.parse_args()

    out_dir = Path(a.output_dir)
    triaged = read_output(out_dir / "triaged.csv")
    invalid = read_output(out_dir / "invalid_tickets.csv")
    review = read_output(out_dir / "needs_review.csv")

    with open(a.gold, encoding="utf-8", newline="") as f:
        gold = list(csv.DictReader(f))

    valid = [g for g in gold if g["status"] == "valid"]
    bad = [g for g in gold if g["status"] == "invalid"]

    both = cat_ok = urg_ok = 0
    edge_total = edge_both = normal_total = normal_both = 0
    misses = []

    for g in valid:
        k = key_of(g)
        is_edge = g["is_edge"] == "yes"
        edge_total += is_edge
        normal_total += not is_edge
        if k in triaged:
            t = triaged[k]
            c = norm(t["category"]) == g["category"]
            u = norm(t["urgency"]) == g["urgency"]
            cat_ok += c
            urg_ok += u
            if c and u:
                both += 1
                edge_both += is_edge
                normal_both += not is_edge
            else:
                misses.append((g["ticket_id"], is_edge, g["subject"],
                               f"expected {g['category']}/{g['urgency']}, got {norm(t['category'])}/{norm(t['urgency'])}"))
        elif k in review:
            misses.append((g["ticket_id"], is_edge, g["subject"], f"in needs_review.csv: {review[k]['reason']}"))
        elif k in invalid:
            misses.append((g["ticket_id"], is_edge, g["subject"], "wrongly rejected by validator"))
        else:
            misses.append((g["ticket_id"], is_edge, g["subject"], "not found in any output file"))

    caught = 0
    validation_fails = []
    for g in bad:
        k = key_of(g)
        if k in invalid:
            caught += 1
            if g["invalid_reason"] not in invalid[k]["reason"]:
                validation_fails.append((g["ticket_id"], f"rejected, but reason differs: {invalid[k]['reason']}"))
        else:
            where = "triaged" if k in triaged else "needs_review" if k in review else "no output file"
            validation_fails.append((g["ticket_id"], f"NOT rejected (found in {where})"))

    overall = both / len(valid)
    edge = edge_both / edge_total if edge_total else 0
    print("=== Triage (valid tickets, category AND urgency must match) ===")
    print(f"Overall : {pct(both, len(valid))}   target {OVERALL_TARGET:.0%}  -> {'PASS' if overall >= OVERALL_TARGET else 'FAIL'}")
    print(f"Edge    : {pct(edge_both, edge_total)}   target {EDGE_TARGET:.0%}  -> {'PASS' if edge >= EDGE_TARGET else 'FAIL'}")
    print(f"Normal  : {pct(normal_both, normal_total)}")
    print(f"Category only: {pct(cat_ok, len(valid))}")
    print(f"Urgency only : {pct(urg_ok, len(valid))}")
    print("\n=== Validation (invalid tickets) ===")
    print(f"Rejected correctly: {pct(caught, len(bad))}")
    for tid, msg in validation_fails:
        print(f"  {tid}: {msg}")
    print(f"\n=== Misses ({len(misses)}) ===")
    for tid, is_edge, subj, msg in misses:
        print(f"  {tid} [{'edge' if is_edge else 'normal'}] {subj!r}: {msg}")


if __name__ == "__main__":
    main()
