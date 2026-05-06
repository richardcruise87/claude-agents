"""
DevStack health and environment checks shared by all agents.

Provides health checking, branch verification, and cleanup utilities.
"""
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class DevStackHealth:
    """DevStack health check results."""
    all_healthy: bool
    service_status: Dict[str, bool]  # service_name → running
    api_reachable: bool
    disk_space_gb: float
    errors: List[str]


@dataclass
class BranchCheck:
    """Git branch verification results."""
    on_main: bool
    current_branch: str
    repo_path: Path
    error: Optional[str] = None


def check_devstack_health(config: Dict) -> DevStackHealth:
    """
    Comprehensive DevStack health check.

    Args:
        config: Configuration dictionary with devstack settings

    Returns:
        DevStackHealth object with check results
    """
    errors = []
    devstack_config = config.get("devstack", {})

    # Check services
    required_services = devstack_config.get("required_services", [])
    service_status = check_services(required_services)

    for service, is_running in service_status.items():
        if not is_running:
            errors.append(f"Service not running: {service}")

    # Check API connectivity
    openrc_file = Path(devstack_config.get("openrc_file", "/opt/stack/devstack/openrc")).expanduser()
    api_reachable = check_api_connectivity(openrc_file)
    if not api_reachable:
        errors.append("OpenStack API not reachable")

    # Check disk space
    devstack_path = Path(devstack_config.get("path", "/opt/stack"))
    min_space_gb = devstack_config.get("min_disk_space_gb", 10)
    disk_space_gb, has_enough_space = check_disk_space(devstack_path, min_space_gb)
    if not has_enough_space:
        errors.append(f"Insufficient disk space: {disk_space_gb:.1f}GB (need {min_space_gb}GB)")

    all_healthy = len(errors) == 0

    return DevStackHealth(
        all_healthy=all_healthy,
        service_status=service_status,
        api_reachable=api_reachable,
        disk_space_gb=disk_space_gb,
        errors=errors
    )


def check_services(required_services: List[str]) -> Dict[str, bool]:
    """
    Check systemd service status.

    Args:
        required_services: List of systemd service names to check

    Returns:
        Dictionary mapping service name to running status (True/False)
    """
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
            # is-active returns 'active' if running, 0 exit code
            is_running = result.returncode == 0 and result.stdout.strip() == "active"
            service_status[service] = is_running
        except (subprocess.TimeoutExpired, FileNotFoundError):
            service_status[service] = False

    return service_status


def check_api_connectivity(openrc_file: Path) -> bool:
    """
    Test OpenStack API connectivity with simple command.

    Args:
        openrc_file: Path to OpenStack credentials file

    Returns:
        True if API is reachable, False otherwise
    """
    if not openrc_file.exists():
        return False

    try:
        # Try to list load balancers (simple API test)
        cmd = f"source {openrc_file} && openstack loadbalancer list --format value --column id"
        result = subprocess.run(
            cmd,
            shell=True,
            executable="/bin/bash",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        # Success if command exits 0 (even if list is empty)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_disk_space(path: Path, min_gb: float = 10.0) -> Tuple[float, bool]:
    """
    Check available disk space.

    Args:
        path: Path to check (e.g., /opt/stack)
        min_gb: Minimum required space in GB

    Returns:
        Tuple of (available_gb, has_enough_space)
    """
    try:
        stat = shutil.disk_usage(path)
        available_gb = stat.free / (1024 ** 3)  # Convert bytes to GB
        has_enough = available_gb >= min_gb
        return (available_gb, has_enough)
    except FileNotFoundError:
        return (0.0, False)


def check_repo_on_main_branch(repo_path: Path) -> BranchCheck:
    """
    Verify repository is on main/master branch.

    Args:
        repo_path: Path to git repository

    Returns:
        BranchCheck object with verification results
    """
    if not repo_path.exists():
        return BranchCheck(
            on_main=False,
            current_branch="",
            repo_path=repo_path,
            error=f"Repository not found: {repo_path}"
        )

    try:
        # Get current branch name
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
                error="Failed to get current branch"
            )

        current_branch = result.stdout.strip()
        on_main = current_branch in ["main", "master"]

        return BranchCheck(
            on_main=on_main,
            current_branch=current_branch,
            repo_path=repo_path,
            error=None if on_main else f"Not on main branch (on '{current_branch}')"
        )

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return BranchCheck(
            on_main=False,
            current_branch="",
            repo_path=repo_path,
            error=f"Error checking branch: {e}"
        )


def checkout_main_branch(repo_path: Path) -> Tuple[bool, str]:
    """
    Checkout main or master branch.

    Args:
        repo_path: Path to git repository

    Returns:
        Tuple of (success, message)
    """
    try:
        # Try main first
        result = subprocess.run(
            ["git", "checkout", "main"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode == 0:
            return (True, "Checked out main branch")

        # Try master as fallback
        result = subprocess.run(
            ["git", "checkout", "master"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        if result.returncode == 0:
            return (True, "Checked out master branch")

        return (False, f"Failed to checkout main/master: {result.stderr}")

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return (False, f"Error: {e}")


def cleanup_test_environment(config: Dict, cleanup_commands: Optional[List[str]] = None) -> Tuple[bool, List[str]]:
    """
    Cleanup test environment (delete test resources, reset state).

    Args:
        config: Configuration dictionary with devstack settings
        cleanup_commands: Optional list of custom cleanup commands

    Returns:
        Tuple of (success, output_lines)
    """
    output = []
    devstack_config = config.get("devstack", {})
    openrc_file = Path(devstack_config.get("openrc_file", "/opt/stack/devstack/openrc")).expanduser()

    if not openrc_file.exists():
        output.append("⚠️  OpenRC file not found, skipping cleanup")
        return (False, output)

    # Default cleanup commands
    if cleanup_commands is None:
        cleanup_commands = [
            # Delete test load balancers
            "openstack loadbalancer list --format value --column id --name test- 2>/dev/null"
            " | xargs -r -n1 openstack loadbalancer delete --cascade",
            # Delete test servers
            "openstack server list --format value --column ID --name test- 2>/dev/null"
            " | xargs -r -n1 openstack server delete",
            # Delete test networks (if orphaned)
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
    except Exception as e:
        output.append(f"❌ Cleanup error: {e}")
        return (False, output)


def format_health_report(health: DevStackHealth) -> str:
    """
    Format health check results as markdown.

    Args:
        health: DevStackHealth object

    Returns:
        Formatted markdown string
    """
    lines = ["## DevStack Health Check", ""]

    if health.all_healthy:
        lines.append("✅ **Status:** ALL CHECKS PASSED")
    else:
        lines.append("❌ **Status:** HEALTH CHECK FAILED")

    lines.append("")
    lines.append("### Service Status")
    lines.append("")

    for service, is_running in sorted(health.service_status.items()):
        status = "✅ Running" if is_running else "❌ Not Running"
        lines.append(f"- **{service}**: {status}")

    lines.append("")
    lines.append("### API Connectivity")
    lines.append("")
    api_status = "✅ Reachable" if health.api_reachable else "❌ Not Reachable"
    lines.append(f"- **OpenStack API**: {api_status}")

    lines.append("")
    lines.append("### Disk Space")
    lines.append("")
    lines.append(f"- **Available**: {health.disk_space_gb:.1f} GB")

    if health.errors:
        lines.append("")
        lines.append("### Errors")
        lines.append("")
        for error in health.errors:
            lines.append(f"- ❌ {error}")

    return "\n".join(lines)
