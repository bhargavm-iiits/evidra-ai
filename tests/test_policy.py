from core.policy import retrieve_policy


def test_payer_a_selects_v2_never_v1_for_2026_08_15():
    chunks = retrieve_policy("DEMO-PAYER-A", "2026-08-15", "missing_documentation",
                              ["referral_letter", "clinical_notes", "prior_auth"])
    versions = {c.version for c in chunks}
    assert versions == {"v2"}
    assert all(c.chunk_id.startswith("POL-A-V2") for c in chunks)


def test_payer_b_selects_v1_for_2026_03_10():
    chunks = retrieve_policy("DEMO-PAYER-B", "2026-03-10", "missing_documentation",
                              ["referral_letter", "clinical_notes", "prior_auth"])
    versions = {c.version for c in chunks}
    assert versions == {"v1"}
    assert all(c.chunk_id.startswith("POL-B-V1") for c in chunks)


def test_out_of_range_date_returns_empty():
    chunks = retrieve_policy("DEMO-PAYER-A", "2024-01-01", "missing_documentation")
    assert chunks == []


def test_unknown_payer_returns_empty():
    chunks = retrieve_policy("DEMO-PAYER-Z", "2026-08-15", "missing_documentation")
    assert chunks == []
