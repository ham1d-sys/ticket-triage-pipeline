import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

from tenacity import RetryError

from ticket_io import load_support_tickets, write_invalid_tickets, write_needs_review_tickets, write_triaged_tickets
from triage import TriageProcessor
from validate import TicketValidator

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(pathname)s - %(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

TICKET_FIELDNAMES = ("ticket_id", "sender", "subject", "body", "received_at")
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
abort_count = 5
support_tickets_path = Path(__file__).resolve().parent.parent / "data" / "input" / "support_tickets_test.csv"
output_path = Path(__file__).resolve().parent.parent / "data" / "output"


def generate_run_dir():
    """Create a unique directory for current run.
    :return: str
    """
    global output_path
    run_id = (datetime.now(timezone.utc).strftime("%Y-%m-%d_%H.%M.%S"))
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
    triaged_tickets_ids = load_triaged_ids()
    run_path = generate_run_dir()
    support_tickets = load_support_tickets(support_tickets_path)

    ticket_validator = TicketValidator(support_tickets, TICKET_FIELDNAMES, TIMESTAMP_FORMAT)
    ticket_validator.ensure_expected_fields_present_and_non_empty()
    ticket_validator.ensure_body_in_valid_tickets_gte_3_chars()
    ticket_validator.ensure_valid_received_at_timestamp()
    ticket_validator.ensure_valid_sender()
    ticket_validator.cleanup_tickets()

    invalid_tickets = ticket_validator.invalid_tickets
    valid_tickets = ticket_validator.tickets

    triage_processor = TriageProcessor(valid_tickets, TICKET_FIELDNAMES, triaged_tickets_ids, abort_count)
    try:
        triage_processor.triage_tickets()
    except RetryError as e:
        logger.warning(f"{type(e).__name__}: {e}. Batch aborted.")

    needs_review_tickets = triage_processor.needs_review
    triaged_tickets = triage_processor.triaged

    write_invalid_tickets(invalid_tickets, TICKET_FIELDNAMES, run_path)
    write_needs_review_tickets(needs_review_tickets, TICKET_FIELDNAMES, run_path)
    write_triaged_tickets(triaged_tickets, TICKET_FIELDNAMES, run_path)


if __name__ == "__main__":
    main()
