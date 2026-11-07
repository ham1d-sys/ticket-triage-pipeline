import os
from logging import getLogger
from typing import List, Dict, Any

from dotenv import load_dotenv
from openai import OpenAI, APIConnectionError, RateLimitError, InternalServerError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter, RetryError

from schema import TriageSchema

logger = getLogger(__name__)

load_dotenv()
_client = None

INITIAL_WAIT = 1
MAX_WAIT = 10
STOP_COUNT = 6
ABORT_COUNT = 5

MODEL = "gpt-5.6-luna"
SYSTEM_PROMPT = "You're a support ticket triage assistant. Classify the ticket below.\nCategory:\n- billing: money: charges, refunds, invoices, plans, payment methods\n- bug: the product misbehaves or breaks, including login and access failures\n- feature_request: asks for something the product doesn't do yet\n- spam: unsolicited promos, scams, or phishing\n- other: real messages that fit none of the above (thanks, general questions)\nUrgency:\n- high: the customer can't use the product, is losing money, or has a security problem right now\n- medium: something is broken or wrong but they can work around it, or it needs a reply soon\n- low: no impact on their work\nRules:\n- If a ticket fits more than one category, choose the issue the customer explicitly asks to have fixed; if none, choose the one with the bigger impact; if still tied, the one mentioned first.\n- Judge urgency by real impact, not tone.\n- If the impact is unclear, use medium.\nGive a concise one-line reason."


def get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
        )
    return _client


class TriageProcessor:
    """Triage tickets."""

    def __init__(self, tickets: List[Dict[str, str]], ticket_fieldnames, triaged_ids):
        self.tickets = tickets
        self.ticket_fieldnames = ticket_fieldnames
        self.triaged_ids = triaged_ids
        self.triaged = []
        self.needs_review = []
        self.skipped = 0
        self.attempted_ids = []
        self.unattempted = []

    @retry(
        retry=retry_if_exception_type((APIConnectionError, RateLimitError, InternalServerError)),
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
                        {**{name: ticket[name] for name in self.ticket_fieldnames}, "reason": "Refusal."})
                    self.attempted_ids.append(ticket["ticket_id"])
                    return True  # indicate processing failed
                else:
                    self.triaged.append({**{name: ticket[name] for name in self.ticket_fieldnames},
                                         **response.output_parsed.model_dump()})
                    self.attempted_ids.append(ticket["ticket_id"])
                    return False  # indicate processing succeeded

        self.needs_review.append(
            {**{name: ticket[name] for name in self.ticket_fieldnames}, "reason": "No usable response."})
        self.attempted_ids.append(ticket["ticket_id"])
        return True  # indicate processing failed

    def triage_tickets(self) -> None:
        """Triage tickets using the OpenAI API."""
        unclassified_count = 0
        failed_retry_count = []

        for ticket in self.tickets:
            if ticket["ticket_id"] in self.triaged_ids:
                self.skipped += 1
                continue

            try:
                unclassified_status = self.triage_ticket(ticket)
                unclassified_count += unclassified_status
                failed_retry_count.append(False)
            except (APIConnectionError, RateLimitError) as e:
                unclassified_count += 1
                self.needs_review.append(
                    {**{name: ticket[name] for name in self.ticket_fieldnames},
                     "reason": f"{type(e).__name__} after {STOP_COUNT} triage attempts."})
                self.attempted_ids.append(ticket["ticket_id"])
                failed_retry_count.append(True)

                if len(failed_retry_count) >= ABORT_COUNT and all(failed_retry_count[-ABORT_COUNT:]):
                    self.unattempted = [ticket for ticket in self.tickets if ticket["ticket_id"] not in self.attempted_ids]
                    raise RetryError(f"Hit {ABORT_COUNT} consecutive API connection, rate-limit or internal server errors")

        if unclassified_count:
            logger.warning(f"{unclassified_count} tickets couldn't be classified. Review them in `needs_review.csv`.")
