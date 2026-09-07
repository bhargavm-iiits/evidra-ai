import json
from pathlib import Path

from core.config import FIXTURES_DIR
from core.extraction import extract_fields
from core.models import Claim
from core.parsing import parse_documents


def load_case(case_name: str) -> tuple[Claim, list]:
    case_dir = FIXTURES_DIR / case_name
    claim = Claim(**json.loads((case_dir / "claim.json").read_text()))
    pdf_paths = sorted(p for p in case_dir.glob("*.pdf"))
    records, _meta = parse_documents(pdf_paths, claim.claim_id)
    facts = extract_fields(records)
    return claim, facts
