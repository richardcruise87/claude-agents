"""Unit tests for agents_lib.prompt_loader."""
import pytest
from agents_lib.prompt_loader import load_prompt_template, format_prompt, load_agent_prompt


class TestLoadPromptTemplate:
    def test_loads_existing_file(self, tmp_path):
        (tmp_path / "my_prompt.txt").write_text("Hello {name}!")
        result = load_prompt_template("my_prompt", prompts_dir=tmp_path)
        assert result == "Hello {name}!"

    def test_raises_for_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_prompt_template("nonexistent", prompts_dir=tmp_path)

    def test_returns_full_content(self, tmp_path):
        content = "Line 1\nLine 2\nLine 3"
        (tmp_path / "multi.txt").write_text(content)
        result = load_prompt_template("multi", prompts_dir=tmp_path)
        assert result == content


class TestFormatPrompt:
    def test_basic_substitution(self):
        result = format_prompt("Hello {name}!", name="World")
        assert result == "Hello World!"

    def test_multiple_keys(self):
        result = format_prompt("{a} + {b} = {c}", a="1", b="2", c="3")
        assert result == "1 + 2 = 3"

    def test_unknown_key_left_as_is(self):
        result = format_prompt("{known} and {unknown}", known="yes")
        assert "{unknown}" in result
        assert "yes" in result

    def test_numeric_value(self):
        result = format_prompt("Count: {n}", n=42)
        assert "42" in result


class TestLoadAgentPrompt:
    def test_loads_generic_prompt(self, tmp_path):
        (tmp_path / "my_agent_prompt.txt").write_text("Instructions here.")
        result = load_agent_prompt("my_agent", provider="anthropic", prompts_dir=tmp_path)
        assert "Instructions here." in result

    def test_provider_specific_file_preferred(self, tmp_path):
        (tmp_path / "my_agent_prompt.txt").write_text("Generic prompt.")
        (tmp_path / "my_agent_prompt_openai.txt").write_text("OpenAI prompt.")
        result = load_agent_prompt("my_agent", provider="openai", prompts_dir=tmp_path)
        assert "OpenAI prompt." in result
        assert "Generic prompt." not in result

    def test_falls_back_to_generic_when_no_provider_specific(self, tmp_path):
        (tmp_path / "my_agent_prompt.txt").write_text("Generic prompt.")
        result = load_agent_prompt("my_agent", provider="openai", prompts_dir=tmp_path)
        assert "Generic prompt." in result

    def test_template_file_appended(self, tmp_path):
        (tmp_path / "my_agent_prompt.txt").write_text("Do analysis.")
        (tmp_path / "my_agent_template.txt").write_text("## Output Format\nSection A")
        result = load_agent_prompt("my_agent", provider="anthropic", prompts_dir=tmp_path)
        assert "Do analysis." in result
        assert "Section A" in result

    def test_anthropic_write_instruction_injected(self, tmp_path):
        (tmp_path / "my_agent_prompt.txt").write_text("Do analysis.")
        result = load_agent_prompt(
            "my_agent", provider="anthropic", prompts_dir=tmp_path, save_path="/tmp/report.md"
        )
        assert "Write tool" in result
        assert "/tmp/report.md" in result

    def test_non_anthropic_no_write_instruction(self, tmp_path):
        (tmp_path / "my_agent_prompt.txt").write_text("Do analysis.")
        result = load_agent_prompt(
            "my_agent", provider="openai", prompts_dir=tmp_path, save_path="/tmp/report.md"
        )
        assert "Write tool" not in result

    def test_anthropic_no_write_instruction_when_no_save_path(self, tmp_path):
        (tmp_path / "my_agent_prompt.txt").write_text("Do analysis.")
        result = load_agent_prompt("my_agent", provider="anthropic", prompts_dir=tmp_path)
        assert "Write tool" not in result

    def test_raises_for_missing_prompt_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_agent_prompt("nonexistent_agent", provider="anthropic", prompts_dir=tmp_path)
