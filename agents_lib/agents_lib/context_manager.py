"""
Cross-run context and learning management for Claude agents.

Provides three capabilities:
  1. load_context_section() — read rules + global + agent context files and
     return a formatted string ready to prepend to any prompt.
  2. generate_learning() — ask the model to summarise a key learning from the
     just-completed run (called only on notable outcomes).
  3. save_learning() — append the learning to the agent's context file.
  4. expand_context_config() — expand ~ and env-vars in context file paths.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from .utils import expand_path

_LEARNING_PROMPT = """In 2-3 sentences, summarise the key learning from this {agent_name} run \
that would be useful for future similar tasks. Focus on:
- What approach worked or failed and why
- Any environment-specific discoveries
- Patterns worth remembering for next time

Run summary:
{result_summary}

Respond with just the learning text, no preamble."""

_MAX_LEARNING_CHARS = 500
_DEFAULT_RULES_FILE = "~/.claude-agents/rules.md"
_DEFAULT_GLOBAL_FILE = "~/.claude-agents/global_context.md"


def expand_context_config(config: dict) -> dict:
    """
    Expand ~ and environment variables in all paths inside config["context"].

    Call this at the end of each agent's load_config() after expand_config_paths().
    Handles extra_files as a list as well as the individual path keys.
    """
    ctx = config.get("context", {})
    for key in ("rules_file", "global_context_file", "agent_context_file"):
        if ctx.get(key):
            ctx[key] = expand_path(ctx[key])
    ctx["extra_files"] = [
        expand_path(f) for f in ctx.get("extra_files", []) if f
    ]
    config["context"] = ctx
    return config


def _read_file_capped(path: str, max_chars: int) -> str:
    """Return up to max_chars from a file, or '' if it does not exist."""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        content = p.read_text(encoding="utf-8").strip()
        return content[:max_chars] if len(content) > max_chars else content
    except OSError:
        return ""


def load_context_section(config: dict, agent_name: str = "") -> str:
    """
    Build a context block from rules + global + agent-specific context files.

    Reading order (highest priority first):
      1. context.rules_file    — project-wide rules, read-only
      2. context.global_context_file — cross-agent learnings
      3. context.agent_context_file  — agent-specific learnings
      4. context.extra_files   — any additional files the user configured

    Each file is capped at context.max_chars_per_file (default 2000 chars).
    Returns "" if all files are absent or empty.

    Args:
        config:     Agent configuration dictionary.
        agent_name: Short agent name used to derive the default agent context
                    file path (e.g. "bug_reproduction"). If omitted, the
                    agent context file is only read if explicitly configured.
    """
    ctx = config.get("context", {})
    max_chars = int(ctx.get("max_chars_per_file", 2000))

    rules_file = ctx.get("rules_file") or expand_path(_DEFAULT_RULES_FILE)
    global_file = ctx.get("global_context_file") or expand_path(_DEFAULT_GLOBAL_FILE)
    agent_file = ctx.get("agent_context_file") or (
        expand_path(f"~/.claude-agents/{agent_name}_context.md") if agent_name else ""
    )
    extra_files = ctx.get("extra_files", [])

    parts: list[str] = []

    rules_content = _read_file_capped(rules_file, max_chars)
    if rules_content:
        parts.append(f"## Project Rules (read-only)\n\n{rules_content}")

    global_content = _read_file_capped(global_file, max_chars)
    if global_content:
        parts.append(f"## Global Context & Learnings\n\n{global_content}")

    if agent_file:
        agent_content = _read_file_capped(agent_file, max_chars)
        if agent_content:
            parts.append(f"## Agent Context & Learnings\n\n{agent_content}")

    for extra in extra_files:
        extra_content = _read_file_capped(extra, max_chars)
        if extra_content:
            label = Path(extra).name
            parts.append(f"## Additional Context ({label})\n\n{extra_content}")

    if not parts:
        return ""

    header = "# Context and Learnings\n\n"
    body = "\n\n---\n\n".join(parts)
    return header + body


async def generate_learning(
    result_summary: str,
    agent_name: str,
    config: dict,
) -> Optional[str]:
    """
    Ask the model to produce a brief learning from the completed run.

    This should only be called on notable outcomes (failures, multi-attempt
    successes, environment errors) — not on every trivial successful run.

    Returns the learning text (capped at 500 chars), or None on failure.
    """
    # pylint: disable=import-outside-toplevel
    from .model_client import create_model_client

    ctx = config.get("context", {})
    if not ctx.get("save_learnings", True):
        return None

    prompt = _LEARNING_PROMPT.format(
        agent_name=agent_name,
        result_summary=result_summary[:1000],
    )

    try:
        client = create_model_client(config)
        result = await client.query(prompt=prompt)
        text = result.text.strip()
        return text[:_MAX_LEARNING_CHARS] if text else None
    except Exception:  # pylint: disable=broad-except
        return None


def save_learning(context_file: str, learning: str, agent_name: str) -> None:
    """
    Append a timestamped learning entry to the agent context file.

    Creates the file and parent directories if they do not exist.

    Note on priority: load_context_section() reads from the *start* of each
    file and caps at max_chars_per_file, so older entries are read first.
    This gives earlier learnings higher effective priority. If you want recent
    entries to take precedence, manually move them to the top of the file, or
    lower max_chars_per_file so old entries are trimmed sooner.

    Args:
        context_file: Path to the agent context markdown file.
        agent_name:   Human-readable agent name for the entry header.
        learning:     The learning text to append.
    """
    if not context_file or not learning:
        return

    path = Path(context_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    entry = f"\n### {date_str} — {agent_name}\n\n{learning}\n"

    with open(path, "a", encoding="utf-8") as fh:
        fh.write(entry)

    print(f"   📝 Learning saved to: {path.name}")
