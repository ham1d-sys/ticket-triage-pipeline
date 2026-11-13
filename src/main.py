import argparse
import csv
import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import get_args, get_type_hints

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
from triage import ABORT_COUNT, MODEL, SYSTEM_PROMPT, TriageProcessor
from validate import TicketValidator

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(pathname)s - %(asctime)s - %(message)s",
)
logger = logging.getLogger(__name__)

MANIFEST_VERSION = 2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUPPORT_TICKETS_PATH = (
        PROJECT_ROOT / "data" / "input" / "support_tickets_test.csv"
)
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
    return parser.parse_args()


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


def main(mode: str):
    start_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = start_time.replace(":", "-") + "_" + uuid.uuid4().hex
    run_path = generate_run_dir(run_id)

    code_info = {
        "git_sha": get_git_sha(PROJECT_ROOT),
        "release": get_release_tag(PROJECT_ROOT),
        "dirty": is_dirty(PROJECT_ROOT),
    }
    config_info = {
        "model": MODEL,
        "prompt_sha256": sha256_text(SYSTEM_PROMPT),
        "abort_count": ABORT_COUNT,
    }
    input_info = {
        "path": str(SUPPORT_TICKETS_PATH),
        "sha256": sha256_file(SUPPORT_TICKETS_PATH),
    }

    manifest_state = Manifest(
        manifest_version=MANIFEST_VERSION,
        run_id=run_id,
        status="running",
        mode=mode,
        started_at=start_time,
        code=code_info,
        config=config_info,
        input=input_info,
    )
    write_manifest(run_path, manifest_state)

    try:
        support_tickets = load_support_tickets(SUPPORT_TICKETS_PATH)

        triaged_keys = set()
        if mode == "production":
            triaged_keys = load_triaged_keys()

        ticket_validator = TicketValidator(support_tickets, TICKET_SCHEMA)
        ticket_validator.ensure_expected_fields_present_and_non_empty()
        ticket_validator.ensure_ticket_unique()
        ticket_validator.ensure_body_in_valid_tickets_gte_3_chars()
        ticket_validator.ensure_valid_received_at_timestamp()
        ticket_validator.ensure_valid_sender()
        ticket_validator.cleanup_tickets()

        invalid_tickets = list(ticket_validator.invalid_tickets.values())
        valid_tickets = ticket_validator.tickets

        triage_processor = TriageProcessor(
            valid_tickets,
            TICKET_SCHEMA["fieldnames"],
            triaged_keys,
        )

        try:
            triage_processor.triage_tickets()
        except RetryError as error:
            manifest_state.status = "aborted"
            manifest_state.error = f"{type(error).__name__}: {error}"
            logger.warning("%s. Batch aborted.", manifest_state.error)

        needs_review_tickets = triage_processor.needs_review
        triaged_tickets = triage_processor.triaged
        unattempted_tickets = triage_processor.unattempted

        manifest_state.counts = {
            "loaded": len(support_tickets),
            "invalid": len(invalid_tickets),
            "skipped": triage_processor.skipped,
            "triaged": len(triaged_tickets),
            "needs_review": len(needs_review_tickets),
            "unattempted": len(unattempted_tickets),
        }
        manifest_state.needs_review_breakdown = dict(
            Counter(ticket["reason"] for ticket in needs_review_tickets)
        )

        counts = manifest_state.counts
        accounted = (
                counts["invalid"]
                + counts["skipped"]
                + counts["triaged"]
                + counts["needs_review"]
                + counts["unattempted"]
        )

        if accounted != counts["loaded"]:
            logger.warning(f"Count mismatch: loaded {counts["loaded"]} tickets but accounted for {accounted} tickets.")
            manifest_state.status = "failed"
            manifest_state.error = "Count mismatch."

        ticket_fieldnames = TICKET_SCHEMA["fieldnames"]
        triage_fields = tuple(TriageSchema.model_fields)

        write_tickets(
            invalid_tickets,
            ticket_fieldnames,
            run_path,
            "invalid_tickets.csv",
            ("reason",),
        )
        write_tickets(
            needs_review_tickets,
            ticket_fieldnames,
            run_path,
            "needs_review.csv",
            ("reason",),
        )
        write_tickets(
            triaged_tickets,
            ticket_fieldnames,
            run_path,
            "triaged.csv",
            triage_fields,
        )
        write_tickets(
            unattempted_tickets,
            ticket_fieldnames,
            run_path,
            "unattempted.csv",
        )

    except Exception as error:
        manifest_state.status = "failed"
        manifest_state.error = f"{type(error).__name__}: {error}"
        logger.warning("%s. Run failed.", manifest_state.error)

    finally:
        if manifest_state.status == "running":
            manifest_state.status = "completed"

        manifest_state.finished_at = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        write_manifest(run_path, manifest_state)


if __name__ == "__main__":
    args = parse_args()
    main(args.mode)
