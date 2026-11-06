import csv
import hashlib
import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from tenacity import RetryError

from hashing_helper import sha256_text, sha256_file
from manifest import Manifest, get_git_sha, get_release_tag, is_dirty, write_manifest
from ticket_io import load_support_tickets, write_invalid_tickets, write_needs_review_tickets, write_triaged_tickets
from triage import TriageProcessor, MODEL, SYSTEM_PROMPT, ABORT_COUNT
from validate import TicketValidator

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(pathname)s - %(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

MANIFEST_VERSION = 2
MODE = "production"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
support_tickets_path = PROJECT_ROOT / "data" / "input" / "support_tickets_test.csv"
output_path = PROJECT_ROOT / "data" / "output"

ticket_schema = {"fieldnames": ("ticket_id", "sender", "subject", "body", "received_at"),
                 "timestamp_format": "%Y-%m-%d %H:%M:%S"}


def generate_run_dir(run_id: str) -> Path:
    """
    Create a unique directory for current run.
    :return: Path object containing current run directory.
    """
    global output_path
    run_dir = output_path / run_id
    run_dir.mkdir(parents=True)
    return run_dir


def load_triaged_ids():
    """Collect tickets ids from `triaged.csv` files in past runs directories."""
    global output_path
    triaged_ids = set()
    for triaged in output_path.glob("*/triaged.csv"):
        with open(triaged, "r", encoding="UTF-8", newline="") as triaged_file:
            triaged_ids.update(ticket["ticket_id"] for ticket in csv.DictReader(triaged_file))
    return triaged_ids


def main():
    start_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = start_time.replace(":", "-") + "_" + uuid.uuid4().hex
    run_path = generate_run_dir(run_id)
    code_info = {"git_sha": get_git_sha(PROJECT_ROOT), "release": get_release_tag(PROJECT_ROOT),
                 "dirty": is_dirty(PROJECT_ROOT)}
    config_info = {"model": MODEL, "prompt_sha256": sha256_text(SYSTEM_PROMPT), "abort_count": ABORT_COUNT}
    input_info = {"path": str(support_tickets_path), "sha256": sha256_file(support_tickets_path)}
    manifest_state = Manifest(manifest_version=MANIFEST_VERSION, run_id=run_id, status="running", mode=MODE,
                              started_at=start_time, code=code_info, config=config_info, input=input_info)
    write_manifest(run_path, manifest_state)

    try:
        support_tickets = load_support_tickets(support_tickets_path)
        triaged_tickets_ids = []
        if MODE == "production":
            triaged_tickets_ids = load_triaged_ids()
        ticket_validator = TicketValidator(support_tickets, ticket_schema)
        ticket_validator.ensure_expected_fields_present_and_non_empty()
        ticket_validator.ensure_body_in_valid_tickets_gte_3_chars()
        ticket_validator.ensure_valid_received_at_timestamp()
        ticket_validator.ensure_valid_sender()
        ticket_validator.cleanup_tickets()

        invalid_tickets = ticket_validator.invalid_tickets
        valid_tickets = ticket_validator.tickets

        triage_processor = TriageProcessor(valid_tickets, ticket_schema["fieldnames"], triaged_tickets_ids)
        try:
            triage_processor.triage_tickets()
        except RetryError as e:
            manifest_state.status = "aborted"
            manifest_state.error = e
            logger.warning(f"{type(e).__name__}: {e}. Batch aborted.")

        needs_review_tickets = triage_processor.needs_review
        triaged_tickets = triage_processor.triaged

        manifest_state.counts = {"loaded": len(support_tickets), "invalid": len(invalid_tickets),
                                 "skipped": triage_processor.skipped, "triaged": len(triaged_tickets),
                                 "needs_review": len(needs_review_tickets),
                                 "not_attempted": triage_processor.not_attempted}
        manifest_state.needs_review_breakdown = dict(Counter(ticket["reason"] for ticket in needs_review_tickets))

        write_invalid_tickets(invalid_tickets, ticket_schema["fieldnames"], run_path)
        write_needs_review_tickets(needs_review_tickets, ticket_schema["fieldnames"], run_path)
        write_triaged_tickets(triaged_tickets, ticket_schema["fieldnames"], run_path)
    except Exception as e:
        manifest_state.status = "failed"
        manifest_state.error = e
        logger.warning(f"{type(e).__name__}: {e}. Run failed.")
    finally:
        if manifest_state.status == "running":
            manifest_state.status = "completed"
        manifest_state.finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_manifest(run_path, manifest_state)


if __name__ == "__main__":
    main()
