"""
Functional tests for end-to-end configuration loading.

Writes real config files, loads them through load_agent_config, and
verifies the full pipeline (file → env overrides → cutoff date → path expansion).
"""
import json
from datetime import datetime, timedelta
from agents_lib import load_agent_config, apply_cutoff_date, expand_config_paths


class TestConfigLoadingRoundTrip:
    def test_full_pipeline(self, tmp_path, monkeypatch):
        """Full config loading pipeline: file + env override + cutoff + paths."""
        cfg = {
            "model": "claude-sonnet-4-6",
            "output_dir": "~/output",
            "tracking_file": "~/tracking.json",
            "cutoff_date": None,
            "max_items": 5,
        }
        (tmp_path / "config.json").write_text(json.dumps(cfg))
        monkeypatch.setenv("MAX_ITEMS", "10")
        monkeypatch.setenv("HOME", str(tmp_path))

        result = load_agent_config(
            tmp_path,
            env_overrides={"MAX_ITEMS": "max_items"},
        )
        result = apply_cutoff_date(result, "cutoff_date", default_days=30)
        result = expand_config_paths(result, ["output_dir", "tracking_file"])

        assert result["max_items"] == 10
        assert result["cutoff_date"] == (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        assert result["output_dir"].startswith(str(tmp_path))
        assert not result["output_dir"].startswith("~")

    def test_sample_fallback_works(self, tmp_path):
        """Ensure config.sample.json is loaded when config.json is absent."""
        cfg = {"model": "claude-haiku-4-5"}
        (tmp_path / "config.sample.json").write_text(json.dumps(cfg))
        result = load_agent_config(tmp_path)
        assert result["model"] == "claude-haiku-4-5"

    def test_nested_env_override_creates_section(self, tmp_path, monkeypatch):
        """Env override creates nested section if it doesn't exist."""
        (tmp_path / "config.json").write_text("{}")
        monkeypatch.setenv("DEVSTACK_PATH", "/opt/stack")
        result = load_agent_config(
            tmp_path,
            env_overrides={"DEVSTACK_PATH": ("devstack", "path")},
        )
        assert result["devstack"]["path"] == "/opt/stack"

    def test_explicit_cutoff_date_preserved(self, tmp_path):
        """Explicit cutoff date in config is not overridden."""
        cfg = {"cutoff_date": "2026-01-01"}
        (tmp_path / "config.json").write_text(json.dumps(cfg))
        result = load_agent_config(tmp_path)
        result = apply_cutoff_date(result, "cutoff_date", default_days=30)
        assert result["cutoff_date"] == "2026-01-01"
