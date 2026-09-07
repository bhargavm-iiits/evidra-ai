import hashlib
from pathlib import Path

import pymupdf

from core.models import PageRecord


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def parse_documents(paths: list[Path], case_id: str) -> tuple[list[PageRecord], dict[str, dict]]:
    """Extract text per page from a list of PDF paths.

    Returns (page_records, document_meta) where document_meta maps document_id to
    {filename, sha256, page_count}. document_id is assigned "<case_id>-DOC-01",
    "<case_id>-DOC-02", ... in upload order — prefixed with case_id because pages
    and documents are stored in tables shared across all cases, and a bare "DOC-01"
    would otherwise collide between two different cases' first uploaded document.
    """
    records: list[PageRecord] = []
    document_meta: dict[str, dict] = {}

    for i, path in enumerate(paths, start=1):
        document_id = f"{case_id}-DOC-{i:02d}"
        doc = pymupdf.open(str(path))
        try:
            for page_index in range(doc.page_count):
                text = doc[page_index].get_text()
                unsupported = len(text.strip()) == 0
                records.append(PageRecord(
                    document_id=document_id,
                    page=page_index + 1,
                    text=text,
                    unsupported=unsupported,
                ))
            document_meta[document_id] = {
                "filename": path.name,
                "sha256": _sha256(path),
                "page_count": doc.page_count,
            }
        finally:
            doc.close()

    return records, document_meta
