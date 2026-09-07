"""Verify the LLM adapter works (live mode) or degrades cleanly (template mode).

Run: python -m scripts.smoke_llm
"""
from pydantic import BaseModel

from core.config import LLM_MODE
from core.llm import structured, LLMUnavailable


class Ping(BaseModel):
    patient_id: str | None
    service_date: str | None


def main():
    print(f"CLAIMBRIDGE_LLM_MODE = {LLM_MODE}")
    try:
        result = structured("Patient ID: SYN-101, date of service 2026-08-15", Ping)
        print("LIVE call succeeded:", result)
    except LLMUnavailable as e:
        print("LLMUnavailable raised as expected in template mode:", e)


if __name__ == "__main__":
    main()
