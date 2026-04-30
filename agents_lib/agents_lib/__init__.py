"""
Claude Agents Shared Library

Shared utilities for Claude-based automation agents.
"""

__version__ = "1.0.0"

from .utils import expand_path, slugify, format_usage_info
from .config_loader import (
    load_agent_config,
    apply_cutoff_date,
    expand_config_paths,
)
from .prompt_loader import load_prompt_template, format_prompt
from .tracking import (
    load_tracking_file,
    save_tracking_file,
    should_process_item,
    record_processed_item,
    create_output_filename,
)
from .devstack_checks import (
    DevStackHealth,
    BranchCheck,
    check_devstack_health,
    check_repo_on_main_branch,
    checkout_main_branch,
    cleanup_test_environment,
    format_health_report,
)
from .devstack_lock import (
    DevStackLock,
    devstack_lock,
    check_devstack_available,
    get_unique_resource_prefix,
)
from .notifications import load_notifications_config, notify_report
from .model_client import ModelResult, ModelClient, create_model_client
from .prompt_loader import load_agent_prompt

__all__ = [
    "expand_path",
    "slugify",
    "format_usage_info",
    "load_agent_config",
    "apply_cutoff_date",
    "expand_config_paths",
    "load_prompt_template",
    "format_prompt",
    "load_tracking_file",
    "save_tracking_file",
    "should_process_item",
    "record_processed_item",
    "create_output_filename",
    "DevStackHealth",
    "BranchCheck",
    "check_devstack_health",
    "check_repo_on_main_branch",
    "checkout_main_branch",
    "cleanup_test_environment",
    "format_health_report",
    "DevStackLock",
    "devstack_lock",
    "check_devstack_available",
    "get_unique_resource_prefix",
    "load_notifications_config",
    "notify_report",
    "ModelResult",
    "ModelClient",
    "create_model_client",
    "load_agent_prompt",
]
