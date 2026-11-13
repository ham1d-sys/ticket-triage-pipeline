import hashlib
import json
from pathlib import Path


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ticket_key(ticket: dict, fieldnames: tuple[str, ...]) -> tuple[str, str]:
    """Identify a ticket by its id plus a hash of its other fields."""
    content = [ticket.get(name) for name in fieldnames if name != "ticket_id"]
    return ticket.get("ticket_id"), sha256_text(json.dumps(content))
