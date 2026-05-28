"""
Prompt templates for the code review agent.

This module provides functions to load and format prompt templates
from external files, keeping the main code clean and maintainable.
"""
from pathlib import Path

from agents_lib import load_agent_prompt as _load_agent_prompt

_PROMPTS_DIR = Path(__file__).parent


def get_code_review_prompt(
    repo_name: str,
    change_number: str,
    current_patchset: int,
    gerrit_base_url: str,
    repo_path: Path,
    patchset_ref: str,
    specific_patchset_note: str = "",
    previous_review_section: str = "",
    previous_patchset: int = None,
    provider: str = "anthropic",
    save_path: str = None,
    forge_type: str = "gerrit",
    forge_url: str = "",
    sequence: int = 1,
    head_sha: str = "",
    backport_rules_section: str = "",
    backport_branches_section: str = "",
    triage_reports_dir: str = "",
    # New: pre-fetched data from Python
    commit_info_text: str = "",
    changed_files_text: str = "",
    test_results_text: str = "",
    bug_context_text: str = "",
    expanded_backport_branches_text: str = "",
    report_template: str = "",
) -> str:
    """Get the formatted code review prompt.

    Args:
        repo_name:          Repository name (e.g., "openstack/octavia")
        change_number:      Gerrit change number / PR number
        current_patchset:   Patchset number being reviewed
        gerrit_base_url:    Base URL for Gerrit
        repo_path:          Local path to the repository
        patchset_ref:       Git ref for fetching the patchset (kept for PR prompt compat)
        specific_patchset_note: Optional note about specific patchset
        previous_review_section: Optional section with previous review context
        previous_patchset:  Previous patchset number if applicable
        provider:           Model provider ("anthropic" | "vertex")
        save_path:          Absolute path where the AI must write the report
        forge_type:         "gerrit" | "github" | "gitlab"
        forge_url:          Full URL to view the change in a browser
        sequence:           Review sequence number (1 = first review)
        head_sha:           Expected commit SHA after checkout
        backport_rules_section:  Markdown describing backport rules
        backport_branches_section: Markdown describing configured backport branches
        triage_reports_dir: Directory containing local triage reports
        commit_info_text:   Pre-formatted commit info from git_info.get_commit_info()
        changed_files_text: Pre-formatted changed files from git_info.get_changed_files()
        test_results_text:  Pre-formatted test results from run_commands.format_command_results()
        bug_context_text:   Pre-fetched bug context (triage files, Launchpad info)
        expanded_backport_branches_text: Resolved branch names (wildcards expanded)
        report_template:    Pre-filled report template for the AI to complete

    Returns:
        Formatted prompt ready to use with the AI agent.
    """
    prompt_name = "code_review" if forge_type == "gerrit" else "code_review_prompt_pr"
    template = _load_agent_prompt(
        prompt_name, provider=provider, prompts_dir=_PROMPTS_DIR, save_path=save_path
    )

    patchset_display = str(current_patchset) if current_patchset else "unknown"
    pr_or_mr = "MR" if forge_type == "gitlab" else "PR"

    # Git fetch command (still used by the PR/MR prompt for GitHub/GitLab)
    if forge_type == "gerrit":
        git_fetch_command = (
            f"git fetch {gerrit_base_url}/{repo_name} {patchset_ref}"
            if patchset_ref
            else f"git fetch {gerrit_base_url}/{repo_name} refs/changes/*/{change_number}/*"
        )
    else:
        git_fetch_command = f"git fetch origin {patchset_ref} && git checkout FETCH_HEAD"

    patchset_comparison_section = ""
    if previous_patchset:
        patchset_comparison_section = f"""
### Compare with Previous Patchset (PS {previous_patchset})

**IMPORTANT**: You have context from a previous review of Patchset {previous_patchset}.

- Check if issues you identified in PS {previous_patchset} were addressed
- Identify what changed between patchsets (new files, modifications, deletions)
- Note if the change is improving or regressing
- Be specific about what was fixed and what wasn't

Reference the previous review context provided at the beginning of these instructions.
"""

    # Defaults for pre-fetched data when not supplied (e.g. PR/MR path)
    if not commit_info_text:
        commit_info_text = "_Commit information not pre-fetched. Run `git log -1 --pretty=full` to retrieve it._"
    if not changed_files_text:
        changed_files_text = "_Changed file information not pre-fetched. Run `git show --stat` and `git diff HEAD~1` to retrieve it._"
    if not test_results_text:
        test_results_text = "_No test commands were configured or test results were not pre-captured._"
    if not bug_context_text:
        bug_context_text = "_No bug references found in commit message, or bug context was not pre-fetched._"
    if not expanded_backport_branches_text:
        expanded_backport_branches_text = backport_branches_section or "_No backport branches configured._"
    if not report_template:
        report_template = f"[Write the full review report here for change #{change_number}]"

    formatted = template

    # Simple substitutions
    formatted = formatted.replace("{repo_name}", repo_name)
    formatted = formatted.replace("{change_number}", change_number)
    formatted = formatted.replace("{patchset_display}", patchset_display)
    formatted = formatted.replace("{current_patchset or 'unknown'}", patchset_display)
    formatted = formatted.replace("{GERRIT_BASE_URL}", gerrit_base_url)
    formatted = formatted.replace("{repo_path}", str(repo_path))
    formatted = formatted.replace("{specific_patchset_note}", specific_patchset_note)
    formatted = formatted.replace("{previous_review_section}", previous_review_section)
    formatted = formatted.replace("{patchset_comparison_section}", patchset_comparison_section)
    formatted = formatted.replace("{head_sha}", head_sha)
    formatted = formatted.replace("{save_path}", save_path or "")
    formatted = formatted.replace("{backport_rules_section}", backport_rules_section)
    formatted = formatted.replace("{backport_branches_section}", backport_branches_section)
    formatted = formatted.replace("{triage_reports_dir}", triage_reports_dir)
    # New pre-fetched data placeholders
    formatted = formatted.replace("{commit_info_text}", commit_info_text)
    formatted = formatted.replace("{changed_files_text}", changed_files_text)
    formatted = formatted.replace("{test_results_text}", test_results_text)
    formatted = formatted.replace("{bug_context_text}", bug_context_text)
    formatted = formatted.replace("{expanded_backport_branches_text}", expanded_backport_branches_text)
    formatted = formatted.replace("{report_template}", report_template)
    # PR/MR-specific
    formatted = formatted.replace("{pr_or_mr}", pr_or_mr)
    formatted = formatted.replace("{forge_url}", forge_url)
    formatted = formatted.replace("{sequence}", str(sequence))
    formatted = formatted.replace("{git_fetch_command}", git_fetch_command)

    # Replace the old complex git-fetch expression that appeared in the previous Gerrit prompt
    # (kept for safety in case any cached/old template still contains it)
    _old_fetch_expr = (
        '{"git fetch " + GERRIT_BASE_URL + "/" + repo_name + " " + patchset_ref'
        ' if patchset_ref else "git fetch " + GERRIT_BASE_URL + "/" + repo_name'
        ' + " refs/changes/*/" + change_number + "/*"}'
    )
    formatted = formatted.replace(_old_fetch_expr, git_fetch_command)

    # Replace old patchset comparison conditional (previous Gerrit prompt format)
    _old_comparison_expr = (
        '{"" if not previous_patchset else f\'\'\'\n'
        '## Step 3a: Compare with Previous Patchset (PS {previous_patchset})\n\n'
        '**IMPORTANT**: You have context from a previous review of Patchset {previous_patchset}.\n\n'
        'Compare the current patchset with your previous review:\n'
        '- Check if issues you identified in PS {previous_patchset} were addressed\n'
        '- Identify what changed between patchsets (new files, modifications, deletions)\n'
        '- Note if the change is improving or regressing\n'
        '- Be specific about what was fixed and what wasn\'t\n\n'
        'Reference the previous review context provided at the beginning of these instructions.\n'
        '\'\'\'}'
    )
    formatted = formatted.replace(_old_comparison_expr, patchset_comparison_section)

    return formatted
