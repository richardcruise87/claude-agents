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

    with open(template_file, 'r', encoding='utf-8') as f:
        return f.read()


def load_agent_prompt(
    name: str,
    provider: str = "anthropic",
    prompts_dir=None,
    save_path: str | None = None,
) -> str:
    """Load the combined prompt (instructions + output template) for an agent.

    Search order for the instruction file:
      1. {name}_prompt_{provider}.txt  (provider-specific variant)
      2. {name}_prompt.txt             (generic fallback)

    If {name}_template.txt exists it is appended as the "Output Format" section.

    For the Anthropic provider, if save_path is given, a Write-tool instruction
    is appended directing the model to write its output to that path.  For other
    providers the instruction is omitted — the calling agent writes the file
    itself from ModelResult.text.

    Args:
        name:       Base name, e.g. "bug_triage", "code_review".
        provider:   Provider name: "anthropic", "openai", "google".
        prompts_dir: Directory containing the .txt files. Defaults to cwd/prompts.
        save_path:  Absolute path the model should write the report to
                    (Anthropic only; ignored for other providers).

    Returns:
        Ready-to-use prompt string (placeholders still present for the caller
        to substitute via format_prompt / str.replace).
    """
    if prompts_dir is None:
        prompts_dir = Path.cwd() / "prompts"
    prompts_dir = Path(prompts_dir)

    # Load instruction file (provider-specific variant preferred)
    specific = prompts_dir / f"{name}_prompt_{provider}.txt"
    generic = prompts_dir / f"{name}_prompt.txt"
    instructions_file = specific if specific.exists() else generic

    if not instructions_file.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {generic}\n"
            f"(also tried provider-specific: {specific})"
        )
    instructions = instructions_file.read_text(encoding="utf-8")

    # Append output template if present
    template_file = prompts_dir / f"{name}_template.txt"
    if template_file.exists():
        template_content = template_file.read_text(encoding="utf-8")
        instructions += (
            "\n\n## Output Format\n\n"
            "Produce the report with the following structure:\n\n"
            + template_content
        )

    # Add file-write instruction for Anthropic only
    if provider == "anthropic" and save_path:
        instructions += (
            f"\n\nUse the Write tool to save the complete document to: {save_path}\n"
            "DO NOT just output the content — you MUST write it to the file using the Write tool."
        )

    return instructions


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
