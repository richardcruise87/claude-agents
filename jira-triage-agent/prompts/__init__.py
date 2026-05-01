"""Prompt loaders for the JIRA Triage Agent."""

from pathlib import Path
from agents_lib import load_agent_prompt

_PROMPTS_DIR = Path(__file__).parent


def get_jira_bug_triage_prompt(
    issue_key: str,
    summary: str,
    issue_type: str,
    status: str,
    priority: str,
    reporter: str,
    assignee: str,
    jira_url: str,
    created: str,
    updated: str,
    description: str,
    devstack_path: str,
    sequence: int,
    previous_triage_summary: str = None,
    previous_sequence: int = None,
    provider: str = "anthropic",
    save_path: str = None,
) -> str:
    """Return the formatted bug triage prompt for a JIRA Bug/Defect."""
    template = load_agent_prompt(
        "jira_bug_triage",
        provider=provider,
        prompts_dir=_PROMPTS_DIR,
        save_path=save_path,
    )

    sequence_note = ""
    if sequence > 1:
        sequence_note = f"\n**NOTE**: This is triage #{sequence} for this issue (it was updated since the last triage).\n"

    previous_triage_section = ""
    if previous_triage_summary and previous_sequence:
        previous_triage_section = f"""

## IMPORTANT: Previous Triage Context

This issue was previously triaged (triage #{previous_sequence}).

**Previous Triage Summary:**
```
{previous_triage_summary}
```

**Your task for this triage:**
- Note what changed in the issue since the last triage
- Update your assessment based on any new information
- Include a "Changes Since Last Triage" section

"""
    elif previous_triage_summary:
        previous_triage_section = f"""

## IMPORTANT: Previous Triage Context

**Previous Triage Summary:**
```
{previous_triage_summary}
```

**Your task:** Update the assessment based on any new information.

"""

    title_words = summary.lower().split()[:5]
    search_keywords = " ".join(title_words)
    relevant_files = "."

    formatted = template
    formatted = formatted.replace("{issue_key}", issue_key)
    formatted = formatted.replace("{summary}", summary)
    formatted = formatted.replace("{issue_type}", issue_type)
    formatted = formatted.replace("{status}", status)
    formatted = formatted.replace("{priority}", priority)
    formatted = formatted.replace("{reporter}", reporter)
    formatted = formatted.replace("{assignee}", assignee)
    formatted = formatted.replace("{jira_url}", jira_url)
    formatted = formatted.replace("{created}", created)
    formatted = formatted.replace("{updated}", updated)
    formatted = formatted.replace("{description}", description)
    formatted = formatted.replace("{devstack_path}", devstack_path)
    formatted = formatted.replace("{sequence_note}", sequence_note)
    formatted = formatted.replace("{previous_triage_section}", previous_triage_section)
    formatted = formatted.replace("{search_keywords}", search_keywords)
    formatted = formatted.replace("{relevant_files}", relevant_files)

    return formatted


def get_jira_planning_prompt(
    issue_key: str,
    summary: str,
    issue_type: str,
    status: str,
    priority: str,
    reporter: str,
    assignee: str,
    jira_url: str,
    created: str,
    updated: str,
    description: str,
    devstack_path: str,
    sequence: int,
    previous_plan_summary: str = None,
    previous_sequence: int = None,
    provider: str = "anthropic",
    save_path: str = None,
) -> str:
    """Return the formatted implementation planning prompt for a JIRA Story/Task."""
    template = load_agent_prompt(
        "jira_planning",
        provider=provider,
        prompts_dir=_PROMPTS_DIR,
        save_path=save_path,
    )

    sequence_note = ""
    if sequence > 1:
        sequence_note = f"\n**NOTE**: This is plan revision #{sequence} (the issue was updated since the last plan).\n"

    previous_plan_section = ""
    if previous_plan_summary and previous_sequence:
        previous_plan_section = f"""

## IMPORTANT: Previous Plan Context

A plan was previously produced for this issue (revision #{previous_sequence}).

**Previous Plan Summary:**
```
{previous_plan_summary}
```

**Your task for this revision:**
- Note what changed in the issue since the last plan
- Update the plan to reflect new requirements or context
- Include a "Changes Since Last Plan" section

"""
    elif previous_plan_summary:
        previous_plan_section = f"""

## IMPORTANT: Previous Plan Context

**Previous Plan Summary:**
```
{previous_plan_summary}
```

**Your task:** Update the plan based on any new information.

"""

    title_words = summary.lower().split()[:5]
    search_keywords = " ".join(title_words)

    formatted = template
    formatted = formatted.replace("{issue_key}", issue_key)
    formatted = formatted.replace("{summary}", summary)
    formatted = formatted.replace("{issue_type}", issue_type)
    formatted = formatted.replace("{status}", status)
    formatted = formatted.replace("{priority}", priority)
    formatted = formatted.replace("{reporter}", reporter)
    formatted = formatted.replace("{assignee}", assignee)
    formatted = formatted.replace("{jira_url}", jira_url)
    formatted = formatted.replace("{created}", created)
    formatted = formatted.replace("{updated}", updated)
    formatted = formatted.replace("{description}", description)
    formatted = formatted.replace("{devstack_path}", devstack_path)
    formatted = formatted.replace("{sequence_note}", sequence_note)
    formatted = formatted.replace("{previous_plan_section}", previous_plan_section)
    formatted = formatted.replace("{search_keywords}", search_keywords)

    return formatted
