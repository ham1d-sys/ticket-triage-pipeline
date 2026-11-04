import csv
from logging import getLogger
from pathlib import Path
from typing import List, Dict, Tuple

from schema import TriageSchema

logger = getLogger(__name__)


def load_support_tickets(tickets_path: Path) -> List[Dict]:
    """
    Load support tickets from CSV file.
    :param tickets_path: Path to CSV file.
    :return: List of tickets.
    """
    with open(tickets_path, "r", encoding="UTF-8", newline="") as tickets_file:
        tickets = list(
            csv.DictReader(tickets_file)
        )
    logger.info(f"Loaded tickets from '{tickets_path}'.")
    return tickets


def write_invalid_tickets(invalid_tickets: Dict, ticket_fieldnames: List[str], run_path: Path) -> None:
    """
    Write invalid tickets to CSV file.
    :param invalid_tickets: Invalid tickets.
    :param ticket_fieldnames: Ticket fields.
    :param run_path: Output directory.
    """
    invalid_tickets_path = run_path / "invalid_tickets.csv"
    with open(invalid_tickets_path, "w", encoding="UTF-8", newline="") as invalid_tickets_file:
        fieldnames = [*ticket_fieldnames, "reason"]
        writer = csv.DictWriter(invalid_tickets_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(invalid_tickets.values())
    logger.info(f"Wrote invalid tickets to '{invalid_tickets_path}'.")


def write_needs_review_tickets(needs_review_tickets: List[Dict], ticket_fieldnames: Tuple[str], run_path: Path) -> None:
    """
    Write tickets that needs review to CSV file.
    :param needs_review_tickets: Tickets that need review.
    :param ticket_fieldnames: Ticket fields.
    :param run_path: Output directory.
    """
    needs_review_path = run_path / "needs_review.csv"
    with open(needs_review_path, "w", encoding="UTF-8", newline="") as needs_review_file:
        fieldnames = [*ticket_fieldnames, "reason"]
        writer = csv.DictWriter(needs_review_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(needs_review_tickets)
    logger.info(f"Wrote needs-review tickets to '{needs_review_path}'")


def write_triaged_tickets(triaged_tickets, ticket_fieldnames, run_path):
    """
    Write triaged tickets to CSV file.
    :param triaged_tickets: Triaged tickets.
    :param ticket_fieldnames: Ticket fields.
    :param run_path: Output directory.
    """
    triaged_path = run_path / "triaged.csv"
    with open(triaged_path, "w", encoding="UTF-8", newline="") as triaged_file:
        fieldnames = [*ticket_fieldnames, *list(TriageSchema.model_fields)]
        writer = csv.DictWriter(triaged_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(triaged_tickets)
    logger.info(f"Wrote triage results to '{triaged_path}'")
