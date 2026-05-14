"""Prompt templates for the backport review agent."""
import json
from pathlib import Path
from typing import Optional

from agents_lib import load_agent_prompt

_PROMPTS_DIR = Path(__file__).parent


def get_backport_review_prompt(
    repo_name: str,
    change_number: str,
    current_patchset: int,
    gerrit_base_url: str,
    repo_path: Path,
    patchset_ref: str,
    target_branch: str = "",
    source_branch: str = "master",
    specific_patchset_note: str = "",
    previous_review_section: str = "",
    previous_patchset: Optional[int] = None,
    provider: str = "anthropic",
    save_path: Optional[str] = None,
    forge_type: str = "gerrit",
    forge_url: str = "",
    sequence: int = 1,
    head_sha: str = "",
    backport_rules_section: str = "",
    backport_branches_section: str = "",
    triage_reports_dir: str = "",
) -> str:
    """
    Get the formatted backport review prompt.

    Reuses the backport_review_prompt.txt template which covers all standard
    review steps plus backport-specific validation (cherry-pick comparison,
    Backport-Candidate label check, branch appropriateness).
    """
    template = load_agent_prompt(
        "backport_review",
        provider=provider,
        prompts_dir=_PROMPTS_DIR,
        save_path=save_path,
    )

    patchset_display = str(current_patchset) if current_patchset else "unknown"

    if forge_type == "gerrit":
        git_fetch_command = (
            f"git fetch {gerrit_base_url}/{repo_name} {patchset_ref}"
            if patchset_ref
            else f"git fetch {gerrit_base_url}/{repo_name} refs/changes/*/{change_number}/*"
        )
    else:
        git_fetch_command = f"git fetch origin {patchset_ref} && git checkout FETCH_HEAD"

    if not backport_rules_section:
        backport_rules_section = "No backport rules configured."

    if not backport_branches_section:
        backport_branches_section = "No backport target branches configured."

    formatted = template
    formatted = formatted.replace("{repo_name}", repo_name)
    formatted = formatted.replace("{change_number}", change_number)
    formatted = formatted.replace("{current_patchset}", patchset_display)
    formatted = formatted.replace("{gerrit_base_url}", gerrit_base_url)
    formatted = formatted.replace("{repo_path}", str(repo_path))
    formatted = formatted.replace("{target_branch}", target_branch)
    formatted = formatted.replace("{source_branch}", source_branch)
    formatted = formatted.replace("{git_fetch_command}", git_fetch_command)
    formatted = formatted.replace("{specific_patchset_note}", specific_patchset_note)
    formatted = formatted.replace("{previous_review_section}", previous_review_section)
    formatted = formatted.replace("{save_path}", save_path or "")
    formatted = formatted.replace("{forge_url}", forge_url)
    formatted = formatted.replace("{backport_rules_section}", backport_rules_section)
    formatted = formatted.replace("{backport_branches_section}", backport_branches_section)
    formatted = formatted.replace("{triage_reports_dir}", triage_reports_dir)
    return formatted
