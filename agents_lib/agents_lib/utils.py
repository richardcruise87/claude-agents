"""
Common utility functions for Claude agents.
"""
import os
import re


# ── Sensitive-data sanitization ───────────────────────────────────────────────

_SENSITIVE_KEYS = (
    "password", "passwd", "secret", "api_key", "apikey",
    "token", "auth_token", "access_token", "bearer",
    "private_key", "ssh_key", "ssh_pass",
    "http_password", "http_passwd",
    "client_secret", "consumer_secret",
)
_KEY_PAT = r"(?:" + "|".join(re.escape(k) for k in _SENSITIVE_KEYS) + r")"
_REDACTED = "[REDACTED]"

_HOME_DIR = os.path.expanduser("~").rstrip("/")

_SANITIZE_RULES: list[tuple] = [
    # Home directory paths — replace with ~ to avoid leaking usernames / machine layout
    *([(re.compile(re.escape(_HOME_DIR)), "~")] if _HOME_DIR and _HOME_DIR != "/" else []),

    # PEM private key blocks (multi-line)
    (re.compile(
        r'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----.*?-----END (?:[A-Z ]+ )?PRIVATE KEY-----',
        re.DOTALL,
    ), f"-----BEGIN PRIVATE KEY-----\n{_REDACTED}\n-----END PRIVATE KEY-----"),

    # Authorization header values
    (re.compile(r'(?i)(Authorization\s*:\s*(?:Bearer|Basic|Digest)\s+)\S+'),
     rf'\1{_REDACTED}'),

    # export VAR=value  /  VAR=value  where VAR contains a sensitive name
    (re.compile(rf'(?i)(export\s+)?({_KEY_PAT})\s*=\s*\S+'), rf'\2={_REDACTED}'),

    # --flag value  /  --flag=value  for sensitive CLI flags.
    # The sensitive keyword may appear after a prefix (e.g. --os-password, --db-token).
    (re.compile(rf'(?i)(--(?:\w+-)*{_KEY_PAT}(?:[-_]\w+)*)\s+(?!-)\S+'), rf'\1 {_REDACTED}'),
    (re.compile(rf'(?i)(--(?:\w+-)*{_KEY_PAT}(?:[-_]\w+)*)=\S+'), rf'\1={_REDACTED}'),

    # "key": "value"  /  key = value  in JSON/YAML/INI config
    (re.compile(rf'(?i)("{_KEY_PAT}"\s*:\s*")[^"]+(")', ), rf'\1{_REDACTED}\2'),
    (re.compile(rf"(?i)('{_KEY_PAT}'\s*:\s*')[^']+(')", ), rf'\1{_REDACTED}\2'),
    (re.compile(rf'(?i)(\b{_KEY_PAT}\s*=\s*)(?!https?://)\S+'), rf'\1{_REDACTED}'),

    # URL embedded credentials: scheme://[user[:password]]@host.
    # Redact everything between :// and the final @ (greedy match handles
    # passwords that themselves contain @ signs).
    (re.compile(r'(?i)([a-z][a-z0-9+\-.]*://)([^/\s@]+(?::[^/\s@]*)?(?:@[^/\s@]+)*@)'),
     rf'\1{_REDACTED}@'),

    # Long token-like strings (≥20 chars) following a sensitive keyword on the same line
    (re.compile(rf'(?i)(\b{_KEY_PAT}\b\s*[:\s]\s*)([A-Za-z0-9+/]{{20,}}={{0,2}})'),
     rf'\1{_REDACTED}'),
]


def sanitize_for_forge(text: str) -> str:
    """Strip passwords, tokens, SSH keys, and other credentials from text.

    Applied to all content before it is posted to a public forge. Uses a
    conservative set of pattern-based rules; normal review prose is unaffected.

    Args:
        text: Raw review or comment text that may contain sensitive values.

    Returns:
        Text with sensitive values replaced by ``[REDACTED]``.
    """
    for pattern, replacement in _SANITIZE_RULES:
        text = pattern.sub(replacement, text)
    return text


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
