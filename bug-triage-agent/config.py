"""
Configuration management for the bug triage agent.

Loads configuration from config.json or environment variables.
"""
from pathlib import Path
from agents_lib import load_agent_config, apply_cutoff_date, expand_config_paths


def load_config():
    """
    Load configuration from config.json or config.sample.json.

    Environment variables override config file settings:
    - TRIAGES_OUTPUT_DIR: Override triages_output_dir
    - DEVSTACK_PATH: Override devstack_path
    - LAUNCHPAD_PROJECT: Override launchpad_project
    - MAX_BUGS: Override max_bugs_per_run
    - CUTOFF_DATE: Override cutoff_date

    Returns:
        dict: Configuration dictionary
    """
    config_dir = Path(__file__).parent

    # Define environment variable overrides
    env_overrides = {
        "TRIAGES_OUTPUT_DIR": "triages_output_dir",
        "DEVSTACK_PATH": "devstack_path",
        "LAUNCHPAD_PROJECT": "launchpad_project",
        "MAX_BUGS": "max_bugs_per_run",
        "CUTOFF_DATE": "cutoff_date",
        "CLAUDE_MODEL": "model",
    }

    # Load config using shared library
    defaults = {"model": "claude-sonnet-4-6"}
    config = load_agent_config(config_dir, env_overrides, defaults)

    # Apply cutoff date logic (default to 30 days ago)
    config = apply_cutoff_date(config, "cutoff_date", default_days=30)

    # Expand paths
    path_keys = [
        "triages_output_dir",
        "devstack_path",
        "triage_tracking_file",
    ]
    config = expand_config_paths(config, path_keys)

    return config


if __name__ == "__main__":
    # Test configuration loading
    try:
        cfg = load_config()
        print("✓ Configuration loaded successfully")
        print(f"  - Launchpad project: {cfg['launchpad_project']}")
        print(f"  - Output directory: {cfg['triages_output_dir']}")
        print(f"  - DevStack path: {cfg['devstack_path']}")
        print(f"  - Max bugs per run: {cfg['max_bugs_per_run']}")
        print(f"  - Cutoff date: {cfg['cutoff_date']}")
    except Exception as e:
        print(f"✗ Error loading configuration: {e}")
        exit(1)
