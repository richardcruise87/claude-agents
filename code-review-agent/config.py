#!/usr/bin/env python3
"""
Configuration loader for Octavia Review Agent.

Loads configuration from:
1. Environment variables (highest priority)
2. config.json (if exists)
3. config.sample.json (fallback)
4. Defaults (lowest priority)
"""
import os
from pathlib import Path
from agents_lib import load_agent_config, apply_cutoff_date, expand_config_paths, expand_context_config


def load_config():
    """
    Load configuration from file and environment variables.

    Returns a dictionary with configuration settings.
    """
    config_dir = Path(__file__).parent.absolute()

    # Default configuration
    defaults = {
        "repositories": ["openstack/octavia"],
        "devstack": {"path": "/opt/stack"},
        "output": {"reviews_directory": "~/octavia_reviews"},
        "gerrit": {"base_url": "https://review.opendev.org"},
        "forge": {
            "type": "gerrit",
            "base_url": "",     # empty → falls back to gerrit.base_url
            "token_env": None,
            "repo_base_path": "/opt/stack",
        },
        "feedback": {
            "post_to_forge": False,
            "enable_voting": True,
            "vote_label": "Code-Review",
            "approval_score": 1,
            "major_issues_score": -1,
            "minor_only_score": 0,
        },
        "testing": {
            "run_unit_tests": True,
            "run_functional_tests": True,
            "run_pep8": True,
            "unit_test_command": "tox -e py3",
            "functional_test_command": "tox -e functional",
            "pep8_command": "tox -e pep8",
            "test_timeout_seconds": 1800
        },
        "monitoring": {
            "max_reviews_per_cycle": 3,
            "reviewed_changes_file": "~/.octavia_reviewed_changes.json"
        },
        "filters": {},
        "model": "claude-sonnet-4-6",
    }

    # Environment variable overrides
    env_overrides = {
        "DEVSTACK_PATH": ("devstack", "path"),
        "REVIEWS_OUTPUT_DIR": ("output", "reviews_directory"),
        "GERRIT_URL": ("gerrit", "base_url"),
        "FORGE_TYPE": ("forge", "type"),
        "FORGE_BASE_URL": ("forge", "base_url"),
        "FORGE_REPO_BASE_PATH": ("forge", "repo_base_path"),
        "MAX_REVIEWS": ("monitoring", "max_reviews_per_cycle"),
        "REVIEWED_CHANGES_FILE": ("monitoring", "reviewed_changes_file"),
        "CUTOFF_DATE": ("filters", "cutoff_date"),
        "CLAUDE_MODEL": "model",
    }

    # Load config using shared library
    config = load_agent_config(config_dir, env_overrides, defaults)

    # Apply cutoff date logic (default to 30 days ago)
    config = apply_cutoff_date(config, ["filters", "cutoff_date"], default_days=30)

    # Expand paths
    path_keys = [
        ("devstack", "path"),
        ("output", "reviews_directory"),
        ("monitoring", "reviewed_changes_file"),
        ("forge", "repo_base_path"),
    ]
    config = expand_config_paths(config, path_keys)

    # Resolve forge base_url: fall back to gerrit.base_url for backward compat
    forge_cfg = config.get("forge", {})
    if not forge_cfg.get("base_url"):
        forge_cfg["base_url"] = config.get("gerrit", {}).get("base_url", "https://review.opendev.org")
        config["forge"] = forge_cfg

    # Create a flat CONFIG dict for backward compatibility
    flat_config = {
        "octavia_repos": config.get("repositories", []),
        "devstack_path": config["devstack"]["path"],
        "reviews_output_dir": config["output"]["reviews_directory"],
        # Gerrit key kept for backward compat (prompts still use it)
        "gerrit_base_url": config["gerrit"]["base_url"],
        # Forge config (new)
        "forge": config.get("forge", {}),
        "forge_type": forge_cfg.get("type", "gerrit"),
        "forge_base_url": forge_cfg.get("base_url", ""),
        "forge_token_env": forge_cfg.get("token_env"),
        "repo_base_path": forge_cfg.get("repo_base_path", "/opt/stack"),
        "reviewed_changes_file": config["monitoring"]["reviewed_changes_file"],
        "max_reviews_per_cycle": config["monitoring"].get("max_reviews_per_cycle", 3),
        "testing": config.get("testing", {}),
        "cutoff_date": config["filters"]["cutoff_date"],
        "filters": config.get("filters", {}),
        "model": config.get("model", "claude-sonnet-4-6"),
        "model_provider": config.get("model_provider", "anthropic"),
        "notifications": config.get("notifications", {}),
        # Feedback / forge posting
        "feedback_enabled": config.get("feedback", {}).get("post_to_forge", False),
        "feedback_voting": config.get("feedback", {}).get("enable_voting", True),
        "feedback_vote_label": config.get("feedback", {}).get("vote_label", "Code-Review"),
        "feedback_approval_score": config.get("feedback", {}).get("approval_score", 1),
        "feedback_major_score": config.get("feedback", {}).get("major_issues_score", -1),
        "feedback_minor_score": config.get("feedback", {}).get("minor_only_score", 0),
    }

    flat_config = expand_context_config(flat_config)
    return flat_config


def get_config_info():
    """Return information about configuration sources."""
    script_dir = Path(__file__).parent.absolute()
    config_file = script_dir / "config.json"

    if config_file.exists():
        source = str(config_file)
    elif (script_dir / "config.sample.json").exists():
        source = str(script_dir / "config.sample.json") + " (using sample)"
    else:
        source = "built-in defaults"

    env_vars = {
        "DEVSTACK_PATH": os.getenv("DEVSTACK_PATH"),
        "REVIEWS_OUTPUT_DIR": os.getenv("REVIEWS_OUTPUT_DIR"),
        "GERRIT_URL": os.getenv("GERRIT_URL"),
        "CUTOFF_DATE": os.getenv("CUTOFF_DATE"),
    }

    active_overrides = {k: v for k, v in env_vars.items() if v}

    return {
        "config_file": source,
        "env_overrides": active_overrides
    }


if __name__ == "__main__":
    # Test configuration loading
    print("Configuration Test")
    print("=" * 60)

    info = get_config_info()
    print(f"Config file: {info['config_file']}")

    if info['env_overrides']:
        print("\nEnvironment overrides:")
        for key, value in info['env_overrides'].items():
            print(f"  {key} = {value}")
    else:
        print("\nNo environment overrides active")

    print("\nLoaded configuration:")
    config = load_config()
    for key, value in config.items():
        if isinstance(value, dict):
            print(f"  {key}:")
            for k, v in value.items():
                print(f"    {k} = {v}")
        elif isinstance(value, list):
            print(f"  {key}: {len(value)} items")
            for item in value[:3]:  # Show first 3
                print(f"    - {item}")
        else:
            print(f"  {key} = {value}")
