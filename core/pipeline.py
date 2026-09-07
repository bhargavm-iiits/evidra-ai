import json
import sqlite3
from pathlib import Path

from core import db
from core.drafting import generate_draft, EscalationRequired
from core.extraction import extract_fields
from core.models import Claim, ExtractedFact
from core.parsing import parse_documents
from core.policy import retrieve_policy
from core.reconcile import reconcile, status_after_reconcile


def create_case_from_upload(conn: sqlite3.Connection, claim: Claim, pdf_paths: list[Path]) -> str:
    """UPLOADED. Idempotent: re-running with the same claim_id updates in place."""
    case_id = claim.claim_id
    db.create_case(conn, case_id, claim.model_dump())

    records, meta = parse_documents(pdf_paths, case_id)
    for document_id, m in meta.items():
        doc_type = None
        for r in records:
            if r.document_id == document_id and "Document Type:" in r.text:
                for line in r.text.splitlines():
                    if line.strip().startswith("Document Type:"):
                        doc_type = line.split(":", 1)[1].strip()
        db.insert_document(conn, document_id, case_id, m["filename"], m["sha256"],
                            m["page_count"], doc_type)
    for r in records:
        db.insert_page(conn, r.document_id, r.page, r.text)

    return case_id


def run_extraction_and_reconcile(conn: sqlite3.Connection, case_id: str) -> str:
    """EXTRACTED -> {NEEDS_CORRECTION | NEEDS_INFORMATION | READY_TO_DRAFT}.

    Idempotent per (case_id, revision, stage): re-running clears and recomputes this
    revision's extracted facts and findings rather than appending duplicates.
    """
    case = db.get_case(conn, case_id)
    revision = case["revision"]
    claim = Claim(**case["claim_json"])

    documents = db.get_documents(conn, case_id)
    document_ids = [d["document_id"] for d in documents]
    page_rows = db.get_pages(conn, document_ids)

    from core.models import PageRecord
    pages = [PageRecord(document_id=p["document_id"], page=p["page"], text=p["text"]) for p in page_rows]

    already_extracted = conn.execute(
        "SELECT COUNT(*) c FROM facts WHERE case_id=? AND revision=? AND origin='extracted'",
        (case_id, revision),
    ).fetchone()["c"]
    if already_extracted == 0:
        facts = extract_fields(pages)
        for f in facts:
            db.insert_fact(conn, case_id, revision, f.field, f.value, f.document_id,
                            f.page, f.source_text, "extracted")
        fact_count = len(facts)
    else:
        fact_count = already_extracted
    db.log_event(conn, case_id, revision, "EXTRACTED", f"{fact_count} facts")
    conn.commit()

    effective_facts = [ExtractedFact(**{k: v for k, v in f.items() if k in ExtractedFact.model_fields})
                        for f in db.get_effective_facts(conn, case_id, revision)]

    findings = reconcile(claim, effective_facts)
    db.clear_findings(conn, case_id, revision)
    for f in findings:
        db.insert_finding(conn, case_id, revision, f.check_name, f.severity, f.message, f.evidence)

    status = status_after_reconcile(findings)
    db.set_case_status(conn, case_id, status, status, f"{len(findings)} findings")
    return status


def run_retrieve_and_draft(conn: sqlite3.Connection, case_id: str) -> str:
    """READY_TO_DRAFT -> NEEDS_REVIEW (or FAILED on escalation).

    Idempotent: re-running replaces this revision's draft rather than duplicating it.
    """
    case = db.get_case(conn, case_id)
    revision = case["revision"]
    claim = Claim(**case["claim_json"])

    if case["status"] != "READY_TO_DRAFT":
        raise ValueError(f"case {case_id} is not READY_TO_DRAFT (status={case['status']})")

    effective_facts = [ExtractedFact(**{k: v for k, v in f.items() if k in ExtractedFact.model_fields})
                        for f in db.get_effective_facts(conn, case_id, revision)]

    chunks = retrieve_policy(claim.payer_id, claim.service_date, claim.denial_category,
                              claim.required_documents)

    try:
        draft = generate_draft(claim, effective_facts, chunks)
    except EscalationRequired as e:
        db.set_case_status(conn, case_id, "FAILED", "FAILED", str(e))
        return "FAILED"

    db.insert_draft(conn, case_id, revision, draft.body, draft.citations, "draft")
    db.set_case_status(conn, case_id, "NEEDS_REVIEW", "NEEDS_REVIEW",
                        f"{len(chunks)} policy chunks retrieved")
    return "NEEDS_REVIEW"


def process_case(conn: sqlite3.Connection, case_id: str) -> str:
    """Run every valid next stage for a case until it reaches a terminal or review status."""
    status = run_extraction_and_reconcile(conn, case_id)
    if status == "READY_TO_DRAFT":
        status = run_retrieve_and_draft(conn, case_id)
    return status


def submit_correction(conn: sqlite3.Connection, case_id: str, field: str, value: str,
                       document_id: str | None = None, page: int | None = None,
                       source_text: str | None = None) -> str:
    """Insert a reviewer-origin fact (never overwrites extracted evidence) and reprocess."""
    case = db.get_case(conn, case_id)
    revision = case["revision"]
    db.insert_fact(conn, case_id, revision, field, value, document_id, page,
                    source_text or f"reviewer correction: {field}={value}", "reviewer")
    db.log_event(conn, case_id, revision, "CORRECTION", f"{field} -> {value}")
    return process_case(conn, case_id)


def approve_draft(conn: sqlite3.Connection, case_id: str, edited_body: str | None = None) -> None:
    case = db.get_case(conn, case_id)
    revision = case["revision"]
    if edited_body is not None:
        draft = db.get_draft(conn, case_id, revision)
        db.update_draft_body(conn, case_id, revision, edited_body, "approved")
    else:
        db.update_draft_body(conn, case_id, revision,
                              db.get_draft(conn, case_id, revision)["body"], "approved")
    db.set_case_status(conn, case_id, "APPROVED", "APPROVED", "reviewer approved")
