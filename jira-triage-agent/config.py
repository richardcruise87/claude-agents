"""Configuration loader for the JIRA Triage Agent."""

import os
from pathlib import Path
from agents_lib import apply_cutoff_date
from agents_lib import expand_config_paths
from agents_lib import load_agent_config


def load_config() -> dict:
    """Load config from config.json (or config.sample.json fallback) plus env vars."""
    config_dir = Path(__file__).parent.absolute()

    defaults = {
        "model": "claude-sonnet-4-6",
        "model_provider": "anthropic",
        "jira": {
            "base_url": "",
            "email": "",
            "token_env": "JIRA_API_TOKEN",
            "jql": "project = MYPROJ AND status != Done ORDER BY updated DESC",
        },
        "output": {
            "triages_dir": "~/jira_triages",
            "plans_dir": "~/jira_plans",
        },
        "processing": {
            "max_issues_per_run": 5,
            "triage_tracking_file": "~/.jira_triages.json",
            "cutoff_date": None,
        },
        "issue_types": {
            "bugs": ["Bug", "Defect"],
            "planning": ["Story", "Task", "Epic"],
        },
        "devstack_path": "/opt/stack",
        "search_repos": [],
    }

    env_overrides = {
        "JIRA_BASE_URL": ("jira", "base_url"),
        "JIRA_EMAIL": ("jira", "email"),
        "JIRA_JQL": ("jira", "jql"),
        "MAX_ISSUES": ("processing", "max_issues_per_run"),
        "CUTOFF_DATE": ("processing", "cutoff_date"),
        "TRIAGES_DIR": ("output", "triages_dir"),
        "PLANS_DIR": ("output", "plans_dir"),
        "DEVSTACK_PATH": "devstack_path",
        "CLAUDE_MODEL": "model",
    }

    config = load_agent_config(config_dir, env_overrides, defaults)
    config = apply_cutoff_date(config, ["processing", "cutoff_date"], default_days=30)
    config = expand_config_paths(config, [
        ("output", "triages_dir"),
        ("output", "plans_dir"),
        ("processing", "triage_tracking_file"),
        "devstack_path",
    ])

    # Flatten frequently accessed keys for convenience
    config["triages_dir"] = config["output"]["triages_dir"]
    config["plans_dir"] = config["output"]["plans_dir"]
    config["triage_tracking_file"] = config["processing"]["triage_tracking_file"]
    config["max_issues_per_run"] = config["processing"].get("max_issues_per_run", 5)
    config["cutoff_date"] = config["processing"]["cutoff_date"]

    return config


def get_config_info() -> dict:
    script_dir = Path(__file__).parent.absolute()
    config_file = script_dir / "config.json"
    source = (
        str(config_file)
        if config_file.exists()
        else str(script_dir / "config.sample.json") + " (using sample)"
    )
    env_keys = ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "JIRA_JQL",
                "MAX_ISSUES", "CUTOFF_DATE"]
    active = {k: os.getenv(k) for k in env_keys if os.getenv(k)}
    return {"config_file": source, "env_overrides": active}
