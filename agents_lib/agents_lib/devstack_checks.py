"""
DevStack health and environment checks shared by all agents.

Provides health checking, branch verification, and cleanup utilities.

The health check system is built around a named-check registry (DevStackChecker).
Checks can be registered, enabled, or disabled individually — either through code
or via the ``disabled_checks`` list in the agent's devstack config block:

    "devstack": {
        "disabled_checks": ["disk_space"]
    }

Use ``build_default_checker(config)`` to get a checker pre-loaded with the three
built-in checks (services, api_connectivity, disk_space).  Call
``check_devstack_health(config)`` as a one-liner convenience wrapper.

To add an agent-specific check:

    checker = build_default_checker(config)
    checker.register("valkey", lambda: _check_valkey(config))
    health = checker.run()
"""
import subprocess
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Result of a single named health check."""
    name: str
    passed: bool
    message: str


@dataclass
class DevStackHealth:
    """Aggregated results from all health checks."""
    all_healthy: bool
    service_status: Dict[str, bool]   # service_name → running
    api_reachable: bool
    disk_space_gb: float
    errors: List[str]
    check_results: List[CheckResult] = field(default_factory=list)


@dataclass
class BranchCheck:
    """Git branch verification results."""
    on_main: bool
    current_branch: str
    repo_path: Path
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class DevStackChecker:
    """
    Registry of named health checks.

    Each check is a zero-argument callable that returns a CheckResult.  Checks
    can be enabled or disabled at registration time, or globally via the
    ``disabled_checks`` config key.

    Usage::

        checker = DevStackChecker(config)
        checker.register("my_check", lambda: CheckResult("my_check", True, "OK"))
        health = checker.run()
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._checks: List[Tuple[str, Callable[[], CheckResult], bool]] = []

    def register(
        self,
        name: str,
        fn: Callable[[], CheckResult],
        enabled: bool = True,
    ) -> "DevStackChecker":
        """Register a check. Returns self for optional chaining."""
        self._checks.append((name, fn, enabled))
        return self

    def run(self) -> DevStackHealth:
        """Run all enabled checks and return aggregated health status."""
        errors: List[str] = []
        check_results: List[CheckResult] = []
        service_status: Dict[str, bool] = {}
        api_reachable = True
        disk_space_gb = 0.0

        for name, fn, enabled in self._checks:
            if not enabled:
                continue
            result = fn()
            check_results.append(result)
            if not result.passed:
                errors.append(result.message)
            # Populate backward-compat fields from well-known check names.
            if name == "services" and hasattr(result, "_service_status"):
                # pylint: disable=protected-access
                service_status = result._service_status  # type: ignore[attr-defined]
            if name == "api_connectivity":
                api_reachable = result.passed
            if name == "disk_space" and hasattr(result, "_disk_space_gb"):
                # pylint: disable=protected-access
                disk_space_gb = result._disk_space_gb  # type: ignore[attr-defined]

        return DevStackHealth(
            all_healthy=len(errors) == 0,
            service_status=service_status,
            api_reachable=api_reachable,
            disk_space_gb=disk_space_gb,
            errors=errors,
            check_results=check_results,
        )


# ---------------------------------------------------------------------------
# Built-in check implementations
# ---------------------------------------------------------------------------

class _ServicesCheckResult(CheckResult):
    """CheckResult subclass that also carries per-service status."""
    def __init__(self, service_status: Dict[str, bool]) -> None:
        failed = [s for s, ok in service_status.items() if not ok]
        passed = len(failed) == 0
        message = (
            f"Services not running: {', '.join(failed)}" if failed else "All services running"
        )
        super().__init__("services", passed, message)
        self._service_status = service_status


class _DiskCheckResult(CheckResult):
    """CheckResult subclass that also carries the raw disk space value."""
    def __init__(self, disk_space_gb: float, passed: bool, min_gb: float) -> None:
        message = (
            f"Insufficient disk space: {disk_space_gb:.1f}GB (need {min_gb}GB)"
            if not passed
            else f"Disk space OK: {disk_space_gb:.1f}GB available"
        )
        super().__init__("disk_space", passed, message)
        self._disk_space_gb = disk_space_gb


def _make_services_check(config: dict) -> Callable[[], CheckResult]:
    def _check() -> CheckResult:
        devstack_config = config.get("devstack", {})
        required_services = devstack_config.get("required_services", [])
        service_status = check_services(required_services)
        return _ServicesCheckResult(service_status)
    return _check


