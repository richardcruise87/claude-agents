"""
Common utility functions for Claude agents.
"""
import os
import re


def expand_path(path_str):
    """
    Expand ~ and environment variables in paths.

    Args:
        path_str: Path string to expand

    Returns:
        Expanded path string
    """
    if not path_str:
        return path_str
    expanded = os.path.expanduser(path_str)
    expanded = os.path.expandvars(expanded)
    return expanded


def slugify(text, max_length=50):
    """
    Convert text to a filesystem-safe slug.

    Args:
        text: Text to convert
        max_length: Maximum length of slug

    Returns:
        Slugified string
    """
    # Convert to lowercase
    text = text.lower()

    # Replace special characters with hyphens
    text = re.sub(r'[^a-z0-9]+', '_', text)

    # Remove leading/trailing hyphens
    text = text.strip('_')

    # Limit length
    if len(text) > max_length:
        text = text[:max_length].rstrip('_')

    return text


def format_usage_info(usage_data=None, cost_usd=None, model=None, duration_ms=None):
    """
    Format token usage and cost information for reports.

    Args:
        usage_data: Dictionary with token counts (from message.usage)
        cost_usd: Total cost in USD (from message.total_cost_usd)
        model: Model name (from message.model)
        duration_ms: Duration in milliseconds (from message.duration_ms)

    Returns:
        Formatted markdown string with usage information
    """
    if not usage_data and cost_usd is None:
        return "**Usage Information:** Not available\n"

    lines = []
    lines.append("## Token Usage & Cost")
    lines.append("")

    # Model information
    if model:
        lines.append(f"**Model:** `{model}`")

    # Duration
    if duration_ms:
        duration_sec = duration_ms / 1000
        lines.append(f"**Duration:** {duration_sec:.2f}s")

    # Token counts
    if usage_data:
        lines.append("")
        lines.append("### Token Usage")
        lines.append("")

        input_tokens = usage_data.get('input_tokens', 0)
        output_tokens = usage_data.get('output_tokens', 0)
        cache_creation_tokens = usage_data.get('cache_creation_input_tokens', 0)
        cache_read_tokens = usage_data.get('cache_read_input_tokens', 0)

        lines.append(f"- **Input tokens:** {input_tokens:,}")
        if cache_creation_tokens > 0:
            lines.append(f"- **Cache creation tokens:** {cache_creation_tokens:,}")
        if cache_read_tokens > 0:
            lines.append(f"- **Cache read tokens:** {cache_read_tokens:,}")
        lines.append(f"- **Output tokens:** {output_tokens:,}")
        total = input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens
        lines.append(f"- **Total tokens:** {total:,}")

    # Cost information
    if cost_usd is not None:
        lines.append("")
        lines.append("### Cost")
        lines.append("")
        lines.append(f"**Total Cost:** ${cost_usd:.6f} USD")

    lines.append("")
    return "\n".join(lines)
