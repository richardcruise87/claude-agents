#!/usr/bin/env python3
"""
Configuration loader for Octavia Review Agent.

Loads configuration from:
1. Environment variables (highest priority)
2. config.json (if exists)
3. config.sample.json (fallback)
4. Defaults (lowest priority)
"""
import json
import os
from pathlib import Path


def expand_path(path_str):
    """Expand ~ and environment variables in paths."""
    if not path_str:
        return path_str
    expanded = os.path.expanduser(path_str)
    expanded = os.path.expandvars(expanded)
    return expanded


def load_config():
    """
    Load configuration from file and environment variables.

    Returns a dictionary with configuration settings.
    """
    # Get the directory where this script is located
    script_dir = Path(__file__).parent.absolute()

    # Try to load from config.json, fallback to config.sample.json
    config_file = script_dir / "config.json"
    if not config_file.exists():
        config_file = script_dir / "config.sample.json"

    # Load from file
    if config_file.exists():
        with open(config_file, 'r') as f:
            config = json.load(f)
    else:
        # Fallback defaults if no config file exists
        config = {
            "repositories": ["openstack/octavia"],
            "devstack": {"path": "/opt/stack"},
            "output": {"reviews_directory": "~/octavia_reviews"},
            "gerrit": {"base_url": "https://review.opendev.org"},
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
            }
        }

    # Environment variable overrides
    env_overrides = {
        "DEVSTACK_PATH": ("devstack", "path"),
        "REVIEWS_OUTPUT_DIR": ("output", "reviews_directory"),
        "GERRIT_URL": ("gerrit", "base_url"),
        "MAX_REVIEWS": ("monitoring", "max_reviews_per_cycle"),
        "REVIEWED_CHANGES_FILE": ("monitoring", "reviewed_changes_file"),
    }

    for env_var, (section, key) in env_overrides.items():
        value = os.getenv(env_var)
        if value:
            if section not in config:
                config[section] = {}
            # Convert to int if it looks like a number
            if value.isdigit():
                value = int(value)
            config[section][key] = value

    # Expand paths
    config["devstack"]["path"] = expand_path(config["devstack"]["path"])
    config["output"]["reviews_directory"] = expand_path(
        config["output"]["reviews_directory"]
    )
    config["monitoring"]["reviewed_changes_file"] = expand_path(
        config["monitoring"].get("reviewed_changes_file", "~/.octavia_reviewed_changes.json")
    )

    # Create a flat CONFIG dict for backward compatibility
    flat_config = {
        "octavia_repos": config.get("repositories", []),
        "devstack_path": config["devstack"]["path"],
        "reviews_output_dir": config["output"]["reviews_directory"],
        "gerrit_base_url": config["gerrit"]["base_url"],
        "reviewed_changes_file": config["monitoring"]["reviewed_changes_file"],
        "max_reviews_per_cycle": config["monitoring"].get("max_reviews_per_cycle", 3),
        "testing": config.get("testing", {}),
    }

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
