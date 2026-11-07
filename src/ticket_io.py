import csv
from logging import getLogger
from pathlib import Path

logger = getLogger(__name__)


def load_support_tickets(tickets_path: Path) -> list[dict[str, str]]:
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


def write_tickets(
        tickets: list[dict[str, str]],
        ticket_fieldnames: tuple[str, ...],
        run_path: Path,
        filename: str,
        extra_fieldnames: tuple[str, ...] = (),
) -> None:
    """Write tickets to a CSV file."""
    output_path = run_path / filename
    fieldnames = [*ticket_fieldnames, *extra_fieldnames]

    with open(output_path, "w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(tickets)

    logger.info("Wrote tickets to '%s'", output_path)
