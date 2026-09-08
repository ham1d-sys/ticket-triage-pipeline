import csv
import os
from logging import getLogger
from pathlib import Path
from typing import List, Dict

from dotenv import load_dotenv
from openai import OpenAI, APIConnectionError
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter, RetryError

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
            timeout=900.0,
        )
    return _client


class TriageSchema(BaseModel):
    """Define JSON output schema"""
    category: str
    urgency: str
    reason: str


class TriageProcessor:
    """Triage tickets."""

    def __init__(self, tickets: List[Dict], output_path: Path, abort_count):
        self.tickets = tickets
        self.triaged = []
        self.needs_review = []
        self.abort_count = abort_count
        self.output_path = output_path

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
            service_tier="flex",
        )
        for output in response.output:
            if output.type != "message":
                continue

            for item in output.content:
                if item.type == "refusal":
                    self.needs_review.append({"content": ticket, "reason": "Refusal."})
                    return True
                else:
                    self.triaged.append({"content": ticket, **response.output_parsed.model_dump()})
                    return False

        self.needs_review.append({"content": ticket, "reason": "No usable response."})
        return True

    def triage_tickets(self) -> None:
        """Triage tickets using the OpenAI API."""
        unclassified_count = 0
        failed_retry_count = []

        for ticket in self.tickets:
            try:
                unclassified_status = self.triage_ticket(ticket)
                unclassified_count += unclassified_status
                failed_retry_count.append(False)
            except (APIConnectionError, APITimeoutError) as e:
                failed_retry_count.append(True)
                if len(failed_retry_count) >= self.abort_count and all(failed_retry_count[-self.abort_count:]):
                    raise RetryError(f"Hit {self.abort_count} consecutive API connection or timeout errors")

                unclassified_count += 1
                self.needs_review.append(
                    {"content": ticket, "reason": f"{type(e).__name__} after {stop_count} triage attempts."})

        if unclassified_count:
            logger.warning(f"{unclassified_count} tickets couldn't be classified. Review them in `needs_review.csv`.")

    def write_outputs(self) -> None:
        """Write self.needs_review and self.triaged to needs_review.csv and triaged.csv, respectively"""
        if self.needs_review:
            needs_review_path = self.output_path / "needs_review.csv"
            with open(needs_review_path, "w", encoding="UTF-8", newline="") as needs_review_file:
                fieldnames = ["content", "reason"]
                writer = csv.DictWriter(needs_review_file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.needs_review)
            logger.info(f"Wrote needs-review tickets to '{needs_review_path}'")

        if self.triaged:
            triaged_path = self.output_path / "triaged.csv"
            with open(triaged_path, "w", encoding="UTF-8", newline="") as triaged_file:
                fieldnames = ["content", "category", "urgency", "reason"]
                writer = csv.DictWriter(triaged_file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.triaged)
                logger.info(f"Wrote triage results to '{triaged_path}'")
