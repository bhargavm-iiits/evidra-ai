"""Run one demo case end to end from the terminal.

Usage: python -m scripts.run_case case_01_clean
"""
import json
import sys
from pathlib import Path

from core.config import FIXTURES_DIR
from core.db import connect, get_draft, get_findings, get_events
from core.models import Claim
from core.pipeline import create_case_from_upload, process_case


def run(case_name: str):
    case_dir = FIXTURES_DIR / case_name
    claim = Claim(**json.loads((case_dir / "claim.json").read_text()))
    pdf_paths = sorted(p for p in case_dir.glob("*.pdf"))

    conn = connect()
    case_id = create_case_from_upload(conn, claim, pdf_paths)
    status = process_case(conn, case_id)

    print(f"\n=== {case_name} -> {case_id} ===")
    print(f"final status: {status}")

    findings = get_findings(conn, case_id, 1)
    if findings:
        print("findings:")
        for f in findings:
            print(f"  [{f['severity']}] {f['check_name']}: {f['message']}")
    else:
        print("findings: none")

    draft = get_draft(conn, case_id, 1)
    if draft:
        print(f"draft citations: {draft['citations']}")
        print("draft body:")
        print(draft["body"])
    else:
        print("draft: none (blocked before drafting)")

    print("events:")
    for e in get_events(conn, case_id):
        print(f"  {e['ts']} [{e['stage']}] {e['detail']}")

    conn.close()
    return status


if __name__ == "__main__":
    case_name = sys.argv[1] if len(sys.argv) > 1 else "case_01_clean"
    run(case_name)
