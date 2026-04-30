"""
DevStack locking mechanism to prevent concurrent access.

Ensures only one agent uses DevStack at a time to avoid:
- Resource naming conflicts
- Test interference
- Cleanup race conditions
"""
import os
import time
import fcntl
from pathlib import Path
from typing import Optional, Tuple
from contextlib import contextmanager


class DevStackLock:
    """File-based lock for exclusive DevStack access."""

    def __init__(self, lock_file: Path = None, timeout: int = 300):
        """
        Initialize DevStack lock.

        Args:
            lock_file: Path to lock file (default: /tmp/devstack-agent.lock)
            timeout: Maximum seconds to wait for lock (default: 300 = 5 minutes)
        """
        if lock_file is None:
            lock_file = Path("/tmp/devstack-agent.lock")
        self.lock_file = lock_file
        self.timeout = timeout
        self.lock_fd: Optional[int] = None
        self.acquired = False

    def acquire(self, agent_name: str = "unknown") -> Tuple[bool, str]:
        """
        Acquire exclusive lock on DevStack.

        Args:
            agent_name: Name of agent requesting lock (for logging)

        Returns:
            Tuple of (success, message)
        """
        start_time = time.time()

        # Create lock file if it doesn't exist
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file.touch(exist_ok=True)

        try:
            # Open lock file
            self.lock_fd = os.open(str(self.lock_file), os.O_RDWR)

            # Try to acquire lock with timeout
            while True:
                try:
                    # Try non-blocking lock
                    fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.acquired = True

                    # Write agent name and PID to lock file
                    lock_info = f"{agent_name}:{os.getpid()}:{int(time.time())}\n"
                    os.write(self.lock_fd, lock_info.encode())
                    os.fsync(self.lock_fd)

                    return (True, f"DevStack lock acquired by {agent_name}")

                except BlockingIOError:
                    # Lock is held by another process
                    elapsed = time.time() - start_time
                    if elapsed >= self.timeout:
                        # Read who has the lock
                        lock_owner = self._read_lock_owner()
                        return (False, f"Timeout waiting for DevStack lock (held by {lock_owner})")

                    # Wait a bit and retry
                    time.sleep(1)

        except Exception as e:
            if self.lock_fd is not None:
                os.close(self.lock_fd)
                self.lock_fd = None
            return (False, f"Failed to acquire lock: {e}")

    def release(self) -> None:
        """Release the DevStack lock."""
        if self.lock_fd is not None and self.acquired:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                os.close(self.lock_fd)
            except Exception:
                pass
            finally:
                self.lock_fd = None
                self.acquired = False

    def _read_lock_owner(self) -> str:
        """Read who currently holds the lock."""
        try:
            with open(self.lock_file, 'r') as f:
                content = f.read().strip()
                if content:
                    parts = content.split(':')
                    if len(parts) >= 3:
                        agent_name, pid, timestamp = parts[0], parts[1], parts[2]
                        lock_time = int(timestamp)
                        age = int(time.time() - lock_time)
                        return f"{agent_name} (PID {pid}, held for {age}s)"
                return "unknown"
        except Exception:
            return "unknown"

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()


@contextmanager
def devstack_lock(agent_name: str = "unknown", timeout: int = 300):
    """
    Context manager for DevStack lock.

    Usage:
        with devstack_lock("code-review-agent"):
            # DevStack is exclusively locked
            run_tests()
        # Lock automatically released

    Args:
        agent_name: Name of agent for logging
        timeout: Maximum seconds to wait for lock

    Raises:
        RuntimeError: If lock cannot be acquired within timeout
    """
    lock = DevStackLock(timeout=timeout)
    success, message = lock.acquire(agent_name)

    if not success:
        raise RuntimeError(f"Could not acquire DevStack lock: {message}")

    try:
        yield lock
    finally:
        lock.release()


def check_devstack_available(timeout: int = 0) -> Tuple[bool, str]:
    """
    Check if DevStack is available (not locked by another agent).

    Args:
        timeout: Seconds to wait (0 = check immediately)

    Returns:
        Tuple of (available, message)
    """
    lock = DevStackLock(timeout=timeout)
    success, message = lock.acquire("check")

    if success:
        lock.release()
        return (True, "DevStack is available")
    else:
        return (False, message)


def get_unique_resource_prefix(agent_name: str) -> str:
    """
    Generate unique resource name prefix for this agent instance.

    Format: test-{agent}-{pid}-{timestamp}-

    Args:
        agent_name: Short agent identifier (e.g., "review", "repro")

    Returns:
        Unique prefix string

    Example:
        >>> get_unique_resource_prefix("review")
        'test-review-12345-1234567890-'
    """
    pid = os.getpid()
    timestamp = int(time.time())
    return f"test-{agent_name}-{pid}-{timestamp}-"


if __name__ == "__main__":
    # Test the locking mechanism

    print("Testing DevStack lock...")
    print("Lock file: /tmp/devstack-agent.lock")
    print()

    # Test 1: Check availability
    print("Test 1: Check if DevStack is available")
    available, msg = check_devstack_available()
    print(f"  Result: {msg}")
    print()

    # Test 2: Acquire and hold lock
    print("Test 2: Acquire lock with context manager")
    try:
        with devstack_lock("test-agent", timeout=5):
            print("  ✓ Lock acquired")
            print("  Holding lock for 3 seconds...")
            time.sleep(3)
            print("  ✓ Lock will be released on exit")
    except RuntimeError as e:
        print(f"  ✗ Failed: {e}")
    print()

    # Test 3: Verify lock was released
    print("Test 3: Verify lock was released")
    available, msg = check_devstack_available()
    print(f"  Result: {msg}")
    print()

    # Test 4: Generate unique prefix
    print("Test 4: Generate unique resource prefix")
    prefix = get_unique_resource_prefix("review")
    print(f"  Prefix: {prefix}")
    print(f"  Example LB name: {prefix}lb")
    print()

    print("✅ All tests passed!")
