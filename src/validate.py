import logging
from datetime import datetime as dt
from typing import Dict, List

from email_validator import EmailNotValidError, validate_email

from hashing_helper import ticket_key
from format import strptime_format_to_iso_8601_template

logger = logging.getLogger(__name__)


class TicketValidator:
    """Validates support tickets and filters out invalid entries."""

    def __init__(self, tickets: List[Dict], ticket_schema):
        self.tickets = tickets
        self.expected_ticket_fields = ticket_schema["fieldnames"]
        self.expected_timestamp_format = ticket_schema["timestamp_format"]
        self.invalid_tickets = {}

    def add_invalid_ticket(self, ticket: Dict, reason: str) -> None:
        """Add invalid tickets to self.invalid_tickets."""
        key = id(ticket)
        if key not in self.invalid_tickets:
            self.invalid_tickets[key] = {**{name: ticket.get(name) for name in self.expected_ticket_fields},
                                         "reason": reason}
        else:
            self.invalid_tickets[key]["reason"] += "; " + reason

    def cleanup_tickets(self) -> None:
        """Remove invalid tickets from self.tickets"""
        if self.invalid_tickets:
            invalid_ids = set(self.invalid_tickets)
            self.tickets = [ticket for ticket in self.tickets if id(ticket) not in invalid_ids]

    def ensure_expected_fields_present_and_non_empty(self) -> None:
        """Ensure that all expected ticket fields are present and non-empty."""
        empty_count = 0
        missing_count = 0

        for ticket in self.tickets:
            actual_fields = set(ticket.keys())
            missing_fields = set(self.expected_ticket_fields) - actual_fields

            if not missing_fields:
                empty_fields = set(
                    [field for field, val in ticket.items() if field in self.expected_ticket_fields and not val])
                if not empty_fields:
                    continue
                reason_invalid = "Empty expected field(s)."
                empty_count += 1
            else:
                reason_invalid = "Missing expected field(s)."
                missing_count += 1

            self.add_invalid_ticket(ticket, reason_invalid)

        if empty_count:
            logger.warning(f"Found {empty_count} tickets with empty field(s).")
        if missing_count:
            logger.warning(f"Found {missing_count} tickets with missing field(s).")

        self.cleanup_tickets()

    def ensure_body_in_valid_tickets_gte_3_chars(self) -> None:
        """Ensure that the body field of a ticket is greater than or equal to 3 characters."""
        lt_3_chars_count = 0

        for ticket in self.tickets:
            body = ticket.get("body", "").strip()
            if not len(body) >= 3:
                reason_invalid = "`body` field is under 3 characters."
                self.add_invalid_ticket(ticket, reason_invalid)
                lt_3_chars_count += 1

        if lt_3_chars_count:
            logger.warning(f"Found {lt_3_chars_count} ticket(s) whose `body` field is under 3 characters.")

    def ensure_valid_received_at_timestamp(self) -> None:
        """Ensure that the received_at field of a ticket is the expected timestamp format."""
        readable_timestamp_format = strptime_format_to_iso_8601_template(self.expected_timestamp_format)
        invalid_timestamp_count = 0

        for ticket in self.tickets:
            received_at = ticket.get("received_at")
            try:
                dt.strptime(received_at, self.expected_timestamp_format)
                continue
            except ValueError:
                reason_invalid = f"`received_at` field contains an invalid timestamp."
                self.add_invalid_ticket(ticket, reason_invalid)
                invalid_timestamp_count += 1

        if invalid_timestamp_count:
            logger.warning(
                f"Found {invalid_timestamp_count} ticket(s) whose `received_at` timestamp field does not follow the expected '{readable_timestamp_format}' format.")

    def ensure_valid_sender(self) -> None:
        """Ensure that the sender field of a ticket is a valid email address (RFC syntax, no DNS lookup)."""
        invalid_sender_count = 0

        for ticket in self.tickets:
            try:
                validate_email(
                    ticket.get("sender") or "",
                    check_deliverability=False,
                    allow_quoted_local=True,
                    allow_domain_literal=True,
                )
            except EmailNotValidError as error:
                self.add_invalid_ticket(ticket, f"`sender` field is not a valid email address ({error})")
                invalid_sender_count += 1

        if invalid_sender_count:
            logger.warning(
                f"Found {invalid_sender_count} ticket(s) whose `sender` field doesn't match an email address' format.")

    def ensure_ticket_unique(self) -> None:
        """Ensure no ticket repeats the same `ticket_id` and content as an earlier one."""
        duplicate_count = 0

        seen = set()
        for ticket in self.tickets:
            key = ticket_key(ticket, self.expected_ticket_fields)
            if key in seen:
                self.add_invalid_ticket(ticket, "Duplicate of an earlier ticket (same `ticket_id` and content).")
                duplicate_count += 1
            seen.add(key)

        if duplicate_count:
            logger.warning(f"Found {duplicate_count} duplicate ticket(s) (same `ticket_id` and content).")
