"""Score the latest pipeline runs against the gold labels.

Run from anywhere, no arguments:  python scripts/score.py
Gold labels:  data/<input file name>_gold_labels.csv, one per input file (e.g. support_tickets_test.csv
              is scored with data/support_tickets_test_gold_labels.csv).
Reads   data/output/<run id>/{manifest.json,triaged.csv,needs_review.csv,invalid_tickets.csv}
        (newest run of each input file that has gold labels)
Writes  scoring/<same run id>/{summary.json,misses.csv}, one folder per run, and prints a combined score.
Refuses to score if any of those runs is not "completed" in its manifest or skipped tickets.
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

OVERALL_TARGET = 0.90
EDGE_TARGET = 0.80

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
GOLD_SUFFIX = "_gold_labels.csv"
OUTPUT_DIR = ROOT / "data" / "output"
SCORING_DIR = ROOT / "data" / "scoring"



def key_of(d):
    """Match tickets across files by ticket_id."""
    return str(d.get("ticket_id", ""))


def find_latest_run(output_dir, input_name):
    """Return (run folder, manifest) of the newest run of input_name, refusing runs that can't be scored fairly."""
    runs = []
    for manifest_path in output_dir.glob("*/manifest.json"):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        if Path(manifest["input"]["path"]).name == input_name:
            runs.append((manifest_path.parent, manifest))
    if not runs:
        sys.exit(f"No runs of {input_name} found in {output_dir}. Run the pipeline first (python src/main.py).")

    run_dir, manifest = max(runs, key=lambda run: run[1]["started_at"])
    if manifest["status"] != "completed":
        sys.exit(f"Latest run '{run_dir.name}' has status '{manifest['status']}', not 'completed'. Nothing to score.")
    if manifest["counts"]["skipped"]:
        sys.exit(f"Latest run '{run_dir.name}' skipped {manifest['counts']['skipped']} already-triaged ticket(s), "
                 f"so its outputs are incomplete. Nothing to score.")
    return run_dir, manifest


def read_output(path):
    """Return {ticket_key: row} from a pipeline output CSV (empty if the file is missing)."""
    out = {}
    if not path.exists():
        return out
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out[key_of(row)] = row
    return out


def norm(x):
    return (x or "").strip().lower()


def pct(n, d):
    return f"{n}/{d} = {100 * n / d:.1f}%" if d else "n/a"


def score_run(run_dir, gold_path):
    """Score one run against one gold file, print and save the results, return the raw counts."""
    triaged = read_output(run_dir / "triaged.csv")
    invalid = read_output(run_dir / "invalid_tickets.csv")
    review = read_output(run_dir / "needs_review.csv")

    with open(gold_path, encoding="utf-8", newline="") as f:
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
    print(f"Scoring {gold_path.name} (run {run_dir.name})\n")
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

    results_dir = SCORING_DIR / run_dir.name
    results_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "run": run_dir.name,
        "overall": {"correct": both, "total": len(valid), "target": OVERALL_TARGET, "passed": overall >= OVERALL_TARGET},
        "edge": {"correct": edge_both, "total": edge_total, "target": EDGE_TARGET, "passed": edge >= EDGE_TARGET},
        "normal": {"correct": normal_both, "total": normal_total},
        "category_only": {"correct": cat_ok, "total": len(valid)},
        "urgency_only": {"correct": urg_ok, "total": len(valid)},
        "validation": {"correct": caught, "total": len(bad)},
    }
    with open(results_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    with open(results_dir / "misses.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticket_id", "kind", "is_edge", "subject", "detail"])
        for tid, is_edge, subj, msg in misses:
            w.writerow([tid, "triage", "yes" if is_edge else "no", subj, msg])
        for tid, msg in validation_fails:
            w.writerow([tid, "validation", "", "", msg])
    print(f"\nResults saved to {results_dir.relative_to(ROOT)}/")
    return Counter(valid=len(valid), both=both, cat_ok=cat_ok, urg_ok=urg_ok, edge_total=edge_total,
                   edge_both=edge_both, normal_total=normal_total, normal_both=normal_both,
                   bad=len(bad), caught=caught)


def print_combined(t, file_count):
    overall = t["both"] / t["valid"]
    edge = t["edge_both"] / t["edge_total"] if t["edge_total"] else 0
    print(f"\n{'=' * 60}\n=== Combined ({file_count} input files) ===")
    print(f"Overall : {pct(t['both'], t['valid'])}   target {OVERALL_TARGET:.0%}  -> {'PASS' if overall >= OVERALL_TARGET else 'FAIL'}")
    print(f"Edge    : {pct(t['edge_both'], t['edge_total'])}   target {EDGE_TARGET:.0%}  -> {'PASS' if edge >= EDGE_TARGET else 'FAIL'}")
    print(f"Normal  : {pct(t['normal_both'], t['normal_total'])}")
    print(f"Category only: {pct(t['cat_ok'], t['valid'])}")
    print(f"Urgency only : {pct(t['urg_ok'], t['valid'])}")
    print(f"Validation rejected correctly: {pct(t['caught'], t['bad'])}")


def main():
    gold_paths = sorted(DATA_DIR.glob(f"*{GOLD_SUFFIX}"))
    if not gold_paths:
        sys.exit(f"No *{GOLD_SUFFIX} files found in {DATA_DIR}.")

    # Look up every run first so a refused run stops scoring before anything is printed or saved.
    runs = [(find_latest_run(OUTPUT_DIR, gold.name.removesuffix(GOLD_SUFFIX) + ".csv")[0], gold) for gold in gold_paths]

    totals = Counter()
    for run_dir, gold_path in runs:
        totals += score_run(run_dir, gold_path)
        print()
    if len(runs) > 1:
        print_combined(totals, len(runs))


if __name__ == "__main__":
    main()