def _make_api_check(config: dict) -> Callable[[], CheckResult]:
    def _check() -> CheckResult:
        devstack_config = config.get("devstack", {})
        openrc_file = Path(
            devstack_config.get("openrc_file", "/opt/stack/devstack/openrc")
        ).expanduser()
        reachable = check_api_connectivity(openrc_file)
        return CheckResult(
            "api_connectivity",
            reachable,
            "OpenStack API reachable" if reachable else "OpenStack API not reachable",
        )
    return _check


def _make_disk_check(config: dict) -> Callable[[], CheckResult]:
    def _check() -> CheckResult:
        devstack_config = config.get("devstack", {})
        devstack_path = Path(devstack_config.get("path", "/opt/stack"))
        min_space_gb = devstack_config.get("min_disk_space_gb", 10)
        disk_space_gb, has_enough = check_disk_space(devstack_path, min_space_gb)
        return _DiskCheckResult(disk_space_gb, has_enough, min_space_gb)
    return _check


# ---------------------------------------------------------------------------
# Public factory and convenience wrapper
# ---------------------------------------------------------------------------

def build_default_checker(config: dict) -> DevStackChecker:
    """
    Build a DevStackChecker pre-loaded with the three built-in checks.

    Checks disabled via ``config["devstack"]["disabled_checks"]`` are registered
    but skipped at run time.  Any check name not in that list is enabled.

    Built-in check names: ``services``, ``api_connectivity``, ``disk_space``.
    """
    disabled = set(config.get("devstack", {}).get("disabled_checks", []))
    checker = DevStackChecker(config)
    checker.register("services", _make_services_check(config), "services" not in disabled)
    checker.register("api_connectivity", _make_api_check(config), "api_connectivity" not in disabled)
    checker.register("disk_space", _make_disk_check(config), "disk_space" not in disabled)
    return checker


def check_devstack_health(config: dict) -> DevStackHealth:
    """
    Run the default set of DevStack health checks.

    Convenience wrapper around ``build_default_checker(config).run()``.
    Agents that need extra checks should call ``build_default_checker`` directly.
    """
    return build_default_checker(config).run()


# ---------------------------------------------------------------------------
# Low-level check helpers (reusable in custom checks)
# ---------------------------------------------------------------------------

