"""ClaimBridge — Streamlit review UI. A thin shell over core/. No business logic here."""
import json
import sys
from pathlib import Path

# Allow `streamlit run ui/app.py` to find the core/ package one level up.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from core.config import LLM_MODE, UPLOAD_DIR
from core.db import (
    connect, get_case, get_documents, get_draft, get_effective_facts,
    get_events, get_findings, list_cases,
)
from core.export import export_evidence_json, export_markdown
from core.models import Claim
from core.pipeline import approve_draft, create_case_from_upload, process_case, submit_correction

st.set_page_config(page_title="ClaimBridge", layout="wide")


def get_conn():
    if "conn" not in st.session_state:
        st.session_state.conn = connect()
    return st.session_state.conn


def upload_panel():
    st.subheader("New case")
    claim_file = st.file_uploader("Claim JSON", type=["json"], key="claim_upload")
    pdf_files = st.file_uploader("Supporting PDFs", type=["pdf"], accept_multiple_files=True, key="pdf_upload")

    if st.button("Create case", disabled=not (claim_file and pdf_files)):
        conn = get_conn()
        claim_data = json.loads(claim_file.read())
        claim = Claim(**claim_data)

        case_dir = UPLOAD_DIR / claim.claim_id
        case_dir.mkdir(parents=True, exist_ok=True)
        pdf_paths = []
        for f in pdf_files:
            path = case_dir / f.name
            path.write_bytes(f.read())
            pdf_paths.append(path)

        case_id = create_case_from_upload(conn, claim, pdf_paths)
        process_case(conn, case_id)
        st.session_state.case_id = case_id
        st.rerun()


def case_picker():
    conn = get_conn()
    cases = list_cases(conn)
    if not cases:
        return
    labels = [f"{c['case_id']} — {c['status']}" for c in cases]
    ids = [c["case_id"] for c in cases]
    current = st.session_state.get("case_id")
    index = ids.index(current) if current in ids else 0
    choice = st.selectbox("Open case", labels, index=index)
    st.session_state.case_id = ids[labels.index(choice)]


def left_column(conn, case_id: str, revision: int):
    st.markdown("### Documents & facts")
    docs = get_documents(conn, case_id)
    for d in docs:
        st.caption(f"{d['document_id']}: {d['filename']} ({d['page_count']} pg) — {d['doc_type'] or 'unknown type'}")

    facts = get_effective_facts(conn, case_id, revision)
    if facts:
        for f in facts:
            origin_tag = "✏️ reviewer" if f["origin"] == "reviewer" else "extracted"
            with st.expander(f"{f['field']}: {f['value']}  ({origin_tag})"):
                st.write(f"Document: {f['document_id']}, page {f['page']}")
                st.code(f['source_text'] or "")
    else:
        st.caption("No facts extracted yet.")

    st.markdown("### Findings")
    findings = get_findings(conn, case_id, revision)
    if not findings:
        st.success("No findings.")
    for f in findings:
        if f["severity"] == "BLOCKING":
            st.error(f"[{f['check_name']}] {f['message']}")
        else:
            st.warning(f"[{f['check_name']}] {f['message']}")

    blocking = [f for f in findings if f["severity"] == "BLOCKING"]
    if blocking:
        st.markdown("#### Submit correction")
        field = st.selectbox("Field", ["patient_id", "service_date"], key="corr_field")
        value = st.text_input("Correct value", key="corr_value")
        if st.button("Apply correction", disabled=not value):
            submit_correction(conn, case_id, field, value)
            st.rerun()

    missing = [f for f in findings if f["check_name"] == "required_document"]
    if missing:
        st.markdown("#### Upload missing document")
        extra_pdf = st.file_uploader("Additional PDF", type=["pdf"], key="extra_pdf")
        if extra_pdf and st.button("Add document and reprocess"):
            case_dir = UPLOAD_DIR / case_id
            case_dir.mkdir(parents=True, exist_ok=True)
            path = case_dir / extra_pdf.name
            path.write_bytes(extra_pdf.read())
            case = get_case(conn, case_id)
            claim = Claim(**case["claim_json"])
            existing_paths = [case_dir / d["filename"] for d in get_documents(conn, case_id)]
            create_case_from_upload(conn, claim, existing_paths + [path])
            process_case(conn, case_id)
            st.rerun()


def centre_column(conn, case_id: str, revision: int):
    st.markdown("### Applicable policy")
    case = get_case(conn, case_id)
    claim = Claim(**case["claim_json"])
    st.caption(f"Payer: {claim.payer_id}  |  Service date: {claim.service_date}")

    draft = get_draft(conn, case_id, revision)
    if draft and draft["citations"]:
        from core.db import get_policy_chunks
        chunks = {c["chunk_id"]: c for c in get_policy_chunks(conn, claim.payer_id)}
        for cid in draft["citations"]:
            c = chunks.get(cid)
            if c:
                with st.expander(f"[{cid}] {c['title']}"):
                    st.write(c["text"])
    else:
        st.caption("No policy retrieved yet for this case.")

    st.markdown("### Required documents")
    docs = get_documents(conn, case_id)
    present_types = {d["doc_type"] for d in docs if d["doc_type"]}
    for req in claim.required_documents:
        if req in present_types:
            st.write(f"✅ {req}")
        else:
            st.write(f"❌ {req} — missing")


def right_column(conn, case_id: str, revision: int):
    st.markdown("### Draft response")
    draft = get_draft(conn, case_id, revision)
    if draft is None:
        st.caption("No draft yet — resolve findings above to reach drafting.")
        return

    if LLM_MODE != "live":
        st.info("Template-generated — not LLM output.")

    edited = st.text_area("Draft (editable)", value=draft["body"], height=300, key="draft_body")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Approve", disabled=draft["status"] == "approved"):
            approve_draft(conn, case_id, edited)
            st.rerun()
    with col2:
        if st.button("Save edits"):
            from core.db import update_draft_body
            update_draft_body(conn, case_id, revision, edited, draft["status"])
            st.rerun()

    if draft["status"] == "approved":
        st.success("Approved.")
        st.download_button("Download response.md", export_markdown(conn, case_id),
                            file_name=f"{case_id}_response.md")
        st.download_button("Download evidence.json", export_evidence_json(conn, case_id),
                            file_name=f"{case_id}_evidence.json")


def bottom_panel(conn, case_id: str):
    st.markdown("### Audit trail")
    events = get_events(conn, case_id)
    if events:
        st.dataframe(
            [{"time": e["ts"], "stage": e["stage"], "detail": e["detail"]} for e in events],
            width="stretch",
        )


def main():
    st.title("ClaimBridge")
    st.caption(f"LLM mode: {LLM_MODE}")

    with st.sidebar:
        upload_panel()
        st.divider()
        case_picker()

    case_id = st.session_state.get("case_id")
    if not case_id:
        st.info("Upload a claim JSON and supporting PDFs to begin, or pick an existing case from the sidebar.")
        return

    conn = get_conn()
    case = get_case(conn, case_id)
    if case is None:
        st.warning("Case not found.")
        return

    st.subheader(f"Case {case_id} — {case['status']}")
    revision = case["revision"]

    left, centre, right = st.columns(3)
    with left:
        left_column(conn, case_id, revision)
    with centre:
        centre_column(conn, case_id, revision)
    with right:
        right_column(conn, case_id, revision)

    st.divider()
    bottom_panel(conn, case_id)


if __name__ == "__main__":
    main()
