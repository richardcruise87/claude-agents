"""
Prompt templates for the code review agent.

This module provides functions to load and format prompt templates
from external files, keeping the main code clean and maintainable.
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
) -> str:
    """
    Get the formatted code review prompt.

    Args:
        repo_name: Repository name (e.g., "openstack/octavia")
        change_number: Gerrit change number
        current_patchset: Current patchset number being reviewed
        gerrit_base_url: Base URL for Gerrit
        repo_path: Local path to the repository
        patchset_ref: Git ref for fetching the patchset
        specific_patchset_note: Optional note about specific patchset
        previous_review_section: Optional section with previous review context
        previous_patchset: Previous patchset number if applicable

    Returns:
        Formatted prompt ready to use with the agent
    """
    template = load_prompt_template("code_review_prompt")

    # Pre-compute complex expressions that appear in the template
    patchset_display = str(current_patchset) if current_patchset else 'unknown'

    git_fetch_command = (
        f"git fetch {gerrit_base_url}/{repo_name} {patchset_ref}"
        if patchset_ref
        else f"git fetch {gerrit_base_url}/{repo_name} refs/changes/*/{change_number}/*"
    )

    patchset_comparison_section = ""
    if previous_patchset:
        patchset_comparison_section = f'''
## Step 3a: Compare with Previous Patchset (PS {previous_patchset})

**IMPORTANT**: You have context from a previous review of Patchset {previous_patchset}.

Compare the current patchset with your previous review:
- Check if issues you identified in PS {previous_patchset} were addressed
- Identify what changed between patchsets (new files, modifications, deletions)
- Note if the change is improving or regressing
- Be specific about what was fixed and what wasn't

Reference the previous review context provided at the beginning of these instructions.
'''

    # Create a dictionary with all replacement values
    # Use simple string formatting to avoid eval() complexity
    replacements = {
        'repo_name': repo_name,
        'change_number': change_number,
        'patchset_display': patchset_display,
        'gerrit_base_url': gerrit_base_url,
        'repo_path': str(repo_path),
        'specific_patchset_note': specific_patchset_note,
        'previous_review_section': previous_review_section,
        'git_fetch_command': git_fetch_command,
        'patchset_comparison_section': patchset_comparison_section,
    }

    # Replace placeholders in template
    # Handle both {var} style and complex expressions
    formatted_prompt = template

    # Replace simple placeholders
    formatted_prompt = formatted_prompt.replace('{repo_name}', repo_name)
    formatted_prompt = formatted_prompt.replace('{change_number}', change_number)
    formatted_prompt = formatted_prompt.replace("{current_patchset or 'unknown'}", patchset_display)
    formatted_prompt = formatted_prompt.replace('{GERRIT_BASE_URL}', gerrit_base_url)
    formatted_prompt = formatted_prompt.replace('{repo_path}', str(repo_path))
    formatted_prompt = formatted_prompt.replace('{specific_patchset_note}', specific_patchset_note)
    formatted_prompt = formatted_prompt.replace('{previous_review_section}', previous_review_section)

    # Replace the complex git fetch command expression
    git_fetch_expr = '{"git fetch " + GERRIT_BASE_URL + "/" + repo_name + " " + patchset_ref if patchset_ref else "git fetch " + GERRIT_BASE_URL + "/" + repo_name + " refs/changes/*/" + change_number + "/*"}'
    formatted_prompt = formatted_prompt.replace(git_fetch_expr, git_fetch_command)

    # Replace the patchset comparison conditional
    comparison_expr = '{"" if not previous_patchset else f\'\'\'\n## Step 3a: Compare with Previous Patchset (PS {previous_patchset})\n\n**IMPORTANT**: You have context from a previous review of Patchset {previous_patchset}.\n\nCompare the current patchset with your previous review:\n- Check if issues you identified in PS {previous_patchset} were addressed\n- Identify what changed between patchsets (new files, modifications, deletions)\n- Note if the change is improving or regressing\n- Be specific about what was fixed and what wasn\'t\n\nReference the previous review context provided at the beginning of these instructions.\n\'\'\'}'
    formatted_prompt = formatted_prompt.replace(comparison_expr, patchset_comparison_section)

    return formatted_prompt
