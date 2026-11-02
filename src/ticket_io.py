import csv
from logging import getLogger
from pathlib import Path
from typing import List, Dict

logger = getLogger(__name__)


def load_support_tickets(tickets_path: Path) -> List[Dict]:
    """
    Load support tickets from CSV file.
    :param tickets_path: Path to CSV file.
    :return: List of tickets."""
    with open(tickets_path, "r", encoding='UTF-8', newline='') as tickets_file:
        tickets = list(
            csv.DictReader(tickets_file)
        )
        logger.info(f"Loaded tickets from '{tickets_path}'.")
    return tickets


def write_invalid_tickets(invalid_tickets: Dict, fieldnames: List[str], output_path: Path) -> None:
    """Write invalid tickets to CSV file."""
    invalid_tickets_path = output_path / "invalid_tickets.csv"
    with open(invalid_tickets_path, "w", encoding='UTF-8', newline='') as invalid_tickets_file:
        writer = csv.DictWriter(invalid_tickets_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(invalid_tickets.values())
        logger.info(f"Wrote invalid tickets to '{invalid_tickets_path}'.")
