"""
Zuul CI API client for fetching build failures.

Supports the Zuul REST API as documented at:
https://zuul-ci.org/docs/zuul/latest/rest-api.html
"""
import json
import socket
import time
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.error import URLError, HTTPError

_ZUUL_TIMEOUT = 60      # seconds per attempt
_ZUUL_RETRIES = 2       # number of retry attempts after first failure


def normalize_build(build):
    """
    Flatten the nested `ref` object in a Zuul API build response to top-level fields.

    Zuul returns ref metadata (project, change, patchset, ref_url) nested under
    a `ref` key. This extracts them so the rest of the code can use consistent
    flat access patterns like build.get("patchset").
    """
    ref = build.get("ref") or {}
    build.setdefault("project", ref.get("project"))
    build.setdefault("change", ref.get("change"))
    build.setdefault("patchset", ref.get("patchset"))
    build.setdefault("ref_url", ref.get("ref_url"))
    return build


def fetch_recent_failures(project, pipeline, zuul_base_url, tenant, hours_back=24):
    """
    Fetch recent CI failures from Zuul API for a project+pipeline.

    Args:
        project: Project name (e.g., "openstack/octavia")
        pipeline: Pipeline name (e.g., "check", "gate")
        zuul_base_url: Base URL of Zuul instance (e.g., "https://zuul.opendev.org")
        tenant: Zuul tenant name (e.g., "openstack")
        hours_back: How many hours back to look for failures

    Returns:
        List of build dictionaries from Zuul API, filtered to the time window.
        Each build dict contains: uuid, job_name, project, pipeline, change, patchset,
        result, log_url, duration, voting, end_time, ref_url, nodeset, etc.
    """
    # Note: "result" is intentionally omitted here. Zuul's /builds endpoint
    # returns HTTP 500 when result= is combined with project+pipeline without
    # a specific change number. Filter for FAILURE in Python instead (below).
    params = urlencode({
        "project": project,
        "pipeline": pipeline,
        "limit": 100,
        "skip": 0,
    })

    url = f"{zuul_base_url}/api/tenant/{tenant}/builds?{params}"

    for attempt in range(1 + _ZUUL_RETRIES):
        try:
            with urlopen(url, timeout=_ZUUL_TIMEOUT) as response:
                builds = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as e:
            print(f"  Warning: HTTP {e.code} fetching Zuul builds for {project}/{pipeline}: {e}")
            return None
        except (socket.timeout, TimeoutError):
            if attempt < _ZUUL_RETRIES:
                time.sleep(5)
        except URLError as e:
            print(f"  Warning: Failed to connect to Zuul at {zuul_base_url}: {e}")
            return None
        except Exception as e:  # pylint: disable=broad-except
            print(f"  Warning: Unexpected error fetching Zuul builds: {e}")
            return None
    else:
        print(f"  Warning: Zuul API timed out for {project}/{pipeline} "
              f"after {1 + _ZUUL_RETRIES} attempts — skipping")
        return None

    if not isinstance(builds, list):
        print("  Warning: Unexpected response format from Zuul API")
        return []

    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)

    recent = []
    for build in builds:
        normalize_build(build)
        # Server-side result= filter removed (caused HTTP 500); filter here instead.
        if build.get("result") != "FAILURE":
            continue
        end_time_str = build.get("end_time")
        if not end_time_str:
            continue
        try:
            end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            if end_time >= cutoff_time:
                recent.append(build)
        except (ValueError, AttributeError):
            continue

    return recent


def group_failures_by_change(builds, skip_non_voting=False):
    """
    Group failing builds by (change, patchset, project, pipeline).

    Args:
        builds: List of Zuul build dictionaries
        skip_non_voting: If True, exclude non-voting jobs

    Returns:
        Dict mapping (change, patchset, project, pipeline) tuples to lists of builds.
        Sorted internally by job name for consistent output.
    """
    grouped = {}

    for build in builds:
        if skip_non_voting and not build.get("voting", True):
            continue

        change = build.get("change")
        patchset = build.get("patchset")
        project = build.get("project")
        pipeline = build.get("pipeline")

        if not change or not patchset or not project or not pipeline:
            continue

        key = (str(change), str(patchset), project, pipeline)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(build)

    return grouped


