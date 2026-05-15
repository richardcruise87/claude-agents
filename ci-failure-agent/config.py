"""
Configuration loader for the CI Failure Analysis Agent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents_lib import load_agent_config, expand_config_paths, expand_context_config
from agents_lib.utils import expand_path

CONFIG_DIR = Path(__file__).parent


def load_config():
    """Load and return agent configuration."""
    defaults = {
        "model": "claude-sonnet-4-6",
        "repositories": ["openstack/octavia"],
        "zuul": {
            "base_url": "https://zuul.opendev.org",
            "tenant": "openstack",
            "pipelines": ["check", "gate"],
            "hours_back": 24,
        },
        "gerrit": {
            "base_url": "https://review.opendev.org",
        },
        "forge": {
            "type": "gerrit",
            "base_url": "",
            "token_env": None,
        },
        "output": {
            "reports_directory": "~/octavia_ci_failures",
        },
        "monitoring": {
            "max_changes_per_cycle": 5,
            "analyzed_failures_file": "~/.octavia_ci_failures.json",
        },
        "filters": {
            "skip_non_voting": False,
        },
        "feedback": {
            "post_to_forge": False,
            "enable_voting": False,
        },
    }

    env_overrides = {
        "ZUUL_BASE_URL": ("zuul", "base_url"),
        "ZUUL_TENANT": ("zuul", "tenant"),
        "HOURS_BACK": ("zuul", "hours_back"),
        "GERRIT_BASE_URL": ("gerrit", "base_url"),
        "REPORTS_OUTPUT_DIR": ("output", "reports_directory"),
        "MAX_CHANGES": ("monitoring", "max_changes_per_cycle"),
        "CLAUDE_MODEL": "model",
    }

    config = load_agent_config(CONFIG_DIR, env_overrides, defaults)
    config = expand_config_paths(config, [
        ("output", "reports_directory"),
        ("monitoring", "analyzed_failures_file"),
    ])

    zuul = config.get("zuul", {})
    gerrit = config.get("gerrit", {})
    forge_cfg = config.get("forge", {})
    output = config.get("output", {})
    monitoring = config.get("monitoring", {})
    filters = config.get("filters", {})
    feedback_cfg = config.get("feedback", {})

    # Resolve forge base_url: fall back to gerrit.base_url
    forge_base_url = forge_cfg.get("base_url") or gerrit.get("base_url", "https://review.opendev.org")

    _cfg = {
        "model": config.get("model", "claude-sonnet-4-6"),
        "model_provider": config.get("model_provider", "anthropic"),
        "repositories": config.get("repositories", ["openstack/octavia"]),
        "zuul_base_url": zuul.get("base_url", "https://zuul.opendev.org"),
        "zuul_tenant": zuul.get("tenant", "openstack"),
        "zuul_pipelines": zuul.get("pipelines", ["check", "gate"]),
        "hours_back": int(zuul.get("hours_back", 24)),
        "gerrit_base_url": gerrit.get("base_url", "https://review.opendev.org"),
        "reports_output_dir": expand_path(output.get("reports_directory", "~/octavia_ci_failures")),
        "max_changes_per_cycle": int(monitoring.get("max_changes_per_cycle", 5)),
        "analyzed_failures_file": expand_path(monitoring.get("analyzed_failures_file", "~/.octavia_ci_failures.json")),
        "skip_non_voting": filters.get("skip_non_voting", False),
        # Forge config (for feedback posting)
        "forge": {
            "type": forge_cfg.get("type", "gerrit"),
            "base_url": forge_base_url,
            "token_env": forge_cfg.get("token_env"),
            "username_env": forge_cfg.get("username_env"),
        },
        "feedback_enabled": feedback_cfg.get("post_to_forge", False),
        "feedback_voting": feedback_cfg.get("enable_voting", False),
    }
    return expand_context_config(_cfg)


if __name__ == "__main__":
    config = load_config()
    import json
    print(json.dumps(config, indent=2))
