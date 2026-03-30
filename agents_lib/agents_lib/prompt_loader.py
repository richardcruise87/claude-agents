"""
Prompt template loading utilities for Claude agents.
"""
from pathlib import Path


def load_prompt_template(template_name, prompts_dir=None):
    """
    Load a prompt template from a file.

    Args:
        template_name: Name of the template (without .txt extension)
        prompts_dir: Directory containing prompt templates.
                    If None, looks in ../prompts/ relative to caller

    Returns:
        Template content as string

    Raises:
        FileNotFoundError: If template file doesn't exist
    """
    if prompts_dir is None:
        # Default to prompts/ directory adjacent to where this is called from
        # This won't work perfectly, so better to pass it explicitly
        prompts_dir = Path.cwd() / "prompts"
    else:
        prompts_dir = Path(prompts_dir)

    template_file = prompts_dir / f"{template_name}.txt"

    if not template_file.exists():
        raise FileNotFoundError(
            f"Prompt template not found: {template_file}\n"
            f"Expected location: {template_file.absolute()}"
        )

    with open(template_file, 'r') as f:
        return f.read()


def format_prompt(template, **replacements):
    """
    Format a prompt template with replacements.

    Args:
        template: Template string with {placeholder} markers
        **replacements: Keyword arguments for replacement values

    Returns:
        Formatted prompt string
    """
    formatted = template
    for key, value in replacements.items():
        placeholder = f"{{{key}}}"
        formatted = formatted.replace(placeholder, str(value))
    return formatted
