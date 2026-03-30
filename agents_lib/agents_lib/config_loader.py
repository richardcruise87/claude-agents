"""
Configuration loading utilities for Claude agents.
"""
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from .utils import expand_path


def load_agent_config(config_dir, env_overrides=None, defaults=None):
    """
    Load agent configuration from file and environment variables.

    Args:
        config_dir: Directory containing config.json / config.sample.json
        env_overrides: Dict mapping env var names to config keys
                      Format: {"ENV_VAR": ("section", "key")} or {"ENV_VAR": "key"}
        defaults: Default configuration dictionary

    Returns:
        Configuration dictionary
    """
    config_dir = Path(config_dir)

    # Try to load config.json, fallback to config.sample.json
    config_file = config_dir / "config.json"
    if not config_file.exists():
        config_file = config_dir / "config.sample.json"

    # Load from file or use defaults
    if config_file.exists():
        with open(config_file, 'r') as f:
            config = json.load(f)
    elif defaults:
        config = defaults.copy()
    else:
        raise FileNotFoundError(
            f"No config.json or config.sample.json found in {config_dir}. "
            "Please create config.json from config.sample.json"
        )

    # Apply environment variable overrides
    if env_overrides:
        for env_var, config_key in env_overrides.items():
            value = os.getenv(env_var)
            if value:
                # Handle nested keys (section, key) or flat keys
                if isinstance(config_key, tuple):
                    section, key = config_key
                    if section not in config:
                        config[section] = {}
                    # Convert to int if it looks like a number
                    if value.isdigit():
                        value = int(value)
                    config[section][key] = value
                else:
                    # Flat key
                    if value.isdigit():
                        value = int(value)
                    config[config_key] = value

    return config


def apply_cutoff_date(config, cutoff_key_path, default_days=30):
    """
    Apply cutoff date logic: default to N days ago if not specified.

    Args:
        config: Configuration dictionary
        cutoff_key_path: Key path to cutoff_date (e.g., "cutoff_date" or ["filters", "cutoff_date"])
        default_days: Number of days ago to use as default

    Returns:
        Modified configuration dictionary
    """
    # Handle nested keys
    if isinstance(cutoff_key_path, str):
        cutoff_key_path = [cutoff_key_path]

    # Navigate to the cutoff date location
    current = config
    for key in cutoff_key_path[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    final_key = cutoff_key_path[-1]

    # Set default if not specified or null
    if not current.get(final_key):
        default_cutoff = datetime.now() - timedelta(days=default_days)
        current[final_key] = default_cutoff.strftime('%Y-%m-%d')

    return config


def expand_config_paths(config, path_keys):
    """
    Expand paths in configuration.

    Args:
        config: Configuration dictionary
        path_keys: List of keys (or key paths) to expand
                  Format: "key" or ("section", "key")

    Returns:
        Modified configuration dictionary
    """
    for key_path in path_keys:
        # Handle nested keys
        if isinstance(key_path, tuple):
            section, key = key_path
            if section in config and key in config[section]:
                config[section][key] = expand_path(config[section][key])
        else:
            # Flat key
            if key_path in config:
                config[key_path] = expand_path(config[key_path])

    return config
