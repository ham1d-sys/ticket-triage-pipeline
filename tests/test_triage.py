from unittest.mock import MagicMock, patch

import pytest
from openai import APIConnectionError
from tenacity import wait_none, RetryError

from triage import TriageProcessor, STOP_COUNT

test_tickets = [{
    "sender": "maria.k@example.com",
    "subject": "Can't log in",
    "body": "I get invalid credentials every time I try.",
    "received_at": "2026-08-19 07:12:00"
}, ]


@pytest.fixture
def triage_processor():
    return TriageProcessor(test_tickets, output_path="some path", abort_count=1)


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
    return response


@patch("triage.get_client")
def test_triage_ticket_retry_after_transient_error(mock_client, triage_processor: TriageProcessor):
    """Ensure triage_ticket() retries after API connection errors."""
    triage_processor.triage_ticket.retry.wait = wait_none()
    mock_client.return_value.responses.parse.side_effect = APIConnectionError(request=MagicMock())
    with pytest.raises(APIConnectionError):
        triage_processor.triage_ticket(test_tickets[0])

    stats = triage_processor.triage_ticket.statistics
    assert "attempt_number" in stats
    assert stats["attempt_number"] == STOP_COUNT


@patch("triage.get_client")
def test_triage_tickets_abort_after_consecutive_transient_errors(mock_client: MagicMock,
                                                                 triage_processor: TriageProcessor):
    """Ensure triage_tickets() abort current batch after consecutive API connection errors."""
    triage_processor.triage_ticket.retry.wait = wait_none()
    mock_client.return_value.responses.parse.side_effect = APIConnectionError(request=MagicMock())
    with pytest.raises(RetryError):
        triage_processor.triage_tickets()


@patch("triage.get_client")
def test_triage_tickets_handles_refusal_response(mock_client: MagicMock, triage_processor: TriageProcessor):
    """Ensure refused tickets are added to TriageProcessor.needs_review with the correct reason."""
    mock_client.return_value.responses.parse.return_value = make_response_output(refusal=True)
    triage_processor.triage_tickets()
    assert triage_processor.needs_review, "Expected refused ticket to require review."
    assert triage_processor.needs_review[0] == {
        "content": test_tickets[0],
        "reason": "Refusal.",
    }
