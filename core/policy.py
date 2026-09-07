import json
from datetime import date

from rank_bm25 import BM25Okapi

from core.config import POLICIES_PATH
from core.models import PolicyChunk


def _load_all_chunks() -> list[PolicyChunk]:
    raw = json.loads(POLICIES_PATH.read_text())
    return [PolicyChunk(**c) for c in raw]


def _applicable(chunk: PolicyChunk, service_date: str) -> bool:
    sd = date.fromisoformat(service_date)
    start = date.fromisoformat(chunk.effective_from)
    if sd < start:
        return False
    if chunk.effective_to is not None:
        end = date.fromisoformat(chunk.effective_to)
        if sd >= end:
            return False
    return True


def _tokenize(text: str) -> list[str]:
    return text.lower().replace("_", " ").split()


def retrieve_policy(payer_id: str, service_date: str, denial_category: str,
                     required_documents: list[str] | None = None, k: int = 3) -> list[PolicyChunk]:
    """Filter by payer + date applicability first, then rank survivors with BM25.

    Returns [] when nothing is applicable — a valid outcome the caller must escalate
    on, never falling back to a non-applicable policy version.
    """
    chunks = [c for c in _load_all_chunks() if c.payer_id == payer_id]
    chunks = [c for c in chunks if _applicable(c, service_date)]
    if not chunks:
        return []

    query_terms = [denial_category] + (required_documents or [])
    query = _tokenize(" ".join(query_terms))

    corpus = [_tokenize(c.title + " " + c.text) for c in chunks]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(query)

    ranked = sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)
    return [c for c, _score in ranked[:k]]
