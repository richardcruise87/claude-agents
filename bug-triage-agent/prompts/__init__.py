"""
Prompt templates for the bug triage agent.

Loads and formats prompt templates from external files.
"""
from pathlib import Path


def load_prompt_template(template_name: str) -> str:
    """
    Load a prompt template from the prompts directory.

    Args:
        template_name: Name of the template file (without .txt extension)

    Returns:
        The template content as a string

    Raises:
        FileNotFoundError: If the template file doesn't exist
    """
    prompts_dir = Path(__file__).parent
    template_file = prompts_dir / f"{template_name}.txt"

    if not template_file.exists():
        raise FileNotFoundError(f"Prompt template not found: {template_file}")

    with open(template_file, 'r', encoding='utf-8') as f:
        return f.read()


def get_bug_triage_prompt(
    bug_number: str,
    bug_title: str,
    bug_status: str,
    bug_importance: str,
    launchpad_url: str,
    date_created: str,
    date_updated: str,
    reporter: str,
    bug_description: str,
    devstack_path: str,
    triage_file: Path,
    sequence: int,
    previous_triage_summary: str = None,
    previous_sequence: int = None,
) -> str:
    """
    Get the formatted bug triage prompt.

    Args:
        bug_number: Launchpad bug number
        bug_title: Bug title
        bug_status: Bug status (New, Confirmed, etc.)
        bug_importance: Bug importance (Critical, High, etc.)
        launchpad_url: URL to the bug on Launchpad
        date_created: When bug was created
        date_updated: When bug was last updated
        reporter: Who reported the bug
        bug_description: Full bug description
        devstack_path: Path to DevStack installation
        triage_file: Path where triage will be saved
        sequence: Sequence number for this triage
        previous_triage_summary: Summary from previous triage
        previous_sequence: Previous sequence number

    Returns:
        Formatted prompt ready to use with the agent
    """
    template = load_prompt_template("bug_triage_prompt")

    # Build sequence note
    sequence_note = ""
    if sequence > 1:
        sequence_note = f"\n**NOTE**: This is triage #{sequence} for this bug. The bug has been updated since the last triage.\n"

    # Build previous triage section
    previous_triage_section = ""
    if previous_triage_summary and previous_sequence:
        previous_triage_section = f"""

## IMPORTANT: Previous Triage Context

This bug was previously triaged (triage #{previous_sequence}).

**Previous Triage Summary** (for context):
```
{previous_triage_summary}
```

**Your Task for This Triage:**
- Note what changed in the bug since last triage
- Check if new information was added
- Update your assessment based on new details
- Reference the previous triage in your analysis
- Include a "Changes Since Last Triage" section

"""
    elif previous_triage_summary:
        previous_triage_section = f"""

## IMPORTANT: Previous Triage Context

This bug was previously triaged.

**Previous Triage Summary** (for context):
```
{previous_triage_summary}
```

**Your Task for This Triage:**
- Check what changed in the bug report
- Update assessment based on any new information

"""

    # Extract potential search keywords from title and description
    # Simple approach: use first few words of title
    title_words = bug_title.lower().split()[:5]
    search_keywords = ' '.join(title_words)

    # Guess relevant files based on common patterns
    relevant_files = "."
    if "api" in bug_title.lower() or "api" in bug_description.lower():
        relevant_files = "octavia/api/"
    elif "amphora" in bug_title.lower() or "amphora" in bug_description.lower():
        relevant_files = "octavia/amphorae/"
    elif "controller" in bug_title.lower() or "worker" in bug_description.lower():
        relevant_files = "octavia/controller/"

    # Replace placeholders
    formatted_prompt = template
    formatted_prompt = formatted_prompt.replace('{bug_number}', bug_number)
    formatted_prompt = formatted_prompt.replace('{bug_title}', bug_title)
    formatted_prompt = formatted_prompt.replace('{bug_status}', bug_status)
    formatted_prompt = formatted_prompt.replace('{bug_importance}', bug_importance)
    formatted_prompt = formatted_prompt.replace('{launchpad_url}', launchpad_url)
    formatted_prompt = formatted_prompt.replace('{date_created}', date_created)
    formatted_prompt = formatted_prompt.replace('{date_updated}', date_updated)
    formatted_prompt = formatted_prompt.replace('{reporter}', reporter)
    formatted_prompt = formatted_prompt.replace('{sequence_note}', sequence_note)
    formatted_prompt = formatted_prompt.replace('{previous_triage_section}', previous_triage_section)
    formatted_prompt = formatted_prompt.replace('{bug_description}', bug_description)
    formatted_prompt = formatted_prompt.replace('{devstack_path}', devstack_path)
    formatted_prompt = formatted_prompt.replace('{triage_file}', str(triage_file))
    formatted_prompt = formatted_prompt.replace('{search_keywords}', search_keywords)
    formatted_prompt = formatted_prompt.replace('{relevant_files}', relevant_files)

    return formatted_prompt
