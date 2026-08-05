"""Unit tests for agents_lib.model_client."""
import pytest
from unittest.mock import MagicMock, patch
from agents_lib.model_client import (
    ModelClient,
    ModelResult,
    create_model_client,
    _parse_model_config,
    _execute_tool,
)


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------

class TestParseModelConfig:
    def test_claude_inferred_as_anthropic(self):
        provider, model = _parse_model_config({"model": "claude-sonnet-4-6"})
        assert provider == "anthropic"
        assert model == "claude-sonnet-4-6"

    def test_gpt_inferred_as_openai(self):
        provider, _ = _parse_model_config({"model": "gpt-4o"})
        assert provider == "openai"

    def test_o1_inferred_as_openai(self):
        provider, _ = _parse_model_config({"model": "o1-preview"})
        assert provider == "openai"

    def test_gemini_inferred_as_google(self):
        provider, _ = _parse_model_config({"model": "gemini-1.5-pro"})
        assert provider == "google"

    def test_explicit_provider_wins(self):
        provider, _ = _parse_model_config({"model": "claude-sonnet-4-6", "model_provider": "openai"})
        assert provider == "openai"

    def test_dict_model_format(self):
        provider, model = _parse_model_config({"model": {"provider": "google", "name": "gemini-1.5-flash"}})
        assert provider == "google"
        assert model == "gemini-1.5-flash"

    def test_default_when_no_model(self):
        provider, model = _parse_model_config({})
        assert provider == "anthropic"
        assert model == "claude-sonnet-4-6"

    def test_unknown_model_defaults_to_anthropic(self):
        provider, _ = _parse_model_config({"model": "some-unknown-model"})
        assert provider == "anthropic"


class TestCreateModelClient:
    def test_returns_model_client(self):
        client = create_model_client({"model": "claude-sonnet-4-6"})
        assert isinstance(client, ModelClient)

    def test_provider_set_correctly(self):
        client = create_model_client({"model": "gpt-4o"})
        assert client.provider == "openai"

    def test_model_set_correctly(self):
        client = create_model_client({"model": "gemini-1.5-pro"})
        assert client.model == "gemini-1.5-pro"


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

class TestExecuteTool:
    def test_bash_success(self, mocker):
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = MagicMock(stdout="hello\n", stderr="", returncode=0)
        result = _execute_tool("bash", {"command": "echo hello"})
        assert "hello" in result

    def test_bash_nonzero_includes_stderr(self, mocker):
        mock_run = mocker.patch("subprocess.run")
        mock_run.return_value = MagicMock(stdout="", stderr="error msg", returncode=1)
        result = _execute_tool("bash", {"command": "false"})
        assert "error msg" in result

    def test_read_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("file content")
        result = _execute_tool("read_file", {"path": str(f)})
        assert result == "file content"

    def test_write_file(self, tmp_path):
        f = tmp_path / "out.txt"
        _execute_tool("write_file", {"path": str(f), "content": "written"})
        assert f.read_text() == "written"

    def test_write_file_creates_parents(self, tmp_path):
        f = tmp_path / "nested" / "dir" / "file.txt"
        _execute_tool("write_file", {"path": str(f), "content": "data"})
        assert f.exists()

    def test_glob(self, tmp_path):
        (tmp_path / "a.txt").write_text("")
        (tmp_path / "b.txt").write_text("")
        result = _execute_tool("glob", {"pattern": "*.txt", "root": str(tmp_path)})
        assert "a.txt" in result
        assert "b.txt" in result

    def test_unknown_tool(self):
        result = _execute_tool("frobnicator", {})
        assert "Unknown" in result or "frobnicator" in result

    def test_web_fetch_mocked(self, mocker):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html>content</html>"
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mocker.patch("urllib.request.urlopen", return_value=mock_resp)
        result = _execute_tool("web_fetch", {"url": "https://example.com"})
        assert "content" in result


# ---------------------------------------------------------------------------
# Anthropic backend
# ---------------------------------------------------------------------------

