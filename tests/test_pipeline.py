import json
import sqlite3

import pytest

from core.config import FIXTURES_DIR
from core.db import connect, init_db, get_draft, get_events, get_findings
from core.models import Claim
from core.pipeline import create_case_from_upload, process_case, submit_correction


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """A fresh, isolated SQLite DB per test — never touches claimbridge.db."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("core.config.DB_PATH", db_path)
    monkeypatch.setattr("core.db.DB_PATH", db_path)
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    c.executescript(__import__("core.db", fromlist=["SCHEMA"]).SCHEMA)
    c.commit()
    from core.policy import _load_all_chunks
    from core.db import upsert_policy_chunk
    for chunk in _load_all_chunks():
        upsert_policy_chunk(c, chunk.model_dump())
    yield c
    c.close()


def _load_and_run(conn, case_name: str) -> str:
    case_dir = FIXTURES_DIR / case_name
    claim = Claim(**json.loads((case_dir / "claim.json").read_text()))
    pdf_paths = sorted(p for p in case_dir.glob("*.pdf"))
    case_id = create_case_from_upload(conn, claim, pdf_paths)
    return process_case(conn, case_id), case_id


def test_case_01_reaches_needs_review_with_a_draft(conn):
    status, case_id = _load_and_run(conn, "case_01_clean")
    assert status == "NEEDS_REVIEW"
    draft = get_draft(conn, case_id, 1)
    assert draft is not None
    assert len(draft["citations"]) > 0


def test_case_02_blocks_with_both_values_shown(conn):
    status, case_id = _load_and_run(conn, "case_02_mismatch")
    assert status == "NEEDS_CORRECTION"
    findings = get_findings(conn, case_id, 1)
    assert any("SYN-101" in f["message"] and "SYN-999" in f["message"] for f in findings)
    assert get_draft(conn, case_id, 1) is None


def test_case_03_needs_information_for_missing_prior_auth(conn):
    status, case_id = _load_and_run(conn, "case_03_missing")
    assert status == "NEEDS_INFORMATION"
    findings = get_findings(conn, case_id, 1)
    assert any("prior_auth" in f["message"] for f in findings)


def test_correction_unblocks_case_02_and_reaches_a_draft(conn):
    _status, case_id = _load_and_run(conn, "case_02_mismatch")
    status = submit_correction(conn, case_id, "patient_id", "SYN-101")
    assert status == "NEEDS_REVIEW"
    assert get_draft(conn, case_id, 1) is not None


def test_reprocessing_does_not_duplicate_draft_or_events(conn):
    status, case_id = _load_and_run(conn, "case_01_clean")
    events_after_first = len(get_events(conn, case_id))
    process_case(conn, case_id)
    process_case(conn, case_id)
    draft_rows = conn.execute("SELECT COUNT(*) c FROM drafts WHERE case_id=?", (case_id,)).fetchone()["c"]
    fact_rows = conn.execute(
        "SELECT COUNT(*) c FROM facts WHERE case_id=? AND origin='extracted'", (case_id,)
    ).fetchone()["c"]
    assert draft_rows == 1
    assert fact_rows == 9  # unchanged across reprocessing
    # events grow (append-only audit log) but draft/fact state does not duplicate
    assert len(get_events(conn, case_id)) > events_after_first


def test_injection_fixture_behaves_like_a_clean_case(conn):
    status, case_id = _load_and_run(conn, "case_04_injection")
    assert status == "NEEDS_REVIEW"
    findings = get_findings(conn, case_id, 1)
    assert findings == []


def test_case_reloads_after_simulated_restart(conn, tmp_path):
    """A second connection to the same DB file sees the same state — simulates the
    app being killed and restarted mid-review."""
    status, case_id = _load_and_run(conn, "case_01_clean")
    assert status == "NEEDS_REVIEW"

    db_path = tmp_path / "test.db"
    conn2 = sqlite3.connect(db_path)
    conn2.row_factory = sqlite3.Row
    draft = get_draft(conn2, case_id, 1)
    assert draft is not None
    assert draft["status"] == "draft"
    conn2.close()
