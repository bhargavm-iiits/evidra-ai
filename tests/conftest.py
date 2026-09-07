import pytest


@pytest.fixture(autouse=True)
def force_template_mode(monkeypatch):
    """Tests must be deterministic and offline regardless of the developer's .env.

    Without this, switching .env to CLAIMBRIDGE_LLM_MODE=live (e.g. to test a real
    provider) silently makes the whole suite depend on network access and API quota.
    """
    monkeypatch.setattr("core.llm.LLM_MODE", "template")