class TestAnthropicBackend:
    @pytest.mark.asyncio
    async def test_happy_path(self):
        with patch("agents_lib.model_client._query_anthropic") as mock:
            async def impl(model, prompt, tools, on_progress):
                if on_progress:
                    on_progress("Streaming...")
                return ModelResult(text="Final answer", usage={"input_tokens": 100}, model=model)
            mock.side_effect = impl

            client = ModelClient(provider="anthropic", model="claude-sonnet-4-6")
            progress_calls = []
            result = await client.query("test prompt", on_progress=lambda t: progress_calls.append(t))

        assert result.text == "Final answer"
        assert "Streaming..." in progress_calls


# ---------------------------------------------------------------------------
# OpenAI backend — ImportError path
# ---------------------------------------------------------------------------

class TestOpenAIImportError:
    @pytest.mark.asyncio
    async def test_import_error_with_hint(self):
        with patch.dict("sys.modules", {"openai": None}):
            client = ModelClient(provider="openai", model="gpt-4o")
            with pytest.raises(ImportError, match="pip install openai"):
                await client.query("test")


class TestGoogleImportError:
    @pytest.mark.asyncio
    async def test_import_error_with_hint(self):
        with patch.dict("sys.modules", {"google.generativeai": None, "google": None}):
            client = ModelClient(provider="google", model="gemini-1.5-pro")
            with pytest.raises((ImportError, Exception)):
                await client.query("test")


# ---------------------------------------------------------------------------
# LiteLLM backend
# ---------------------------------------------------------------------------

