from core.models import Claim, ExtractedFact, Finding, BLOCKING, INFO


def reconcile(claim: Claim, facts: list[ExtractedFact]) -> list[Finding]:
    """Pure Python, no LLM. Compares extracted facts against the claim record."""
    findings: list[Finding] = []

    for field in ("patient_id", "service_date"):
        claimed = getattr(claim, field)
        seen: dict[str, ExtractedFact] = {}
        for f in facts:
            if f.field == field and f.value:
                seen[f.value] = f
        conflicting = [v for v in seen if v != claimed]
        if conflicting:
            findings.append(Finding(
                check_name=f"{field}_match",
                severity=BLOCKING,
                message=(f"{field} in claim is {claimed} but documents show "
                         f"{', '.join(conflicting)}"),
                evidence=[seen[v].model_dump() for v in conflicting],
            ))

    present = {f.value for f in facts if f.field == "document_type" and f.value}
    for required in claim.required_documents:
        if required not in present:
            findings.append(Finding(
                check_name="required_document",
                severity=INFO,
                message=f"Missing required document: {required}",
                evidence=[],
            ))

    return findings


def status_after_reconcile(findings: list[Finding]) -> str:
    if any(f.severity == BLOCKING for f in findings):
        return "NEEDS_CORRECTION"
    if any(f.severity == INFO for f in findings):
        return "NEEDS_INFORMATION"
    return "READY_TO_DRAFT"
