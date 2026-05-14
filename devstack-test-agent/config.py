"""
Configuration loader for DevStack test agent.

Loads configuration from config.json with environment variable overrides.
"""
from pathlib import Path
from agents_lib import load_agent_config, expand_config_paths, expand_context_config


def load_config():
    """
    Load configuration from config.json or config.sample.json.

    Returns:
        Configuration dictionary
    """
    config_dir = Path(__file__).parent

    # Define environment variable overrides
    env_overrides = {
        "REVIEWS_DIR": "reviews_directory",
        "DEVSTACK_PATH": ("devstack", "path"),
        "OPENRC_FILE": ("devstack", "openrc_file"),
        "LOCK_TIMEOUT": ("devstack", "lock_timeout"),
        "TEST_TIMEOUT": ("testing", "test_timeout"),
        "CLEANUP_ON_FAILURE": ("testing", "cleanup_on_failure"),
    }

    # Load config using shared library
    config = load_agent_config(config_dir, env_overrides)

    # Expand paths with ~ and environment variables
    path_keys = [
        "reviews_directory",
        ("devstack", "path"),
        ("devstack", "openrc_file"),
        ("tracking", "tested_reviews_file"),
    ]
    config = expand_config_paths(config, path_keys)

    # Add derived values for convenience
    config["devstack_path"] = config["devstack"]["path"]
    config["openrc_file"] = config["devstack"]["openrc_file"]

    # Wire forge config (same pattern as code-review-agent)
    forge_cfg = config.get("forge", {})
    config["forge_type"] = forge_cfg.get("type", "gerrit")
    config["forge_base_url"] = forge_cfg.get("base_url", "https://review.opendev.org")
    config["forge_token_env"] = forge_cfg.get("token_env")
    config["forge_username_env"] = forge_cfg.get("username_env")
    # Backward-compat key still used by some prompt templates
    config["gerrit_base_url"] = config["forge_base_url"]

    config = expand_context_config(config)
    return config


if __name__ == "__main__":
    # Test configuration loading
    print("Testing configuration loading...")
    print()

    config = load_config()

    print("Configuration loaded successfully:")
    print(f"  Reviews directory: {config['reviews_directory']}")
    print(f"  DevStack path: {config['devstack_path']}")
    print(f"  OpenRC file: {config['openrc_file']}")
    print(f"  Lock timeout: {config['devstack']['lock_timeout']}s")
    print(f"  Test timeout: {config['testing']['test_timeout']}s")
    print(f"  Cleanup on failure: {config['testing']['cleanup_on_failure']}")
    print(f"  Tracking file: {config['tracking']['tested_reviews_file']}")
    print()

    # Test filters
    if config["filters"]["only_test_repositories"]:
        print(f"  Only testing: {', '.join(config['filters']['only_test_repositories'])}")
    else:
        print("  Testing: All repositories")

    print()
    print("✅ Configuration is valid")
