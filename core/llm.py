import os
from typing import TypeVar, Type

from pydantic import BaseModel

from core.config import LLM_MODE

# PROVIDER selects which live backend structured() calls when LLM_MODE == "live".
# Every other module only ever calls structured() — this is the only file that
# knows which vendor SDK is in use.
PROVIDER = os.getenv("CLAIMBRIDGE_LLM_PROVIDER", "anthropic")

ANTHROPIC_MODEL = "claude-opus-5"
GEMINI_MODEL = os.getenv("CLAIMBRIDGE_GEMINI_MODEL", "gemini-2.5-flash")

T = TypeVar("T", bound=BaseModel)

DEFAULT_SYSTEM = (
    "You extract facts from healthcare claim documents. "
    "Use null for anything not present. Never invent values."
)


class LLMUnavailable(Exception):
    """Raised so callers can degrade to a deterministic template path."""


def _structured_anthropic(prompt: str, schema: Type[T], system: str) -> T:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.parse(
        model=ANTHROPIC_MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=schema,
    )
    return resp.parsed_output


def _structured_gemini(prompt: str, schema: Type[T], system: str) -> T:
    from google import genai

    client = genai.Client()  # reads GEMINI_API_KEY from the environment
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"{system}\n\n{prompt}",
        config={
            "response_mime_type": "application/json",
            "response_schema": schema,
        },
    )
    parsed = getattr(resp, "parsed", None)
    if parsed is not None:
        return parsed
    # Fallback: some SDK versions only populate .text, not .parsed.
    return schema.model_validate_json(resp.text)


def structured(prompt: str, schema: Type[T], system: str = "") -> T:
    """Return a validated instance of `schema`. Never returns raw text.

    In template mode (no API key needed), always raises LLMUnavailable so callers
    fall back to their deterministic path. In live mode, PROVIDER picks the backend.
    """
    if LLM_MODE != "live":
        raise LLMUnavailable("template mode")

    system = system or DEFAULT_SYSTEM

    if PROVIDER == "gemini":
        return _structured_gemini(prompt, schema, system)
    elif PROVIDER == "anthropic":
        return _structured_anthropic(prompt, schema, system)
    else:
        raise ValueError(f"unknown CLAIMBRIDGE_LLM_PROVIDER: {PROVIDER!r}")
