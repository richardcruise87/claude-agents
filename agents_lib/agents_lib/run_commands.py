"""
Configurable command runner for agent pre-flight test execution.

Runs a list of commands (e.g. tox environments) in Python so that agent
prompts receive deterministic pre-captured output rather than instructing
the AI to execute shell commands itself.
"""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class CommandResult:
    """Result of a single command execution."""

    name: str           # human-readable label (e.g. "unit tests")
    command: List[str]  # the command as a list (e.g. ["tox", "-e", "py3"])
    returncode: int
    stdout: str         # trimmed to max_output_lines
    stderr: str         # trimmed to max_output_lines
    duration_s: float
    timed_out: bool
    output_truncated: bool = False

    @property
    def passed(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def status_emoji(self) -> str:
        if self.timed_out:
            return "⏰"
        return "✅" if self.passed else "❌"

    def format_for_prompt(self) -> str:
        """Return a compact block suitable for embedding in a prompt."""
        cmd_str = " ".join(self.command)
        header = f"### {self.name} (`{cmd_str}`)"
        result_word = 'PASS' if self.passed else ('TIMEOUT' if self.timed_out else 'FAIL')
        status = f"**Status**: {self.status_emoji} {result_word}  (exit {self.returncode}, {self.duration_s:.1f}s)"
        body_parts = []
        combined = (self.stdout + self.stderr).strip()
        if combined:
            trunc_note = "\n[output truncated]" if self.output_truncated else ""
            body_parts.append(f"```\n{combined}{trunc_note}\n```")
        return "\n".join([header, status] + body_parts)


def run_command_list(
    commands: List[dict],
    cwd: Path,
    env: Optional[dict] = None,
    max_output_lines: int = 200,
) -> List[CommandResult]:
    """Run a list of commands sequentially and return their results.

    Each command dict has keys:
        name (str):    Human-readable label shown in the prompt.
        cmd (list):    Command as a list of strings, e.g. ["tox", "-e", "py3"].
        timeout (int): Seconds before the command is killed (default: 300).

    Args:
        commands:         List of command dicts to run.
        cwd:              Working directory for all commands.
        env:              Optional environment variables (merged with current env).
        max_output_lines: Maximum lines of stdout+stderr to keep per command.

    Returns:
        List of CommandResult objects in execution order.
    """
    import os
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    results: List[CommandResult] = []

    for spec in commands:
        name = spec.get("name", " ".join(spec["cmd"]))
        cmd = spec["cmd"]
        timeout = spec.get("timeout", 300)

        print(f"  ▶ {name}: {' '.join(cmd)}")
        t0 = time.monotonic()
        timed_out = False
        returncode = -1
        raw_stdout = ""
        raw_stderr = ""

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=full_env,
                check=False,
            )
            returncode = result.returncode
            raw_stdout = result.stdout
            raw_stderr = result.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = -1
            raw_stdout = exc.stdout or ""
            raw_stderr = exc.stderr or f"Command timed out after {timeout}s"
        except FileNotFoundError:
            returncode = 127
            raw_stderr = f"Command not found: {cmd[0]}"

        duration = time.monotonic() - t0

        # Trim output to last max_output_lines lines (most relevant for failures)
        stdout_lines = raw_stdout.splitlines()
        stderr_lines = raw_stderr.splitlines()
        combined_lines = stdout_lines + stderr_lines
        truncated = len(combined_lines) > max_output_lines
        if truncated:
            kept = combined_lines[-max_output_lines:]
            stdout_trimmed = "\n".join(kept)
            stderr_trimmed = ""
        else:
            stdout_trimmed = raw_stdout
            stderr_trimmed = raw_stderr

        status = "✅ PASS" if returncode == 0 and not timed_out else ("⏰ TIMEOUT" if timed_out else "❌ FAIL")
        print(f"    {status} ({duration:.1f}s)")

        results.append(CommandResult(
            name=name,
            command=cmd,
            returncode=returncode,
            stdout=stdout_trimmed,
            stderr=stderr_trimmed,
            duration_s=round(duration, 1),
            timed_out=timed_out,
            output_truncated=truncated,
        ))

    return results


def format_command_results(results: List[CommandResult]) -> str:
    """Format a list of CommandResult objects as a markdown block for prompts."""
    if not results:
        return "_No test commands were configured._"
    return "\n\n".join(r.format_for_prompt() for r in results)
