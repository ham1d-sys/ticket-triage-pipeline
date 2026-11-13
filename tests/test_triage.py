import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APIConnectionError
from tenacity import wait_none, RetryError

from triage import TriageProcessor, STOP_COUNT

TICKET_FIELDNAMES = ("ticket_id", "sender", "subject", "body", "received_at")

test_tickets = [{
    "ticket_id": "T01",
    "sender": "maria.k@example.com",
    "subject": "Can't log in",
    "body": "I get invalid credentials every time I try.",
    "received_at": "2026-08-19 07:12:00"
}, ]


def make_tickets(count: int) -> list[dict[str, str]]:
    """Create distinct tickets whose subject encodes their position (S0, S1, ...)."""
    return [{**test_tickets[0], "ticket_id": f"T{index:02d}", "subject": f"S{index}"} for index in range(count)]


@pytest.fixture
def triage_processor():
    return TriageProcessor(test_tickets, TICKET_FIELDNAMES, triaged_keys=set())


def make_response_output(refusal: bool = False, fail: bool = False) -> MagicMock | None:
    """
    Create a mock response or raise an exception.
    :param refusal: Whether to create a refusal response.
    :param fail: Whether to raise an exception.
    :return: A MagicMock response unless an exception is raised.
    """
    if fail:
        raise APIConnectionError(
            request=MagicMock()
        )
    content_item = MagicMock()
    content_item.type = "refusal" if refusal else "output_text"
    output = MagicMock()
    output.type = "message"
    output.content = [content_item]
    response = MagicMock()
    response.output = [output]
    response.output_parsed.model_dump.return_value = {"category": "bug", "urgency": "low", "model_reason": "test"}
    return response


@patch("triage.get_client")
def test_triage_ticket_retry_after_transient_error(mock_client, triage_processor: TriageProcessor):
    """Ensure triage_ticket() retries after API connection errors."""
    triage_processor.triage_ticket.retry.wait = wait_none()
    mock_client.return_value.responses.parse = AsyncMock(side_effect=APIConnectionError(request=MagicMock()))
    with pytest.raises(APIConnectionError):
        asyncio.run(triage_processor.triage_ticket(test_tickets[0]))

    stats = triage_processor.triage_ticket.statistics
    assert "attempt_number" in stats
    assert stats["attempt_number"] == STOP_COUNT


@patch("triage.get_client")
def test_triage_tickets_abort_after_consecutive_transient_errors(mock_client: MagicMock,
                                                                 monkeypatch: pytest.MonkeyPatch):
    """Ensure triage_tickets() abort current batch after consecutive API connection errors."""
    monkeypatch.setattr("triage.ABORT_COUNT", 1)
    monkeypatch.setattr("triage.MAX_CONCURRENCY", 1)
    processor = TriageProcessor(make_tickets(3), TICKET_FIELDNAMES, triaged_keys=set())
    processor.triage_ticket.retry.wait = wait_none()
    mock_client.return_value.responses.parse = AsyncMock(side_effect=APIConnectionError(request=MagicMock()))
    with pytest.raises(RetryError):
        asyncio.run(processor.triage_tickets())

    assert len(processor.needs_review) == 1, "Only the first ticket should have been attempted."
    assert [ticket["ticket_id"] for ticket in processor.unattempted] == ["T01", "T02"]


@patch("triage.get_client")
def test_triage_tickets_handles_refusal_response(mock_client: MagicMock, triage_processor: TriageProcessor):
    """Ensure refused tickets are added to TriageProcessor.needs_review with the correct reason."""
    mock_client.return_value.responses.parse = AsyncMock(return_value=make_response_output(refusal=True))
    asyncio.run(triage_processor.triage_tickets())
    assert triage_processor.needs_review, "Expected refused ticket to require review."
    assert triage_processor.needs_review[0] == {
        **test_tickets[0],
        "reason": "Refusal.",
    }


@patch("triage.get_client")
def test_triage_tickets_respects_max_concurrency(mock_client: MagicMock, monkeypatch: pytest.MonkeyPatch):
    """Ensure no more than MAX_CONCURRENCY API calls are in flight at once."""
    monkeypatch.setattr("triage.MAX_CONCURRENCY", 2)
    in_flight = peak = 0

    async def slow_parse(**kwargs):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return make_response_output()

    mock_client.return_value.responses.parse = slow_parse
    processor = TriageProcessor(make_tickets(6), TICKET_FIELDNAMES, triaged_keys=set())
    asyncio.run(processor.triage_tickets())

    assert peak == 2
    assert len(processor.triaged) == 6


@patch("triage.get_client")
def test_triage_tickets_keeps_input_order(mock_client: MagicMock, monkeypatch: pytest.MonkeyPatch):
    """Ensure results are in input order even when later tickets finish first."""
    monkeypatch.setattr("triage.MAX_CONCURRENCY", 6)

    async def parse_later_tickets_faster(**kwargs):
        index = int(json.loads(kwargs["input"][1]["content"])["subject"][1:])
        await asyncio.sleep(0.01 * (6 - index))
        return make_response_output()

    mock_client.return_value.responses.parse = parse_later_tickets_faster
    tickets = make_tickets(6)
    processor = TriageProcessor(tickets, TICKET_FIELDNAMES, triaged_keys=set())
    asyncio.run(processor.triage_tickets())

    assert [row["ticket_id"] for row in processor.triaged] == [ticket["ticket_id"] for ticket in tickets]
