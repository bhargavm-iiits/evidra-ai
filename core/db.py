import json
import sqlite3
from datetime import datetime, timezone

from core.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  case_id TEXT PRIMARY KEY, claim_json TEXT, status TEXT,
  revision INTEGER DEFAULT 1, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS documents (
  document_id TEXT PRIMARY KEY, case_id TEXT, filename TEXT,
  sha256 TEXT, page_count INTEGER, doc_type TEXT);
CREATE TABLE IF NOT EXISTS pages (
  document_id TEXT, page INTEGER, text TEXT);
CREATE TABLE IF NOT EXISTS facts (
  case_id TEXT, revision INTEGER, field TEXT, value TEXT,
  document_id TEXT, page INTEGER, source_text TEXT, origin TEXT);
CREATE TABLE IF NOT EXISTS policy_chunks (
  chunk_id TEXT PRIMARY KEY, payer_id TEXT, version TEXT,
  effective_from TEXT, effective_to TEXT, title TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS findings (
  case_id TEXT, revision INTEGER, check_name TEXT, severity TEXT,
  message TEXT, evidence_json TEXT);
CREATE TABLE IF NOT EXISTS drafts (
  case_id TEXT, revision INTEGER, body TEXT,
  citations_json TEXT, status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS events (
  case_id TEXT, revision INTEGER, stage TEXT, detail TEXT, ts TEXT);
"""


def connect() -> sqlite3.Connection:
    # check_same_thread=False: Streamlit reruns the script on different worker
    # threads across interactions within the same session, but this app never
    # touches one connection from two threads concurrently, so this is safe.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(conn: sqlite3.Connection, case_id: str, revision: int, stage: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO events (case_id, revision, stage, detail, ts) VALUES (?, ?, ?, ?, ?)",
        (case_id, revision, stage, detail, _now()),
    )


# ---- cases ----

def create_case(conn: sqlite3.Connection, case_id: str, claim_json: dict, status: str = "UPLOADED") -> None:
    now = _now()
    conn.execute(
        "INSERT OR REPLACE INTO cases (case_id, claim_json, status, revision, created_at, updated_at) "
        "VALUES (?, ?, ?, 1, ?, ?)",
        (case_id, json.dumps(claim_json), status, now, now),
    )
    log_event(conn, case_id, 1, "UPLOADED", "case created")
    conn.commit()


def get_case(conn: sqlite3.Connection, case_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["claim_json"] = json.loads(d["claim_json"])
    return d


def list_cases(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM cases ORDER BY created_at DESC").fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["claim_json"] = json.loads(d["claim_json"])
        out.append(d)
    return out


def set_case_status(conn: sqlite3.Connection, case_id: str, status: str, stage: str, detail: str = "") -> None:
    case = get_case(conn, case_id)
    revision = case["revision"] if case else 1
    conn.execute(
        "UPDATE cases SET status = ?, updated_at = ? WHERE case_id = ?",
        (status, _now(), case_id),
    )
    log_event(conn, case_id, revision, stage, detail)
    conn.commit()


def bump_revision(conn: sqlite3.Connection, case_id: str) -> int:
    case = get_case(conn, case_id)
    new_rev = case["revision"] + 1
    conn.execute("UPDATE cases SET revision = ?, updated_at = ? WHERE case_id = ?", (new_rev, _now(), case_id))
    conn.commit()
    return new_rev


# ---- documents / pages ----

def insert_document(conn: sqlite3.Connection, document_id: str, case_id: str, filename: str,
                     sha256: str, page_count: int, doc_type: str | None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO documents (document_id, case_id, filename, sha256, page_count, doc_type) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (document_id, case_id, filename, sha256, page_count, doc_type),
    )
    conn.commit()


def get_documents(conn: sqlite3.Connection, case_id: str) -> list[dict]:
    rows = conn.execute("SELECT * FROM documents WHERE case_id = ?", (case_id,)).fetchall()
    return [dict(r) for r in rows]


def insert_page(conn: sqlite3.Connection, document_id: str, page: int, text: str) -> None:
    # document_id is now globally unique per case (see parsing.parse_documents), but
    # delete-then-insert keeps re-processing the same document idempotent regardless.
    conn.execute("DELETE FROM pages WHERE document_id = ? AND page = ?", (document_id, page))
    conn.execute("INSERT INTO pages (document_id, page, text) VALUES (?, ?, ?)", (document_id, page, text))
    conn.commit()


def get_pages(conn: sqlite3.Connection, document_ids: list[str]) -> list[dict]:
    if not document_ids:
        return []
    placeholders = ",".join("?" for _ in document_ids)
    rows = conn.execute(
        f"SELECT * FROM pages WHERE document_id IN ({placeholders}) ORDER BY document_id, page",
        document_ids,
    ).fetchall()
    return [dict(r) for r in rows]


# ---- facts ----

def insert_fact(conn: sqlite3.Connection, case_id: str, revision: int, field: str, value: str | None,
                 document_id: str | None, page: int | None, source_text: str | None, origin: str) -> None:
    conn.execute(
        "INSERT INTO facts (case_id, revision, field, value, document_id, page, source_text, origin) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (case_id, revision, field, value, document_id, page, source_text, origin),
    )
    conn.commit()


def get_facts(conn: sqlite3.Connection, case_id: str, revision: int) -> list[dict]:
    """Reviewer-origin facts win over extracted facts for the same field+value context.

    Returns every row (both origins) — callers that need "latest per field" should
    prefer rows with origin == 'reviewer' when present.
    """
    rows = conn.execute(
        "SELECT * FROM facts WHERE case_id = ? AND revision = ? ORDER BY field, origin",
        (case_id, revision),
    ).fetchall()
    return [dict(r) for r in rows]


def get_effective_facts(conn: sqlite3.Connection, case_id: str, revision: int) -> list[dict]:
    """Collapse to one fact per field: a reviewer correction overrides extracted facts."""
    all_facts = get_facts(conn, case_id, revision)
    reviewer_fields = {f["field"] for f in all_facts if f["origin"] == "reviewer"}
    effective = [f for f in all_facts if f["origin"] == "reviewer"]
    effective += [f for f in all_facts if f["origin"] == "extracted" and f["field"] not in reviewer_fields]
    return effective


# ---- policy_chunks ----

def upsert_policy_chunk(conn: sqlite3.Connection, chunk: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO policy_chunks "
        "(chunk_id, payer_id, version, effective_from, effective_to, title, text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (chunk["chunk_id"], chunk["payer_id"], chunk["version"], chunk["effective_from"],
         chunk.get("effective_to"), chunk["title"], chunk["text"]),
    )
    conn.commit()


def get_policy_chunks(conn: sqlite3.Connection, payer_id: str | None = None) -> list[dict]:
    if payer_id:
        rows = conn.execute("SELECT * FROM policy_chunks WHERE payer_id = ?", (payer_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM policy_chunks").fetchall()
    return [dict(r) for r in rows]


# ---- findings ----

def insert_finding(conn: sqlite3.Connection, case_id: str, revision: int, check_name: str,
                    severity: str, message: str, evidence: list) -> None:
    conn.execute(
        "INSERT INTO findings (case_id, revision, check_name, severity, message, evidence_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (case_id, revision, check_name, severity, message, json.dumps(evidence)),
    )
    conn.commit()


def get_findings(conn: sqlite3.Connection, case_id: str, revision: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM findings WHERE case_id = ? AND revision = ?", (case_id, revision)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["evidence"] = json.loads(d["evidence_json"])
        out.append(d)
    return out


def clear_findings(conn: sqlite3.Connection, case_id: str, revision: int) -> None:
    conn.execute("DELETE FROM findings WHERE case_id = ? AND revision = ?", (case_id, revision))
    conn.commit()


# ---- drafts ----

def insert_draft(conn: sqlite3.Connection, case_id: str, revision: int, body: str,
                  citations: list[str], status: str) -> None:
    # Idempotency: don't create a duplicate draft for the same case+revision.
    existing = conn.execute(
        "SELECT rowid FROM drafts WHERE case_id = ? AND revision = ?", (case_id, revision)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE drafts SET body = ?, citations_json = ?, status = ? WHERE rowid = ?",
            (body, json.dumps(citations), status, existing["rowid"]),
        )
    else:
        conn.execute(
            "INSERT INTO drafts (case_id, revision, body, citations_json, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (case_id, revision, body, json.dumps(citations), status, _now()),
        )
    conn.commit()


def get_draft(conn: sqlite3.Connection, case_id: str, revision: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM drafts WHERE case_id = ? AND revision = ?", (case_id, revision)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["citations"] = json.loads(d["citations_json"])
    return d


def update_draft_body(conn: sqlite3.Connection, case_id: str, revision: int, body: str, status: str) -> None:
    conn.execute(
        "UPDATE drafts SET body = ?, status = ? WHERE case_id = ? AND revision = ?",
        (body, status, case_id, revision),
    )
    conn.commit()


# ---- events ----

def get_events(conn: sqlite3.Connection, case_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM events WHERE case_id = ? ORDER BY ts", (case_id,)
    ).fetchall()
    return [dict(r) for r in rows]
