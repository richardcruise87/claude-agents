"""Unit tests for agents_lib.config_loader."""
import json
import pytest
from datetime import datetime, timedelta
from agents_lib.config_loader import load_agent_config, apply_cutoff_date, expand_config_paths


class TestLoadAgentConfig:
    def test_loads_config_json(self, tmp_path):
        cfg = {"model": "claude-sonnet-4-6", "max_items": 5}
        (tmp_path / "config.json").write_text(json.dumps(cfg))
        result = load_agent_config(tmp_path)
        assert result["model"] == "claude-sonnet-4-6"
        assert result["max_items"] == 5

    def test_fallback_to_sample(self, tmp_path):
        cfg = {"model": "claude-opus-4-7"}
        (tmp_path / "config.sample.json").write_text(json.dumps(cfg))
        result = load_agent_config(tmp_path)
        assert result["model"] == "claude-opus-4-7"

    def test_config_json_preferred_over_sample(self, tmp_path):
        (tmp_path / "config.json").write_text(json.dumps({"model": "from-config"}))
        (tmp_path / "config.sample.json").write_text(json.dumps({"model": "from-sample"}))
        result = load_agent_config(tmp_path)
        assert result["model"] == "from-config"

    def test_raises_when_no_config(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_agent_config(tmp_path)

    def test_uses_defaults_when_no_file(self, tmp_path):
        defaults = {"model": "default-model", "count": 3}
        result = load_agent_config(tmp_path, defaults=defaults)
        assert result["model"] == "default-model"

    def test_env_override_flat_key(self, tmp_path, monkeypatch):
        (tmp_path / "config.json").write_text(json.dumps({"cutoff_date": "2026-01-01"}))
        monkeypatch.setenv("CUTOFF_DATE", "2026-06-01")
        result = load_agent_config(tmp_path, env_overrides={"CUTOFF_DATE": "cutoff_date"})
        assert result["cutoff_date"] == "2026-06-01"

    def test_env_override_nested_key(self, tmp_path, monkeypatch):
        cfg = {"monitoring": {"max_items": 3}}
        (tmp_path / "config.json").write_text(json.dumps(cfg))
        monkeypatch.setenv("MAX_ITEMS", "10")
        result = load_agent_config(
            tmp_path, env_overrides={"MAX_ITEMS": ("monitoring", "max_items")}
        )
        assert result["monitoring"]["max_items"] == 10

    def test_env_override_int_conversion(self, tmp_path, monkeypatch):
        (tmp_path / "config.json").write_text(json.dumps({"max_bugs": 5}))
        monkeypatch.setenv("MAX_BUGS", "15")
        result = load_agent_config(tmp_path, env_overrides={"MAX_BUGS": "max_bugs"})
        assert result["max_bugs"] == 15
        assert isinstance(result["max_bugs"], int)

    def test_env_override_ignored_when_unset(self, tmp_path, monkeypatch):
        (tmp_path / "config.json").write_text(json.dumps({"model": "original"}))
        monkeypatch.delenv("MY_MODEL", raising=False)
        result = load_agent_config(tmp_path, env_overrides={"MY_MODEL": "model"})
        assert result["model"] == "original"


class TestApplyCutoffDate:
    def test_explicit_date_kept(self):
        config = {"cutoff_date": "2026-01-15"}
        result = apply_cutoff_date(config, "cutoff_date")
        assert result["cutoff_date"] == "2026-01-15"

    def test_null_replaced_with_default(self):
        config = {"cutoff_date": None}
        result = apply_cutoff_date(config, "cutoff_date", default_days=30)
        expected = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        assert result["cutoff_date"] == expected

    def test_missing_key_gets_default(self):
        config = {}
        result = apply_cutoff_date(config, "cutoff_date", default_days=7)
        expected = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        assert result["cutoff_date"] == expected

    def test_nested_key(self):
        config = {"filters": {"cutoff_date": None}}
        result = apply_cutoff_date(config, ["filters", "cutoff_date"], default_days=14)
        expected = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        assert result["filters"]["cutoff_date"] == expected

    def test_default_days_parameter(self):
        config = {"cutoff_date": None}
        result = apply_cutoff_date(config, "cutoff_date", default_days=90)
        expected = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        assert result["cutoff_date"] == expected


class TestExpandConfigPaths:
    def test_expands_tilde(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/testuser")
        config = {"output_dir": "~/results"}
        result = expand_config_paths(config, ["output_dir"])
        assert result["output_dir"].startswith("/home/testuser")

    def test_nested_key_tuple(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/testuser")
        config = {"devstack": {"path": "~/devstack"}}
        result = expand_config_paths(config, [("devstack", "path")])
        assert result["devstack"]["path"].startswith("/home/testuser")

    def test_missing_key_no_crash(self):
        config = {"other_key": "value"}
        result = expand_config_paths(config, ["nonexistent"])
        assert result["other_key"] == "value"

    def test_multiple_keys(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/u")
        config = {"dir_a": "~/a", "dir_b": "~/b"}
        result = expand_config_paths(config, ["dir_a", "dir_b"])
        assert "/home/u/a" in result["dir_a"]
        assert "/home/u/b" in result["dir_b"]