def get_builds_for_change(change_number, zuul_base_url, tenant, pipeline=None, result="FAILURE"):
    """
    Fetch all builds for a specific Gerrit change number.

    Args:
        change_number: Gerrit change number (int or string)
        zuul_base_url: Base URL of Zuul instance
        tenant: Zuul tenant name
        pipeline: Optional pipeline filter (e.g., "check"). None = all pipelines.
        result: Result filter — "FAILURE", "SUCCESS", or None for all results.

    Returns:
        List of build dictionaries, most recent first.
    """
    params = {"change": str(change_number), "limit": 100}
    if pipeline:
        params["pipeline"] = pipeline
    if result:
        params["result"] = result

    url = f"{zuul_base_url}/api/tenant/{tenant}/builds?{urlencode(params)}"

    for attempt in range(1 + _ZUUL_RETRIES):
        try:
            with urlopen(url, timeout=_ZUUL_TIMEOUT) as response:
                builds = json.loads(response.read().decode("utf-8"))
            break
        except HTTPError as e:
            print(f"  Warning: HTTP {e.code} fetching builds for change #{change_number}: {e}")
            return []
        except (socket.timeout, TimeoutError):
            if attempt < _ZUUL_RETRIES:
                time.sleep(5)
        except URLError as e:
            print(f"  Warning: Failed to connect to Zuul at {zuul_base_url}: {e}")
            return []
        except Exception as e:  # pylint: disable=broad-except
            print(f"  Warning: Unexpected error fetching change builds: {e}")
            return []
    else:
        print(f"  Warning: Zuul API timed out fetching builds for change "
              f"#{change_number} after {1 + _ZUUL_RETRIES} attempts")
        return []

    if not isinstance(builds, list):
        print("  Warning: Unexpected response format from Zuul API")
        return []

    for build in builds:
        normalize_build(build)

    return builds


def get_build_by_uuid(uuid, zuul_base_url, tenant):
    """
    Fetch a specific build by its UUID.

    Args:
        uuid: Zuul build UUID
        zuul_base_url: Base URL of Zuul instance
        tenant: Zuul tenant name

    Returns:
        Build dictionary, or None if not found or on error.
    """
    url = f"{zuul_base_url}/api/tenant/{tenant}/build/{uuid}"

    build = None
    for attempt in range(1 + _ZUUL_RETRIES):
        try:
            with urlopen(url, timeout=_ZUUL_TIMEOUT) as response:
                build = normalize_build(json.loads(response.read().decode("utf-8")))
            break
        except HTTPError as e:
            if e.code == 404:
                print(f"  Error: Build {uuid[:12]}... not found in Zuul tenant '{tenant}'")
                print("  Check the UUID and that you are using the correct --zuul-base-url / tenant")
            else:
                print(f"  Warning: HTTP {e.code} fetching build {uuid[:12]}...: {e}")
            return None
        except (socket.timeout, TimeoutError):
            if attempt < _ZUUL_RETRIES:
                time.sleep(5)
        except URLError as e:
            print(f"  Warning: Failed to connect to Zuul at {zuul_base_url}: {e}")
            return None
        except Exception as e:  # pylint: disable=broad-except
            print(f"  Warning: Unexpected error fetching build {uuid[:12]}...: {e}")
            return None
    else:
        print(f"  Warning: Zuul API timed out fetching build {uuid[:12]}... "
              f"after {1 + _ZUUL_RETRIES} attempts")
        return None
    return build


def get_latest_patchset_failures(builds):
    """
    From a list of failed builds for a change, isolate the latest patchset's failures.

    When a change has multiple patchsets with failures, this returns only the
    failures belonging to the most recent patchset, grouped by pipeline.

    Args:
        builds: List of build dicts for a single change number

    Returns:
        Tuple of (latest_patchset: str, grouped: dict)
        where grouped maps (patchset, project, pipeline) -> list of builds.
        Returns (None, {}) if builds is empty.
    """
    if not builds:
        return None, {}

    patchset_nums = [int(b.get("patchset", 0)) for b in builds if b.get("patchset")]
    if not patchset_nums:
        return None, {}

    latest_patchset = str(max(patchset_nums))
    latest_builds = [b for b in builds if str(b.get("patchset", "")) == latest_patchset]

    grouped = {}
    for build in latest_builds:
        project = build.get("project")
        pipeline = build.get("pipeline")
        if not project or not pipeline:
            continue
        key = (latest_patchset, project, pipeline)
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(build)

    return latest_patchset, grouped


def get_build_log_url(build):
    """
    Get the base log URL for a build.

    The log_url in Zuul API points to the base of the log artifact storage.
    Append filenames like 'job-output.txt' to get specific files.

    Args:
        build: Zuul build dictionary

    Returns:
        Log URL string, or None if not available
    """
    log_url = build.get("log_url")
    if log_url and not log_url.endswith("/"):
        log_url += "/"
    return log_url


def format_duration(seconds):
    """Format duration in seconds to human-readable string."""
    if not seconds:
        return "unknown"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
