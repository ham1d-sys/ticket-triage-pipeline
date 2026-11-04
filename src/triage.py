import os
from logging import getLogger
from typing import List, Dict

from dotenv import load_dotenv
from openai import OpenAI, APIConnectionError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter, RetryError

from schema import TriageSchema

logger = getLogger(__name__)

load_dotenv()
_client = None

initial_wait = 1
max_wait = 10
stop_count = 4


def get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
        )
    return _client


class TriageProcessor:
    """Triage tickets."""

    def __init__(self, tickets: List[Dict], ticket_fieldnames, triaged_ids, abort_count):
        self.tickets = tickets
        self.ticket_fieldnames = ticket_fieldnames
        self.triaged_ids = triaged_ids
        self.triaged = []
        self.needs_review = []
        self.abort_count = abort_count

    @retry(
        retry=retry_if_exception_type(APIConnectionError),
        wait=wait_exponential_jitter(initial=initial_wait, max=max_wait),
        stop=stop_after_attempt(stop_count),
        reraise=True,
    )
    def triage_ticket(self, ticket) -> bool:
        """Triage a single ticket using the OpenAI API."""
        response = get_client().responses.parse(
            model="gpt-5.6-luna",
            input=[
                {
                    "role": "system",
                    "content": "You're a support ticket triage assistant. Classify this support ticket into a category (billing / bug / feature_request / spam / other) and an urgency (low / medium / high) with a concise one-line reason.",
                },
                {
                    "role": "user",
                    "content": f"{ticket}",
                },
            ],
            text_format=TriageSchema,
        )
        for output in response.output:
            if output.type != "message":
                continue

            for item in output.content:
                if item.type == "refusal":
                    self.needs_review.append(
                        {**{name: ticket.get(name) for name in self.ticket_fieldnames}, "reason": "Refusal."})
                    return True  # indicate processing failed
                else:
                    self.triaged.append({**{name: ticket.get(name) for name in self.ticket_fieldnames},
                                         **response.output_parsed.model_dump()})
                    return False  # indicate processing succeeded

        self.needs_review.append(
            {**{name: ticket.get(name) for name in self.ticket_fieldnames}, "reason": "No usable response."})
        return True  # indicate processing failed

    def triage_tickets(self) -> None:
        """Triage tickets using the OpenAI API."""
        unclassified_count = 0
        failed_retry_count = []

        for ticket in self.tickets:
            if ticket["ticket_id"] in self.triaged_ids:
                continue

            try:
                unclassified_status = self.triage_ticket(ticket)
                unclassified_count += unclassified_status
                failed_retry_count.append(False)
            except APIConnectionError as e:
                failed_retry_count.append(True)
                if len(failed_retry_count) >= self.abort_count and all(failed_retry_count[-self.abort_count:]):
                    raise RetryError(f"Hit {self.abort_count} consecutive API connection errors")

                unclassified_count += 1
                self.needs_review.append(
                    {"content": ticket, "reason": f"{type(e).__name__} after {stop_count} triage attempts."})

        if unclassified_count:
            logger.warning(f"{unclassified_count} tickets couldn't be classified. Review them in `needs_review.csv`.")
