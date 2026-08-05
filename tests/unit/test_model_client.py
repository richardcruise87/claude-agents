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
# Unknown provider
# ---------------------------------------------------------------------------

class TestUnknownProvider:
    @pytest.mark.asyncio
    async def test_raises_value_error(self):
        client = ModelClient(provider="anthropic_unknown", model="whatever")
        client.provider = "unknown_provider"
        with pytest.raises(ValueError, match="Unknown model provider"):
            await client.query("test")