class TestLiteLLMProvider:
    def test_litellm_prefix_inferred(self):
        provider, model = _parse_model_config({"model": "litellm/gpt-4o"})
        assert provider == "litellm"
        # Prefix must be stripped before the model name reaches the proxy
        assert model == "gpt-4o"

    def test_litellm_prefix_stripped_for_non_gpt(self):
        provider, model = _parse_model_config({"model": "litellm/claude-3-opus"})
        assert provider == "litellm"
        assert model == "claude-3-opus"

    def test_explicit_provider_wins_over_litellm_prefix(self):
        # model_provider always takes precedence over name-based inference
        provider, model = _parse_model_config(
            {"model": "litellm/gpt-4o", "model_provider": "openai"}
        )
        assert provider == "openai"
        # prefix should NOT be stripped when provider was set explicitly
        assert model == "litellm/gpt-4o"

    def test_explicit_litellm_provider_bare_model(self):
        # model_provider=litellm with a plain model name (no prefix)
        provider, model = _parse_model_config(
            {"model": "gpt-4o", "model_provider": "litellm"}
        )
        assert provider == "litellm"
        assert model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_import_error_with_hint(self):
        with patch.dict("sys.modules", {"openai": None}):
            client = ModelClient(provider="litellm", model="gpt-4o")
            with pytest.raises(ImportError, match="pip install openai"):
                await client.query("test")

    @pytest.mark.asyncio
    async def test_default_base_url(self, mocker):
        """When LITELLM_BASE_URL and LITELLM_API_KEY are absent, defaults are used."""
        mock_client = MagicMock()

        mock_response = MagicMock()
        mock_response.choices[0].finish_reason = "stop"
        mock_response.choices[0].message.content = "done"
        mock_response.choices[0].message.tool_calls = None
        mock_response.model = "gpt-4o"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        async def fake_create(**kwargs):
            return mock_response

        mock_client.chat.completions.create = fake_create

        captured = {}

        def capturing_constructor(**kwargs):
            captured.update(kwargs)
            return mock_client

        mocker.patch("openai.AsyncOpenAI", capturing_constructor)

        # Ensure the env vars are absent
        env = {k: v for k, v in __import__("os").environ.items()
               if k not in ("LITELLM_BASE_URL", "LITELLM_API_KEY", "LITELLM_TIMEOUT")}
        mocker.patch.dict("os.environ", env, clear=True)

        from agents_lib.model_client import _query_litellm  # noqa: PLC0415
        await _query_litellm("gpt-4o", "hello", None, None)

        assert captured.get("base_url") == "http://localhost:4000/v1"
        assert captured.get("api_key") == "no-key"

    @pytest.mark.asyncio
    async def test_custom_base_url_and_key(self, mocker):
        mock_client = MagicMock()

        mock_response = MagicMock()
        mock_response.choices[0].finish_reason = "stop"
        mock_response.choices[0].message.content = "result"
        mock_response.choices[0].message.tool_calls = None
        mock_response.model = "my-model"
        mock_response.usage.prompt_tokens = 8
        mock_response.usage.completion_tokens = 4

        async def fake_create(**kwargs):
            return mock_response

        mock_client.chat.completions.create = fake_create

        captured = {}

        def capturing_constructor(**kwargs):
            captured.update(kwargs)
            return mock_client

        mocker.patch("openai.AsyncOpenAI", capturing_constructor)

        from agents_lib.model_client import _query_litellm  # noqa: PLC0415

        mocker.patch.dict("os.environ", {
            "LITELLM_BASE_URL": "http://myproxy:8080/v1",
            "LITELLM_API_KEY": "secret-token",
        })

        result = await _query_litellm("my-model", "hello", None, None)

        assert captured["base_url"] == "http://myproxy:8080/v1"
        assert captured["api_key"] == "secret-token"
        assert result.text == "result"
        assert result.usage == {"input_tokens": 8, "output_tokens": 4}

    @pytest.mark.asyncio
    async def test_happy_path_via_model_client(self, mocker):
        """End-to-end: ModelClient with provider=litellm returns correct ModelResult."""
        mock_client = MagicMock()

        mock_response = MagicMock()
        mock_response.choices[0].finish_reason = "stop"
        mock_response.choices[0].message.content = "LiteLLM answer"
        mock_response.choices[0].message.tool_calls = None
        mock_response.model = "gpt-4o"
        mock_response.usage.prompt_tokens = 20
        mock_response.usage.completion_tokens = 10

        async def fake_create(**kwargs):
            return mock_response

        mock_client.chat.completions.create = fake_create
        mocker.patch("openai.AsyncOpenAI", return_value=mock_client)
        mocker.patch.dict("os.environ", {
            "LITELLM_BASE_URL": "http://localhost:4000/v1",
            "LITELLM_API_KEY": "no-key",
        })

        client = ModelClient(provider="litellm", model="gpt-4o")
        result = await client.query("test prompt")

        assert result.text == "LiteLLM answer"
        assert result.usage == {"input_tokens": 20, "output_tokens": 10}
        assert result.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_tool_calls_forwarded(self, mocker):
        """LiteLLM backend executes tool calls and loops until done."""
        mock_client = MagicMock()

        # First response: tool call
        tool_call = MagicMock()
        tool_call.id = "call_1"
        tool_call.function.name = "bash"
        tool_call.function.arguments = '{"command": "echo hi"}'

        first_response = MagicMock()
        first_response.choices[0].finish_reason = "tool_calls"
        first_response.choices[0].message.tool_calls = [tool_call]
        first_response.model = "gpt-4o"
        first_response.usage.prompt_tokens = 15
        first_response.usage.completion_tokens = 5

        # Second response: final answer
        second_response = MagicMock()
        second_response.choices[0].finish_reason = "stop"
        second_response.choices[0].message.content = "Tool result received"
        second_response.choices[0].message.tool_calls = None
        second_response.model = "gpt-4o"
        second_response.usage.prompt_tokens = 25
        second_response.usage.completion_tokens = 8

        call_count = 0

        async def fake_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return first_response if call_count == 1 else second_response

        mock_client.chat.completions.create = fake_create
        mocker.patch("openai.AsyncOpenAI", return_value=mock_client)
        mocker.patch("subprocess.run",
                     return_value=MagicMock(stdout="hi\n", stderr="", returncode=0))
        mocker.patch.dict("os.environ", {
            "LITELLM_BASE_URL": "http://localhost:4000/v1",
            "LITELLM_API_KEY": "no-key",
        })

        client = ModelClient(provider="litellm", model="gpt-4o")
        result = await client.query("run something", tools=["Bash"])

        assert call_count == 2
        assert result.text == "Tool result received"
        assert result.usage == {"input_tokens": 40, "output_tokens": 13}


# ---------------------------------------------------------------------------
# Unknown provider
# ---------------------------------------------------------------------------

class TestUnknownProvider:
    @pytest.mark.asyncio
    async def test_raises_value_error(self):
        client = ModelClient(provider="anthropic_unknown", model="whatever")
        client.provider = "unknown_provider"
        with pytest.raises(ValueError, match="Unknown model provider"):
            await client.query("test")
