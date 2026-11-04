from typing import Literal

from pydantic import BaseModel


class TriageSchema(BaseModel):
    """Define JSON output schema"""
    category: Literal["billing", "bug", "feature_request", "spam", "other"]
    urgency: Literal["low", "medium", "high"]
    model_reason: str
