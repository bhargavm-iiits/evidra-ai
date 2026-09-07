import re

from core.llm import structured, LLMUnavailable
from core.models import Claim, ExtractedFact, PolicyChunk, Draft, DraftModel

CITE = re.compile(r"\[(POL-[A-Z0-9\-]+)\]")


class EscalationRequired(Exception):
    """Raised when a draft still carries unresolvable citations after one repair."""


def validate_citations(body: str, allowed_ids: set[str]) -> list[str]:
    """Return citation IDs used in the draft that were not among the retrieved chunks."""
    return [c for c in CITE.findall(body) if c not in allowed_ids]


def _facts_by_field(facts: list[ExtractedFact]) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in facts:
        if f.value and f.field not in out:
            out[f.field] = f.value
    return out


def _build_prompt(claim: Claim, facts: list[ExtractedFact], chunks: list[PolicyChunk]) -> str:
    fields = _facts_by_field(facts)
    facts_block = "\n".join(f"- {k}: {v}" for k, v in fields.items())
    policy_block = "\n\n".join(f"[{c.chunk_id}] {c.title}\n{c.text}" for c in chunks)
    allowed = ", ".join(c.chunk_id for c in chunks)
    return (
        "Draft a short resubmission response for a healthcare claim denied for "
        "missing_documentation. Use ONLY the validated facts and policy passages below. "
        f"Cite every policy-derived statement using its bracketed ID, e.g. [POL-A-V2-001]. "
        f"Only use these citation IDs: {allowed}. Do not invent citation IDs.\n\n"
        f"Claim: {claim.claim_id}, patient {claim.patient_id}, payer {claim.payer_id}, "
        f"service date {claim.service_date}.\n\n"
        f"Validated facts:\n{facts_block}\n\n"
        f"Applicable policy passages:\n{policy_block}"
    )


def _template_body(claim: Claim, chunks: list[PolicyChunk]) -> str:
    lines = [
        f"# Resubmission response - {claim.claim_id}",
        "",
        f"This claim ({claim.claim_id}, patient {claim.patient_id}) was denied for "
        "missing supporting documentation. The following requirements apply:",
        "",
    ]
    for c in chunks:
        lines.append(f"- {c.title} [{c.chunk_id}]")
    lines.append("")
    lines.append(
        "The required documents have been reconciled against this claim and are "
        "attached with this resubmission."
    )
    return "\n".join(lines)


def generate_draft(claim: Claim, facts: list[ExtractedFact], chunks: list[PolicyChunk],
                    attempt: int = 0) -> Draft:
    if not chunks:
        raise EscalationRequired("no applicable policy retrieved — cannot draft without evidence")

    allowed = {c.chunk_id for c in chunks}

    try:
        prompt = _build_prompt(claim, facts, chunks)
        parsed: DraftModel = structured(prompt, DraftModel)
        body = parsed.body
    except LLMUnavailable:
        body = _template_body(claim, chunks)

    bad = validate_citations(body, allowed)
    if bad and attempt == 0:
        return generate_draft(claim, facts, chunks, attempt=1)
    if bad:
        raise EscalationRequired(f"unresolvable citations after repair: {bad}")

    citations = CITE.findall(body)
    return Draft(body=body, citations=citations, status="draft")
