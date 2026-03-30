"""
Configuration management for the bug triage agent.

Loads configuration from config.json or environment variables.
"""
import json
import os
from pathlib import Path


def expand_path(path_str: str) -> str:
    """Expand ~ and environment variables in path."""
    if not path_str:
        return path_str
    expanded = os.path.expanduser(path_str)
    expanded = os.path.expandvars(expanded)
    return expanded


def load_config():
    """
    Load configuration from config.json or config.sample.json.

    Environment variables override config file settings:
    - TRIAGES_OUTPUT_DIR: Override triages_output_dir
    - DEVSTACK_PATH: Override devstack_path
    - LAUNCHPAD_PROJECT: Override launchpad_project
    - MAX_BUGS: Override max_bugs_per_run

    Returns:
        dict: Configuration dictionary
    """
    config_dir = Path(__file__).parent

    # Try to load config.json, fallback to config.sample.json
    config_file = config_dir / "config.json"
    if not config_file.exists():
        config_file = config_dir / "config.sample.json"

    if not config_file.exists():
        raise FileNotFoundError(
            "No config.json or config.sample.json found. "
            "Please create config.json from config.sample.json"
        )

    with open(config_file, 'r') as f:
        config = json.load(f)

    # Apply environment variable overrides
    if os.getenv('TRIAGES_OUTPUT_DIR'):
        config['triages_output_dir'] = os.getenv('TRIAGES_OUTPUT_DIR')

    if os.getenv('DEVSTACK_PATH'):
        config['devstack_path'] = os.getenv('DEVSTACK_PATH')

    if os.getenv('LAUNCHPAD_PROJECT'):
        config['launchpad_project'] = os.getenv('LAUNCHPAD_PROJECT')

    if os.getenv('MAX_BUGS'):
        config['max_bugs_per_run'] = int(os.getenv('MAX_BUGS'))

    # Expand paths
    config['triages_output_dir'] = expand_path(config['triages_output_dir'])
    config['devstack_path'] = expand_path(config['devstack_path'])
    config['triage_tracking_file'] = expand_path(config['triage_tracking_file'])

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
    except Exception as e:
        print(f"✗ Error loading configuration: {e}")
        exit(1)
