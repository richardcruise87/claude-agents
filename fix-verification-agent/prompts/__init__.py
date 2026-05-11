"""Prompt templates for the fix verification agent."""
from pathlib import Path
from agents_lib import load_prompt_template

_PROMPTS_DIR = Path(__file__).parent


def get_failure_analysis_prompt(
    bug_number: str,
    bug_title: str,
    root_cause: str,
    patch_description: str,
    exit_code: int,
    execution_time: float,
    timeout_exceeded: bool,
    stdout: str,
    stderr: str,
) -> str:
    """Return a formatted failure analysis prompt."""
    template = load_prompt_template("failure_analysis_prompt", _PROMPTS_DIR)
    return template.format(
        bug_number=bug_number,
        bug_title=bug_title,
        root_cause=root_cause[:500] if root_cause else "See triage report.",
        patch_description=patch_description,
        exit_code=exit_code,
        execution_time=execution_time,
        timeout_exceeded=timeout_exceeded,
        stdout=stdout[-3000:],
        stderr=stderr[-1500:],
    )
