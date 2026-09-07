from core.reconcile import reconcile, status_after_reconcile
from tests.helpers import load_case


def test_case_01_clean_has_no_findings():
    claim, facts = load_case("case_01_clean")
    findings = reconcile(claim, facts)
    assert findings == []
    assert status_after_reconcile(findings) == "READY_TO_DRAFT"


def test_case_02_mismatch_is_blocking_with_both_values():
    claim, facts = load_case("case_02_mismatch")
    findings = reconcile(claim, facts)
    blocking = [f for f in findings if f.severity == "BLOCKING"]
    assert len(blocking) == 1
    assert blocking[0].check_name == "patient_id_match"
    assert "SYN-101" in blocking[0].message
    assert "SYN-999" in blocking[0].message
    assert status_after_reconcile(findings) == "NEEDS_CORRECTION"


def test_case_03_missing_document_is_info():
    claim, facts = load_case("case_03_missing")
    findings = reconcile(claim, facts)
    info = [f for f in findings if f.severity == "INFO"]
    assert any(f.check_name == "required_document" and "prior_auth" in f.message for f in info)
    assert status_after_reconcile(findings) == "NEEDS_INFORMATION"
