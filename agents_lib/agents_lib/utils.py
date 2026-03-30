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
