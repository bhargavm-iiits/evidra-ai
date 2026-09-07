import json
from datetime import datetime, timezone

from core.db import get_case, get_draft, get_effective_facts, get_findings, get_policy_chunks


def export_markdown(conn, case_id: str) -> str:
    case = get_case(conn, case_id)
    revision = case["revision"]
    draft = get_draft(conn, case_id, revision)
    if draft is None:
        raise ValueError(f"no draft to export for case {case_id}")

    lines = [draft["body"], "", "---", "## Citation appendix", ""]
    all_chunks = {c["chunk_id"]: c for c in get_policy_chunks(conn)}
    for chunk_id in draft["citations"]:
        chunk = all_chunks.get(chunk_id)
        if chunk:
            lines.append(f"- **[{chunk_id}]** {chunk['title']} (version {chunk['version']})")
    lines += ["", f"*Status: {draft['status']} — exported {datetime.now(timezone.utc).isoformat()}*"]
    return "\n".join(lines)


def export_evidence(conn, case_id: str) -> dict:
    case = get_case(conn, case_id)
    revision = case["revision"]
    facts = get_effective_facts(conn, case_id, revision)
    findings = get_findings(conn, case_id, revision)
    draft = get_draft(conn, case_id, revision)

    return {
        "case_id": case_id,
        "revision": revision,
        "claim": case["claim_json"],
        "status": case["status"],
        "facts": facts,
        "findings": findings,
        "draft_citations": draft["citations"] if draft else [],
        "draft_status": draft["status"] if draft else None,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


def export_evidence_json(conn, case_id: str) -> str:
    return json.dumps(export_evidence(conn, case_id), indent=2)
