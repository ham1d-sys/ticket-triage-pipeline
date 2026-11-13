import argparse
import asyncio
import csv
import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args, get_type_hints

from openai import OpenAIError
from tenacity import RetryError

from hashing_helper import sha256_file, sha256_text, ticket_key
from manifest import (
    Manifest,
    get_git_sha,
    get_release_tag,
    is_dirty,
    write_manifest,
)
from schema import TriageSchema
from ticket_io import load_support_tickets, write_tickets
from triage import ABORT_COUNT, MAX_CONCURRENCY, MODEL, SYSTEM_PROMPT, TriageProcessor
from validate import TicketValidator

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(pathname)s - %(asctime)s - %(message)s",
)
logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = PROJECT_ROOT / "data" / "input"
OUTPUT_PATH = PROJECT_ROOT / "data" / "output"

TICKET_SCHEMA = {
    "fieldnames": ("ticket_id", "sender", "subject", "body", "received_at"),
    "timestamp_format": "%Y-%m-%d %H:%M:%S",
}


def parse_args():
    parser = argparse.ArgumentParser(description="ticket-triage-pipeline")
    parser.add_argument(
        "--mode",
        choices=get_args(get_type_hints(Manifest)["mode"]),
        required=True,
        help="Run mode: production or eval.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_PATH,
        help="CSV file, or directory of CSV files, to process (default: data/input).",
    )
    args = parser.parse_args()
    if not args.input.exists():
        parser.error(f"input path does not exist: {args.input}")
    return args


def generate_run_dir(run_id: str) -> Path:
    """Create and return a unique directory for the current run."""
    run_dir = OUTPUT_PATH / run_id
    run_dir.mkdir(parents=True)
    return run_dir


def load_triaged_keys() -> set[tuple[str, str]]:
    """Collect ticket keys (id + content hash) from triaged.csv files in past run directories."""
    triaged_keys = set()

    for triaged_file_path in OUTPUT_PATH.glob("*/triaged.csv"):
        with open(
                triaged_file_path,
                "r",
                encoding="UTF-8",
                newline="",
        ) as triaged_file:
            triaged_keys.update(
                ticket_key(ticket, TICKET_SCHEMA["fieldnames"])
                for ticket in csv.DictReader(triaged_file)
            )

    return triaged_keys


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_error(manifest: Manifest, status: str, error: Exception) -> None:
    """Mark the run with a status and the error that caused it."""
    manifest.status = status
    manifest.error = f"{type(error).__name__}: {error}"
    logger.warning("%s. Run %s.", manifest.error, status)


def validate_tickets(tickets: list[dict[str, str]]) -> TicketValidator:
    validator = TicketValidator(tickets, TICKET_SCHEMA)
    validator.ensure_expected_fields_present_and_non_empty()
    validator.ensure_ticket_unique()
    validator.ensure_body_in_valid_tickets_gte_3_chars()
    validator.ensure_valid_received_at_timestamp()
    validator.ensure_valid_sender()
    validator.cleanup_tickets()
    return validator


def write_outputs(run_path: Path, results: dict[str, list]) -> None:
    fieldnames = TICKET_SCHEMA["fieldnames"]
    triage_fields = tuple(TriageSchema.model_fields)
    outputs = (
        ("invalid_tickets.csv", "invalid", ("reason",)),
        ("needs_review.csv", "needs_review", ("reason",)),
        ("triaged.csv", "triaged", triage_fields),
        ("unattempted.csv", "unattempted", ()),
    )
    for filename, key, extra_fields in outputs:
        write_tickets(results[key], fieldnames, run_path, filename, extra_fields)


async def run_pipeline(mode: str, input_path: Path) -> str:
    """Run the pipeline on one input file and return the run's final status."""
    start_time = utc_now()
    run_id = start_time.replace(":", "-") + "_" + uuid.uuid4().hex
    run_path = generate_run_dir(run_id)

    manifest_state = Manifest(
        manifest_version=MANIFEST_VERSION,
        run_id=run_id,
        status="running",
        mode=mode,
        started_at=start_time,
        code={
            "git_sha": get_git_sha(PROJECT_ROOT),
            "release": get_release_tag(PROJECT_ROOT),
            "dirty": is_dirty(PROJECT_ROOT),
        },
        config={
            "model": MODEL,
            "prompt_sha256": sha256_text(SYSTEM_PROMPT),
            "abort_count": ABORT_COUNT,
            "max_concurrency": MAX_CONCURRENCY,
        },
        input={
            "path": str(input_path),
            "sha256": sha256_file(input_path),
        },
    )
    write_manifest(run_path, manifest_state)

    support_tickets = []
    validator = None
    triage_processor = None

    try:
        support_tickets = load_support_tickets(input_path)
        triaged_keys = load_triaged_keys() if mode == "production" else set()

        validator = validate_tickets(support_tickets)
        triage_processor = TriageProcessor(
            validator.tickets,
            TICKET_SCHEMA["fieldnames"],
            triaged_keys,
        )
        await triage_processor.triage_tickets()

    except RetryError as error:
        record_error(manifest_state, "aborted", error)
    except (csv.Error, UnicodeDecodeError) as error:
        record_error(manifest_state, "failed", error)
    except OSError as error:
        record_error(manifest_state, "failed", error)
    except OpenAIError as error:
        record_error(manifest_state, "failed", error)
    except Exception as error:
        record_error(manifest_state, "failed", error)

    finally:
        results = {
            "invalid": list(validator.invalid_tickets.values()) if validator else [],
            "needs_review": triage_processor.needs_review if triage_processor else [],
            "triaged": triage_processor.triaged if triage_processor else [],
            "unattempted": triage_processor.unattempted if triage_processor else [],
        }
        counts = {
            "loaded": len(support_tickets),
            "invalid": len(results["invalid"]),
            "skipped": triage_processor.skipped if triage_processor else 0,
            "triaged": len(results["triaged"]),
            "needs_review": len(results["needs_review"]),
            "unattempted": len(results["unattempted"]),
        }
        manifest_state.counts = counts
        manifest_state.needs_review_breakdown = dict(
            Counter(ticket["reason"] for ticket in results["needs_review"])
        )

        accounted = sum(v for k, v in counts.items() if k != "loaded")
        if manifest_state.status != "failed" and accounted != counts["loaded"]:
            logger.warning(
                "Count mismatch: loaded %d tickets but accounted for %d tickets.",
                counts["loaded"],
                accounted,
            )
            manifest_state.status = "failed"
            manifest_state.error = "Count mismatch."

        try:
            write_outputs(run_path, results)
        except OSError as error:
            record_error(manifest_state, "failed", error)

        if manifest_state.status == "running":
            manifest_state.status = "completed"

        manifest_state.finished_at = utc_now()
        write_manifest(run_path, manifest_state)

    return manifest_state.status


async def main(mode: str, input_path: Path):
    input_files = sorted(input_path.glob("*.csv")) if input_path.is_dir() else [input_path]
    if not input_files:
        logger.warning("No CSV files found in %s.", input_path)
        return

    for number, input_file in enumerate(input_files, start=1):
        logger.info("Processing %s (%d/%d).", input_file.name, number, len(input_files))
        status = await run_pipeline(mode, input_file)

        if status == "aborted":
            logger.warning("Run aborted; skipping the remaining %d file(s).", len(input_files) - number)
            break


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(args.mode, args.input))
