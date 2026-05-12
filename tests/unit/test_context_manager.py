"""Unit tests for agents_lib.context_manager."""
from agents_lib.context_manager import (
    expand_context_config,
    load_context_section,
    save_learning,
)


# ---------------------------------------------------------------------------
# expand_context_config
# ---------------------------------------------------------------------------

class TestExpandContextConfig:
    def test_expands_tilde_in_rules_file(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/testuser")
        config = {"context": {"rules_file": "~/.claude-agents/rules.md"}}
        result = expand_context_config(config)
        assert result["context"]["rules_file"] == "/home/testuser/.claude-agents/rules.md"

    def test_expands_extra_files_list(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/testuser")
        config = {"context": {"extra_files": ["~/file1.md", "~/file2.md"]}}
        result = expand_context_config(config)
        assert result["context"]["extra_files"] == [
            "/home/testuser/file1.md",
            "/home/testuser/file2.md",
        ]

    def test_no_context_section_is_safe(self):
        config = {"model": "claude-sonnet-4-6"}
        result = expand_context_config(config)
        ctx = result["context"]
        # All keys guaranteed present — no KeyError even without a context section
        assert ctx["agent_context_file"] == ""
        assert ctx["rules_file"] == ""
        assert ctx["global_context_file"] == ""
        assert ctx["extra_files"] == []
        assert ctx["save_learnings"] is True

    def test_empty_strings_left_empty(self):
        config = {"context": {"rules_file": "", "agent_context_file": ""}}
        result = expand_context_config(config)
        assert result["context"]["rules_file"] == ""
        assert result["context"]["agent_context_file"] == ""


# ---------------------------------------------------------------------------
# load_context_section
# ---------------------------------------------------------------------------

class TestLoadContextSection:
    def test_returns_empty_when_no_files_exist(self, tmp_path):
        config = {
            "context": {
                "rules_file": str(tmp_path / "nope_rules.md"),
                "global_context_file": str(tmp_path / "nope_global.md"),
                "agent_context_file": str(tmp_path / "nope_agent.md"),
                "extra_files": [],
                "max_chars_per_file": 2000,
            }
        }
        assert load_context_section(config) == ""

    def test_includes_rules_file(self, tmp_path):
        rules = tmp_path / "rules.md"
        rules.write_text("Always use the CLI, not the API directly.")
        config = {
            "context": {
                "rules_file": str(rules),
                "global_context_file": str(tmp_path / "nope.md"),
                "agent_context_file": "",
                "extra_files": [],
                "max_chars_per_file": 2000,
            }
        }
        result = load_context_section(config)
        assert "Project Rules" in result
        assert "Always use the CLI" in result

    def test_includes_global_and_agent_sections(self, tmp_path):
        (tmp_path / "global.md").write_text("Global learning.")
        (tmp_path / "agent.md").write_text("Agent-specific learning.")
        config = {
            "context": {
                "rules_file": str(tmp_path / "nope.md"),
                "global_context_file": str(tmp_path / "global.md"),
                "agent_context_file": str(tmp_path / "agent.md"),
                "extra_files": [],
                "max_chars_per_file": 2000,
            }
        }
        result = load_context_section(config)
        assert "Global Context" in result
        assert "Global learning." in result
        assert "Agent Context" in result
        assert "Agent-specific learning." in result

    def test_caps_at_max_chars_per_file(self, tmp_path):
        rules = tmp_path / "rules.md"
        rules.write_text("A" * 5000)
        config = {
            "context": {
                "rules_file": str(rules),
                "global_context_file": "",
                "agent_context_file": "",
                "extra_files": [],
                "max_chars_per_file": 100,
            }
        }
        result = load_context_section(config)
        # The content itself is capped; header overhead is separate
        assert "A" * 100 in result
        assert "A" * 101 not in result

    def test_includes_extra_files(self, tmp_path):
        extra = tmp_path / "extra.md"
        extra.write_text("Extra context here.")
        config = {
            "context": {
                "rules_file": "",
                "global_context_file": "",
                "agent_context_file": "",
                "extra_files": [str(extra)],
                "max_chars_per_file": 2000,
            }
        }
        result = load_context_section(config)
        assert "Extra context here." in result
        assert "extra.md" in result

    def test_agent_name_derives_default_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        agent_file = tmp_path / ".claude-agents" / "my_agent_context.md"
        agent_file.parent.mkdir(parents=True)
        agent_file.write_text("Agent default content.")
        config = {"context": {"extra_files": [], "max_chars_per_file": 2000}}
        result = load_context_section(config, agent_name="my_agent")
        assert "Agent default content." in result


# ---------------------------------------------------------------------------
# save_learning
# ---------------------------------------------------------------------------

class TestSaveLearning:
    def test_creates_file_and_appends(self, tmp_path):
        ctx_file = str(tmp_path / "agent_context.md")
        save_learning(ctx_file, "Sourcing ~/.bashrc is required.", "Bug Reproduction Agent")
        content = open(ctx_file).read()
        assert "Bug Reproduction Agent" in content
        assert "Sourcing ~/.bashrc is required." in content

    def test_creates_parent_directories(self, tmp_path):
        ctx_file = str(tmp_path / "new" / "dir" / "context.md")
        save_learning(ctx_file, "Test learning.", "Test Agent")
        assert open(ctx_file).read().strip() != ""

    def test_appends_to_existing_file(self, tmp_path):
        ctx_file = tmp_path / "context.md"
        ctx_file.write_text("## Existing content\n\nOld learning.\n")
        save_learning(str(ctx_file), "New learning.", "Test Agent")
        content = ctx_file.read_text()
        assert "Old learning." in content
        assert "New learning." in content

    def test_includes_date_header(self, tmp_path):
        ctx_file = str(tmp_path / "context.md")
        save_learning(ctx_file, "A learning.", "Some Agent")
        content = open(ctx_file).read()
        import re
        assert re.search(r"### \d{4}-\d{2}-\d{2}", content)

    def test_noop_when_empty_learning(self, tmp_path):
        ctx_file = str(tmp_path / "context.md")
        save_learning(ctx_file, "", "Test Agent")
        assert not (tmp_path / "context.md").exists()

    def test_noop_when_empty_path(self, tmp_path):
        # Should not raise
        save_learning("", "A learning.", "Test Agent")
