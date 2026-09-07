import re

from core.llm import structured, LLMUnavailable
from core.models import ExtractedFact, PageRecord, DocumentFactsModel

PATIENT_ID_RE = re.compile(r"Patient ID:\s*(\S+)")
SERVICE_DATE_RE = re.compile(r"Date of Service:\s*(\d{4}-\d{2}-\d{2})")
DOC_TYPE_RE = re.compile(r"Document Type:\s*(\S+)")


def _document_text(pages: list[PageRecord], document_id: str) -> str:
    return "\n".join(p.text for p in pages if p.document_id == document_id)


def _first_page_with_line(pages: list[PageRecord], document_id: str, line_prefix: str) -> tuple[int | None, str | None]:
    for p in pages:
        if p.document_id != document_id:
            continue
        for line in p.text.splitlines():
            if line.strip().startswith(line_prefix):
                return p.page, line.strip()
    return None, None


def _extract_regex(pages: list[PageRecord], document_id: str) -> list[ExtractedFact]:
    text = _document_text(pages, document_id)
    facts = []

    m = PATIENT_ID_RE.search(text)
    if m:
        page, source = _first_page_with_line(pages, document_id, "Patient ID:")
        facts.append(ExtractedFact(field="patient_id", value=m.group(1), document_id=document_id,
                                    page=page, source_text=source, confidence="high"))

    m = SERVICE_DATE_RE.search(text)
    if m:
        page, source = _first_page_with_line(pages, document_id, "Date of Service:")
        facts.append(ExtractedFact(field="service_date", value=m.group(1), document_id=document_id,
                                    page=page, source_text=source, confidence="high"))

    m = DOC_TYPE_RE.search(text)
    if m:
        page, source = _first_page_with_line(pages, document_id, "Document Type:")
        facts.append(ExtractedFact(field="document_type", value=m.group(1), document_id=document_id,
                                    page=page, source_text=source, confidence="high"))

    return facts


def _extract_llm(pages: list[PageRecord], document_id: str) -> list[ExtractedFact]:
    text = _document_text(pages, document_id)
    prompt = (
        "Extract patient_id, service_date (YYYY-MM-DD), and document_type from this "
        "document. For each, also return the exact source line it came from "
        f"(*_source_text). Use null for anything not present.\n\n{text}"
    )
    parsed: DocumentFactsModel = structured(prompt, DocumentFactsModel)
    facts = []
    field_map = [
        ("patient_id", parsed.patient_id, parsed.patient_id_source_text),
        ("service_date", parsed.service_date, parsed.service_date_source_text),
        ("document_type", parsed.document_type, parsed.document_type_source_text),
    ]
    for field, value, source_text in field_map:
        if value is None:
            continue
        page = None
        if source_text:
            for p in pages:
                if p.document_id == document_id and source_text in p.text:
                    page = p.page
                    break
        facts.append(ExtractedFact(field=field, value=value, document_id=document_id,
                                    page=page, source_text=source_text, confidence="high"))
    return facts


def extract_fields(pages: list[PageRecord]) -> list[ExtractedFact]:
    """One extraction pass per document. Falls back to regex when the LLM is unavailable."""
    document_ids = sorted({p.document_id for p in pages})
    all_facts: list[ExtractedFact] = []
    for document_id in document_ids:
        try:
            all_facts.extend(_extract_llm(pages, document_id))
        except LLMUnavailable:
            all_facts.extend(_extract_regex(pages, document_id))
    return all_facts
