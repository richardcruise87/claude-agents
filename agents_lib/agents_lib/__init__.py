"""
Claude Agents Shared Library

Shared utilities for Claude-based automation agents.
"""

__version__ = "1.0.0"

from .utils import expand_path, slugify, format_usage_info, sanitize_for_forge, build_feedback_comment, find_latest_report
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
from .forge_client import (
    LineComment, ChangeInfo, ForgeClient,
    GerritClient, GitHubClient, GitLabClient, create_forge_client,
)
from .review_history import (
    ReviewRecord,
    load_review_history,
    should_review_change,
    record_review,
    create_review_filename,
    find_previous_reviews,
    load_previous_review_context,
)
from .context_manager import (
    expand_context_config,
    load_context_section,
    generate_learning,
    save_learning,
)
from .launchpad_client import (
    post_launchpad_comment,
    post_launchpad_comment_from_config,
    get_launchpad_bug_comments,
    post_report_to_launchpad,
)
from .forge_feedback import (
    extract_forge_comment,
    extract_line_comments,
    determine_vote,
    extract_ci_forge_comment,
    extract_devstack_forge_comment,
    determine_backport_vote,
)

__all__ = [
    "expand_path",
    "slugify",
    "format_usage_info",
    "sanitize_for_forge",
    "build_feedback_comment",
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
    "LineComment",
    "ChangeInfo",
    "ForgeClient",
    "GerritClient",
    "GitHubClient",
    "GitLabClient",
    "create_forge_client",
    "ReviewRecord",
    "load_review_history",
    "should_review_change",
    "record_review",
    "create_review_filename",
    "find_previous_reviews",
    "load_previous_review_context",
    "expand_context_config",
    "load_context_section",
    "generate_learning",
    "save_learning",
    "extract_forge_comment",
    "extract_line_comments",
    "determine_vote",
    "extract_ci_forge_comment",
    "extract_devstack_forge_comment",
    "determine_backport_vote",
    "post_launchpad_comment",
    "post_launchpad_comment_from_config",
    "get_launchpad_bug_comments",
    "post_report_to_launchpad",
    "find_latest_report",
]
