import json
import os
from pathlib import Path
from logging import getLogger
from typing import List, Dict

from dotenv import load_dotenv
from openai import OpenAI, APIConnectionError, RateLimitError, InternalServerError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter, RetryError

from hashing_helper import ticket_key
from schema import TriageSchema

logger = getLogger(__name__)

load_dotenv()
_client = None

INITIAL_WAIT = 1
MAX_WAIT = 10
STOP_COUNT = 6
ABORT_COUNT = 5
LLM_TICKET_FIELDS = ("sender", "subject", "body")
RETRY_EXCEPTIONS = (APIConnectionError, RateLimitError, InternalServerError)

MODEL = "gpt-5.6-luna"
SYSTEM_PROMPT = (Path(__file__).resolve().parent.parent / "system_prompt.md").read_text(encoding="utf-8").strip()


def get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
        )
    return _client


class TriageProcessor:
    """Triage tickets."""

    def __init__(self, tickets: List[Dict[str, str]], ticket_fieldnames, triaged_keys):
        self.tickets = tickets
        self.ticket_fieldnames = ticket_fieldnames
        self.triaged_keys = triaged_keys
        self.triaged = []
        self.needs_review = []
        self.skipped = 0
        self.attempted_keys = []
        self.unattempted = []

    @retry(
        retry=retry_if_exception_type(RETRY_EXCEPTIONS),
        wait=wait_exponential_jitter(initial=INITIAL_WAIT, max=MAX_WAIT),
        stop=stop_after_attempt(STOP_COUNT),
        reraise=True,
    )
    def triage_ticket(self, ticket: Dict[str, str]) -> bool:
        """Triage a single ticket using the OpenAI API."""
        response = get_client().responses.parse(
            model=MODEL,
            input=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps({name: ticket[name] for name in LLM_TICKET_FIELDS}, ensure_ascii=False),
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
                        {**{name: ticket[name] for name in self.ticket_fieldnames}, "reason": "Refusal."})
                    self.attempted_keys.append(ticket_key(ticket, self.ticket_fieldnames))
                    return True  # indicate processing failed
                else:
                    self.triaged.append({**{name: ticket[name] for name in self.ticket_fieldnames},
                                         **response.output_parsed.model_dump()})
                    self.attempted_keys.append(ticket_key(ticket, self.ticket_fieldnames))
                    return False  # indicate processing succeeded

        self.needs_review.append(
            {**{name: ticket[name] for name in self.ticket_fieldnames}, "reason": "No usable response."})
        self.attempted_keys.append(ticket_key(ticket, self.ticket_fieldnames))
        return True  # indicate processing failed

    def triage_tickets(self) -> None:
        """Triage tickets using the OpenAI API."""
        unclassified_count = 0
        failed_retry_count = []

        for ticket in self.tickets:
            if ticket_key(ticket, self.ticket_fieldnames) in self.triaged_keys:
                self.skipped += 1
                continue

            try:
                unclassified_status = self.triage_ticket(ticket)
                unclassified_count += unclassified_status
                failed_retry_count.append(False)
            except RETRY_EXCEPTIONS as e:
                unclassified_count += 1
                self.needs_review.append(
                    {**{name: ticket[name] for name in self.ticket_fieldnames},
                     "reason": f"{type(e).__name__} after {STOP_COUNT} triage attempts."})
                self.attempted_keys.append(ticket_key(ticket, self.ticket_fieldnames))
                failed_retry_count.append(True)

                if len(failed_retry_count) >= ABORT_COUNT and all(failed_retry_count[-ABORT_COUNT:]):
                    self.unattempted = [ticket for ticket in self.tickets if
                                        ticket_key(ticket, self.ticket_fieldnames) not in self.attempted_keys]
                    raise RetryError(
                        f"Hit {ABORT_COUNT} consecutive API connection, rate-limit or internal server errors")

        if unclassified_count:
            logger.warning(f"{unclassified_count} tickets couldn't be classified. Review them in `needs_review.csv`.")
