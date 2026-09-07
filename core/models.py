from datetime import date
from typing import Literal

from pydantic import BaseModel, field_validator

BLOCKING = "BLOCKING"
INFO = "INFO"


class Claim(BaseModel):
    claim_id: str
    patient_id: str
    payer_id: str
    service_date: str
    denial_category: Literal["missing_documentation"]
    required_documents: list[str]

    @field_validator("service_date")
    @classmethod
    def valid_iso_date(cls, v: str) -> str:
        date.fromisoformat(v)  # raises ValueError on malformed input
        return v


class PageRecord(BaseModel):
    document_id: str
    page: int
    text: str
    unsupported: bool = False


class ExtractedFact(BaseModel):
    field: Literal["patient_id", "service_date", "document_type"]
    value: str | None
    document_id: str | None = None
    page: int | None = None
    source_text: str | None = None
    confidence: Literal["high", "medium", "low"] = "high"


class Finding(BaseModel):
    check_name: str
    severity: Literal["BLOCKING", "INFO"]
    message: str
    evidence: list[dict] = []


class PolicyChunk(BaseModel):
    chunk_id: str
    payer_id: str
    version: str
    effective_from: str
    effective_to: str | None
    title: str
    text: str


class Draft(BaseModel):
    body: str
    citations: list[str]
    status: Literal["draft", "approved", "rejected"] = "draft"


# ---- schemas passed to core.llm.structured() ----

class DocumentFactsModel(BaseModel):
    """One document's extractable facts, for a single messages.parse() call."""
    patient_id: str | None
    patient_id_source_text: str | None
    service_date: str | None
    service_date_source_text: str | None
    document_type: str | None
    document_type_source_text: str | None


class DraftModel(BaseModel):
    body: str
    citations: list[str]
