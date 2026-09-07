import pytest

from core.drafting import validate_citations, generate_draft, EscalationRequired
from core.policy import retrieve_policy
from tests.helpers import load_case


def test_validate_citations_rejects_unresolvable_id():
    allowed = {"POL-A-V2-001", "POL-A-V2-002"}
    bad = validate_citations("See [POL-A-V2-001] and [POL-FAKE-999].", allowed)
    assert bad == ["POL-FAKE-999"]


def test_validate_citations_accepts_all_known_ids():
    allowed = {"POL-A-V2-001", "POL-A-V2-002"}
    bad = validate_citations("See [POL-A-V2-001] and [POL-A-V2-002].", allowed)
    assert bad == []


def test_template_mode_draft_never_invents_citations():
    claim, facts = load_case("case_01_clean")
    chunks = retrieve_policy(claim.payer_id, claim.service_date, claim.denial_category,
                              claim.required_documents)
    draft = generate_draft(claim, facts, chunks)
    allowed = {c.chunk_id for c in chunks}
    assert validate_citations(draft.body, allowed) == []
    assert set(draft.citations).issubset(allowed)


def test_bounded_repair_escalates_after_one_retry(monkeypatch):
    """Simulate a persistently bad LLM response: repair is attempted exactly once,
    then EscalationRequired is raised — never an infinite loop."""
    claim, facts = load_case("case_01_clean")
    chunks = retrieve_policy(claim.payer_id, claim.service_date, claim.denial_category,
                              claim.required_documents)

    call_count = {"n": 0}

    def fake_structured(prompt, schema):
        call_count["n"] += 1
        return schema(body="Cites [POL-FAKE-999].", citations=["POL-FAKE-999"])

    monkeypatch.setattr("core.drafting.structured", fake_structured)

    with pytest.raises(EscalationRequired):
        generate_draft(claim, facts, chunks)

    assert call_count["n"] == 2  # original attempt + exactly one repair


def test_no_applicable_policy_raises_escalation():
    claim, facts = load_case("case_01_clean")
    with pytest.raises(EscalationRequired):
        generate_draft(claim, facts, chunks=[])