def check_services(required_services: List[str]) -> Dict[str, bool]:
    """Return a dict mapping each service name to its running status."""
    service_status = {}
    for service in required_services:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            service_status[service] = (
                result.returncode == 0 and result.stdout.strip() == "active"
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            service_status[service] = False
    return service_status


def check_api_connectivity(openrc_file: Path) -> bool:
    """Return True if the OpenStack API is reachable."""
    if not openrc_file.exists():
        return False
    try:
        cmd = (
            f"source ~/.bashrc 2>/dev/null; source {openrc_file}"
            " && openstack loadbalancer list --format value --column id"
        )
        result = subprocess.run(
            cmd,
            shell=True,
            executable="/bin/bash",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_disk_space(path: Path, min_gb: float = 10.0) -> Tuple[float, bool]:
    """Return (available_gb, has_enough_space)."""
    try:
        stat = shutil.disk_usage(path)
        available_gb = stat.free / (1024 ** 3)
        return (available_gb, available_gb >= min_gb)
    except FileNotFoundError:
        return (0.0, False)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def check_repo_on_main_branch(repo_path: Path) -> BranchCheck:
    """Verify that a repository is on main/master branch."""
    if not repo_path.exists():
        return BranchCheck(
            on_main=False,
            current_branch="",
            repo_path=repo_path,
            error=f"Repository not found: {repo_path}",
        )
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return BranchCheck(
                on_main=False,
                current_branch="",
                repo_path=repo_path,
                error="Failed to get current branch",
            )
        current_branch = result.stdout.strip()
        on_main = current_branch in ("main", "master")
        return BranchCheck(
            on_main=on_main,
            current_branch=current_branch,
            repo_path=repo_path,
            error=None if on_main else f"Not on main branch (on '{current_branch}')",
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return BranchCheck(
            on_main=False,
            current_branch="",
            repo_path=repo_path,
            error=f"Error checking branch: {exc}",
        )


def checkout_main_branch(repo_path: Path) -> Tuple[bool, str]:
    """Checkout main or master branch. Returns (success, message)."""
    try:
        for branch in ("main", "master"):
            result = subprocess.run(
                ["git", "checkout", branch],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                return (True, f"Checked out {branch} branch")
        return (False, f"Failed to checkout main/master: {result.stderr}")
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return (False, f"Error: {exc}")


def git_stash_save(repo_path: Path, message: str = "claude-agents auto-stash") -> bool:
    """Stash local changes. Returns True if a stash entry was created.

    Returns False when the working tree is already clean, on git error, or on
    timeout — never raises.
    """
    try:
        result = subprocess.run(
            ["git", "stash", "push", "-m", message],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0 and "No local changes to save" not in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def git_stash_pop(repo_path: Path) -> Tuple[bool, str]:
    """Restore the most recent stash entry. Returns (success, message). Never raises."""
    try:
        result = subprocess.run(
            ["git", "stash", "pop"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            return (True, "Stash popped successfully")
        return (False, result.stderr.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return (False, str(exc))


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------

def cleanup_test_environment(
    config: Dict,
    cleanup_commands: Optional[List[str]] = None,
) -> Tuple[bool, List[str]]:
    """
    Cleanup test environment (delete test resources, reset state).

    Returns (success, output_lines).
    """
    output: List[str] = []
    devstack_config = config.get("devstack", {})
    openrc_file = Path(
        devstack_config.get("openrc_file", "/opt/stack/devstack/openrc")
    ).expanduser()

    if not openrc_file.exists():
        output.append("⚠️  OpenRC file not found, skipping cleanup")
        return (False, output)

    if cleanup_commands is None:
        cleanup_commands = [
            "openstack loadbalancer list --format value --column id --name test- 2>/dev/null"
            " | xargs -r -n1 openstack loadbalancer delete --cascade",
            "openstack server list --format value --column ID --name test- 2>/dev/null"
            " | xargs -r -n1 openstack server delete",
            "openstack network list --format value --column ID --name test- 2>/dev/null"
            " | xargs -r -n1 openstack network delete",
        ]

    try:
        for cmd in cleanup_commands:
            full_cmd = f"source {openrc_file} && {cmd}"
            result = subprocess.run(
                full_cmd,
                shell=True,
                executable="/bin/bash",
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode == 0:
                output.append(f"✓ Executed: {cmd[:80]}...")
                if result.stdout.strip():
                    output.append(f"  Output: {result.stdout.strip()[:200]}")
            else:
                output.append(f"⚠️  Command failed (continuing): {cmd[:80]}...")
                if result.stderr.strip():
                    output.append(f"  Error: {result.stderr.strip()[:200]}")
        output.append("✓ Cleanup completed")
        return (True, output)
    except subprocess.TimeoutExpired:
        output.append("❌ Cleanup timed out")
        return (False, output)
    except Exception as exc:  # pylint: disable=broad-except
        output.append(f"❌ Cleanup error: {exc}")
        return (False, output)


# ---------------------------------------------------------------------------
# Report formatter
# ---------------------------------------------------------------------------

def format_health_report(health: DevStackHealth) -> str:
    """Format health check results as markdown."""
    lines = ["## DevStack Health Check", ""]

    if health.all_healthy:
        lines.append("✅ **Status:** ALL CHECKS PASSED")
    else:
        lines.append("❌ **Status:** HEALTH CHECK FAILED")

    if health.check_results:
        lines += ["", "### Check Results", ""]
        for cr in health.check_results:
            icon = "✅" if cr.passed else "❌"
            lines.append(f"- **{cr.name}**: {icon} {cr.message}")
    else:
        # Backward-compat display when check_results not populated
        lines += ["", "### Service Status", ""]
        for service, is_running in sorted(health.service_status.items()):
            status = "✅ Running" if is_running else "❌ Not Running"
            lines.append(f"- **{service}**: {status}")

        lines += ["", "### API Connectivity", ""]
        api_status = "✅ Reachable" if health.api_reachable else "❌ Not Reachable"
        lines.append(f"- **OpenStack API**: {api_status}")

        lines += ["", "### Disk Space", ""]
        lines.append(f"- **Available**: {health.disk_space_gb:.1f} GB")

    if health.errors:
        lines += ["", "### Errors", ""]
        for error in health.errors:
            lines.append(f"- ❌ {error}")

    return "\n".join(lines)
