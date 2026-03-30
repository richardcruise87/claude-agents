"""
DevStack health check functionality.

Verifies DevStack environment is healthy before attempting bug reproduction.
Checks services, API connectivity, and disk space.
"""
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class DevStackHealth:
    """DevStack health check results."""
    all_healthy: bool
    service_status: Dict[str, bool]  # service_name → running
    api_reachable: bool
    disk_space_gb: float
    errors: List[str]


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
    openrc_file = Path(devstack_config.get("openrc_file", "/opt/stack/devstack/openrc"))
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
                timeout=5
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
            timeout=30
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


if __name__ == "__main__":
    # Test the health check functionality
    import json
    from pathlib import Path

    print("Testing DevStack health check...")
    print("")

    # Load config from sample or use defaults
    config_file = Path(__file__).parent / "config.json"
    sample_config_file = Path(__file__).parent / "config.sample.json"

    if config_file.exists():
        with open(config_file) as f:
            config = json.load(f)
        print(f"✓ Loaded config from {config_file}")
    elif sample_config_file.exists():
        with open(sample_config_file) as f:
            config = json.load(f)
        print(f"✓ Loaded config from {sample_config_file}")
    else:
        # Default config
        config = {
            "devstack": {
                "path": "/opt/stack",
                "openrc_file": "/opt/stack/devstack/openrc",
                "required_services": [
                    "devstack@o-api.service",
                    "devstack@o-cw.service",
                    "devstack@o-hm.service",
                ],
                "min_disk_space_gb": 10
            }
        }
        print("✓ Using default config")

    print("")
    print("Running health checks...")
    print("")

    health = check_devstack_health(config)

    print(format_health_report(health))
    print("")

    if health.all_healthy:
        print("✅ DevStack is healthy and ready for bug reproduction")
    else:
        print("❌ DevStack has issues that need to be resolved")
        print("")
        print("Errors:")
        for error in health.errors:
            print(f"  - {error}")
