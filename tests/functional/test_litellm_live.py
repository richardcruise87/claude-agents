"""
Live integration test for the LiteLLM model client.

Requires a running LiteLLM proxy at LITELLM_BASE_URL (default: http://localhost:4000/v1)
and a valid LITELLM_API_KEY.

Run with:
    LITELLM_API_KEY=sk-... tox -e functional -- tests/functional/test_litellm_live.py -v
"""
import os
import json
import pytest

LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000/v1")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not LITELLM_API_KEY,
    reason="LITELLM_API_KEY not set — skipping live LiteLLM tests",
)


def _available_models():
    """Return the list of model IDs from the proxy /v1/models endpoint."""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{LITELLM_BASE_URL.removesuffix('/v1').rstrip('/')}/v1/models",
            headers={"Authorization": f"Bearer {LITELLM_API_KEY}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return [m["id"] for m in data.get("data", [])]
    except Exception:
        return []


def _pick_model():
    """Pick a fast model available on the proxy."""
    available = _available_models()
    for preferred in ("claude-sonnet-4-5", "claude-sonnet-4-6", "gemini-2-5-pro"):
        if preferred in available:
            return preferred
    return available[0] if available else "gemini-2-5-flash"


@pytest.fixture(autouse=True)
def _set_litellm_env(monkeypatch):
    monkeypatch.setenv("LITELLM_BASE_URL", LITELLM_BASE_URL)
    monkeypatch.setenv("LITELLM_API_KEY", LITELLM_API_KEY)


class TestLiteLLMClientLive:
    @pytest.mark.asyncio
    async def test_simple_prompt_returns_text(self):
        """A basic prompt returns a non-empty text response."""
        from agents_lib.model_client import _query_litellm

        model = _pick_model()
        result = await _query_litellm(model, "Reply with exactly: pong", None, None)

        assert isinstance(result.text, str)
        assert len(result.text) > 0

    @pytest.mark.asyncio
    async def test_usage_tokens_populated(self):
        """Token usage counts are returned and are positive integers."""
        from agents_lib.model_client import _query_litellm

        model = _pick_model()
        result = await _query_litellm(model, "Say hi.", None, None)

        assert result.usage.get("input_tokens", 0) > 0
        assert result.usage.get("output_tokens", 0) > 0

    @pytest.mark.asyncio
    async def test_model_field_populated(self):
        """The model field in the result is set to the model name returned by the proxy."""
        from agents_lib.model_client import _query_litellm

        model = _pick_model()
        result = await _query_litellm(model, "Say hi.", None, None)

        assert result.model is not None
        assert len(result.model) > 0

    @pytest.mark.asyncio
    async def test_duration_ms_populated(self):
        """Duration in milliseconds is a positive integer."""
        from agents_lib.model_client import _query_litellm

        model = _pick_model()
        result = await _query_litellm(model, "Say hi.", None, None)

        assert isinstance(result.duration_ms, int)
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_create_model_client_with_litellm_prefix(self):
        """create_model_client with 'litellm/' prefix routes to the LiteLLM backend."""
        from agents_lib.model_client import create_model_client

        model = _pick_model()
        client = create_model_client({"model": f"litellm/{model}"})
        result = await client.query("Reply with exactly: pong")

        assert "pong" in result.text.lower()

    @pytest.mark.asyncio
    async def test_explicit_litellm_provider(self):
        """model_provider='litellm' with a bare model name works correctly."""
        from agents_lib.model_client import create_model_client

        model = _pick_model()
        client = create_model_client({"model": model, "model_provider": "litellm"})
        result = await client.query("Reply with exactly: pong")

        assert "pong" in result.text.lower()

    @pytest.mark.asyncio
    async def test_proxy_models_endpoint_reachable(self):
        """Sanity check: the proxy /v1/models endpoint returns at least one model."""
        available = _available_models()
        assert len(available) > 0, "No models returned from proxy — is the proxy running?"
