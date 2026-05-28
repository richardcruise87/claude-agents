"""
HTTP log retrieval with retry, gzip support, and size limits.

Designed for fetching CI job logs (e.g. from Zuul/Swift object store) where:
- Logs may be served plain or gzip-compressed (.gz extension)
- Network hiccups are common — retry with backoff
- Files can be very large — truncate to a tail of meaningful size
"""

import gzip
import time
import urllib.error
import urllib.request
from typing import Tuple


def fetch_log_section(
    url: str,
    tail_lines: int = 500,
    max_bytes: int = 5_000_000,
    retries: int = 3,
    timeout: int = 30,
) -> Tuple[bool, str]:
    """Download a log file with retry, gzip support, and size limits.

    Tries the plain URL first; if that returns a 404 or network error,
    appends '.gz' to the URL and retries (handles Zuul's dual
    plain/compressed log layout).  Decompresses gzip automatically.
    Truncates to the last ``tail_lines`` lines when content is large.

    Args:
        url:       URL of the log file (plain or .gz).
        tail_lines: Maximum number of lines to return (from the end).
        max_bytes:  Maximum raw bytes to download before truncating.
        retries:   Maximum fetch attempts per URL variant.
        timeout:   HTTP request timeout in seconds.

    Returns:
        (True, content)        on success.
        (False, error_message) when all attempts fail.
    """
    # Build the two URL variants to try: plain then .gz (or just one if
    # the caller already passed a .gz URL).
    if url.endswith(".gz"):
        urls_to_try = [url]
    else:
        urls_to_try = [url, url + ".gz"]

    last_error = "unknown error"
    for try_url in urls_to_try:
        for attempt in range(1, retries + 1):
            try:
                raw = _fetch_bytes(try_url, max_bytes, timeout)
                text = _decompress_if_needed(raw, try_url)
                return (True, _tail(text, tail_lines))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    last_error = f"HTTP 404 for {try_url}"
                    break  # 404 is definitive — try the .gz variant
                last_error = f"HTTP {exc.code} for {try_url}: {exc.reason}"
            except urllib.error.URLError as exc:
                last_error = f"Network error for {try_url}: {exc.reason}"
            except Exception as exc:  # pylint: disable=broad-except
                last_error = f"Error fetching {try_url}: {exc}"

            if attempt < retries:
                time.sleep(2 ** attempt)  # 2 s, 4 s

    return (False, f"Failed to fetch log after all attempts: {last_error}")


def _fetch_bytes(url: str, max_bytes: int, timeout: int) -> bytes:
    """Fetch up to max_bytes from url. Raises urllib errors on failure."""
    req = urllib.request.Request(url, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
        return resp.read(max_bytes)


def _decompress_if_needed(data: bytes, url: str) -> str:
    """Decompress gzip data if the URL ends with .gz, otherwise decode as UTF-8."""
    if url.endswith(".gz"):
        data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def _tail(text: str, n: int) -> str:
    """Return the last n lines of text, with a truncation note if lines were dropped."""
    lines = text.splitlines()
    if len(lines) <= n:
        return text
    kept = lines[-n:]
    dropped = len(lines) - n
    return f"[... {dropped} earlier lines omitted ...]\n" + "\n".join(kept)
