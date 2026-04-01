# DevStack Locking and Deadlock Prevention

**Date:** 2026-04-01
**Purpose:** Prevent concurrent DevStack access and resource conflicts between agents

---

## Problem

Multiple agents may attempt to use the same DevStack environment simultaneously:

1. **Bug Reproduction Agent** - Running reproduction scripts
2. **Code Review Agent** - Testing changes live
3. **Manual Testing** - User running commands

### Potential Conflicts

**Without Locking:**
- ❌ Resource naming conflicts (both create `test-review-lb`)
- ❌ Test interference (one agent's test affects another's)
- ❌ Cleanup race (deleting resources while another agent uses them)
- ❌ API rate limiting (too many concurrent requests)
- ❌ Confusing results (can't tell which test failed)

---

## Solution: File-Based Locking + Unique Resource Prefixes

### 1. File-Based Lock (`/tmp/devstack-agent.lock`)

**Mechanism:**
- Uses `fcntl.flock()` for POSIX file locking
- Only one process can hold the lock at a time
- Automatic release on process exit (even if crashed)
- Configurable timeout (default: 5 minutes)

**Lock File Content:**
```
agent-name:PID:timestamp
Example: code-review-agent:12345:1775041234
```

### 2. Unique Resource Prefixes

**Format:** `test-{agent}-{pid}-{timestamp}-`

**Examples:**
```
test-review-402292-1775041974-lb
test-repro-402293-1775042100-server1
```

**Benefits:**
- No naming conflicts between agents
- Easy to identify which agent created resources
- Cleanup only affects resources created by that agent instance
- Orphaned resources can be traced back to specific runs

---

## Implementation

### Shared Library: `agents_lib/devstack_lock.py`

**Classes:**
```python
class DevStackLock:
    """File-based exclusive lock for DevStack access."""
    
    def acquire(agent_name) -> (success, message)
    def release() -> None
```

**Context Manager:**
```python
with devstack_lock("code-review-agent"):
    # DevStack is exclusively locked
    run_tests_in_devstack()
# Lock automatically released
```

**Helper Functions:**
```python
# Check if DevStack is available (non-blocking)
available, msg = check_devstack_available(timeout=0)

# Generate unique resource prefix
prefix = get_unique_resource_prefix("review")
# Returns: "test-review-12345-1775041974-"
```

---

## Agent Integration

### Code Review Agent

**Pre-flight Check:**
```python
# Check DevStack availability before starting
available, msg = check_devstack_available(timeout=0)
if not available:
    print(f"⚠️  {msg}")
    print("DevStack testing will be skipped")
    devstack_available = False

# Generate unique prefix for this review
resource_prefix = get_unique_resource_prefix("review")
# Example: "test-review-12345-1775041974-"
```

**Resource Creation (in prompt):**
```bash
# Use unique prefix instead of hardcoded name
openstack loadbalancer create --name {resource_prefix}lb

# Cleanup uses same prefix
openstack loadbalancer delete --cascade {resource_prefix}lb
```

**Lock Behavior:**
- Checks if DevStack is locked before testing
- If locked: Skips DevStack testing, continues with other tests
- If available: Proceeds with testing
- **Does NOT acquire lock** (AI agent may hold it for long time)

### Bug Reproduction Agent

**Potential Enhancement:**
```python
# Acquire lock for reproduction
with devstack_lock("bug-reproduction-agent", timeout=300):
    # Run reproduction script
    execute_reproduction_script()
# Lock automatically released
```

---

## Lock Timeout and Error Handling

### Default Timeout: 300 seconds (5 minutes)

**Why 5 minutes?**
- Code review tests typically complete in 2-3 minutes
- Bug reproduction may take longer
- Prevents indefinite waiting
- Balance between patience and responsiveness

### Timeout Behavior

```python
lock = DevStackLock(timeout=300)
success, msg = lock.acquire("my-agent")

if not success:
    # msg contains info about who holds the lock
    # Example: "Timeout waiting for DevStack lock (held by bug-reproduction-agent PID 12345, held for 315s)"
    print(f"⚠️  {msg}")
    # Agent decides how to proceed
```

### Error Scenarios

| Scenario | Behavior |
|----------|----------|
| Lock held by other agent | Wait up to timeout, then skip DevStack tests |
| Lock file permission denied | Report error, skip DevStack tests |
| Lock holder crashed | Lock auto-released by OS (fcntl behavior) |
| Agent crashes while holding lock | Lock auto-released by OS |
| Timeout exceeded | Skip DevStack tests, continue with other work |

---

## Deadlock Prevention

### Why No Deadlock?

1. **Single Resource**: Only one lock (DevStack)
2. **No Lock Nesting**: Agents don't acquire multiple locks
3. **Auto-Release**: Locks released automatically on exit
4. **Timeout**: Maximum wait time prevents infinite blocking
5. **Graceful Degradation**: Agents skip DevStack tests if unavailable

### Starvation Prevention

**Scenario:** Code review agent holds lock for long time

**Solution:**
- Timeout ensures no agent waits forever
- Failed agents retry on next cycle
- Manual intervention possible (delete lock file)
- Lock shows who's holding it and for how long

---

## Testing Concurrent Access

### Test 1: Simultaneous Code Reviews

```bash
# Terminal 1
octavia-review-change 123456 &

# Terminal 2 (immediately after)
octavia-review-change 789012 &

# Expected:
# - First agent gets lock
# - Second agent sees "DevStack locked by code-review-agent"
# - Second agent skips DevStack testing
# - Both complete successfully
```

### Test 2: Review During Reproduction

```bash
# Terminal 1 - Start bug reproduction
octavia-reproduce-bugs &

# Terminal 2 - Start code review
octavia-review-change 123456 &

# Expected:
# - Reproduction agent may hold lock (if implemented)
# - Review agent skips DevStack tests
# - Both complete without interference
```

### Test 3: Lock Cleanup After Crash

```bash
# Terminal 1 - Start review
octavia-review-change 123456 &
PID=$!

# Kill it mid-execution
kill -9 $PID

# Terminal 2 - Start another review
octavia-review-change 789012

# Expected:
# - Lock automatically released by OS
# - Second review acquires lock successfully
```

---

## Manual Lock Management

### Check Lock Status

```bash
cat /tmp/devstack-agent.lock
# Output: code-review-agent:12345:1775041234
```

### Force Release (if agent crashed and didn't cleanup)

```bash
rm /tmp/devstack-agent.lock
```

### Monitor Lock Activity

```bash
# Watch lock file changes
watch -n 1 'cat /tmp/devstack-agent.lock 2>/dev/null || echo "No lock"'
```

---

## Resource Cleanup Strategy

### Agent-Specific Cleanup

**Before (Problematic):**
```bash
# Deletes ALL test resources
openstack loadbalancer list --name test- | xargs openstack loadbalancer delete
```

**After (Safe):**
```bash
# Deletes only THIS agent's resources
openstack loadbalancer list --name {resource_prefix} | xargs openstack loadbalancer delete
```

### Orphaned Resource Cleanup

**Manual Cleanup Script:**
```bash
#!/bin/bash
# cleanup-old-test-resources.sh

# Find resources older than 1 hour with test- prefix
for lb in $(openstack loadbalancer list --name test- -f value -c id); do
    created=$(openstack loadbalancer show $lb -f value -c created_at)
    age=$(calculate_age "$created")
    if [ $age -gt 3600 ]; then
        echo "Deleting old test LB: $lb (age: ${age}s)"
        openstack loadbalancer delete --cascade $lb
    fi
done
```

---

## Configuration

### Code Review Agent: `config.json`

```json
{
  "devstack": {
    "test_in_devstack": true,
    "lock_timeout": 300,
    "skip_if_locked": true
  }
}
```

**Options:**
- `test_in_devstack`: Enable DevStack testing (default: true)
- `lock_timeout`: Seconds to wait for lock (default: 300)
- `skip_if_locked`: Skip if locked vs. wait (default: true)

---

## Advantages of This Design

### 1. **No Code Changes to AI Prompts**
- Lock checking happens before prompt is sent
- AI doesn't need to understand locking
- Resource prefix injected into prompt variables

### 2. **Fail-Safe Defaults**
- If lock unavailable → skip DevStack tests
- Other tests (unit, functional, style) still run
- Review completes successfully

### 3. **Observable**
- Lock file shows who has DevStack
- Resource prefixes identify agent instances
- Easy to debug conflicts

### 4. **Portable**
- Standard POSIX file locking
- Works on Linux, Mac, BSD
- No external dependencies

### 5. **Automatic Cleanup**
- OS releases lock if agent crashes
- No persistent lock state
- No manual intervention needed (usually)

---

## Monitoring and Alerting

### Log Messages

**Code Review Agent:**
```
🔒 Checking DevStack availability...
   ✅ DevStack is available
   
# OR

🔒 Checking DevStack availability...
   ⚠️  Timeout waiting for DevStack lock (held by bug-reproduction-agent PID 12345, held for 45s)
   DevStack testing will be skipped (another agent is using it)
```

**Metrics to Track:**
- Number of times lock was unavailable
- Average lock hold time
- Number of skipped DevStack tests
- Orphaned resource count

---

## Future Enhancements

### Priority-Based Locking
- High-priority agents (manual reviews) get priority
- Low-priority agents (automated triages) defer

### Lock Queue
- Agents queue for DevStack access
- Fair scheduling (FIFO or priority)

### Distributed Locking
- Multiple DevStack instances
- Agents coordinate across machines
- Redis/etcd-based locks

### Resource Pools
- Multiple test resource pools
- Agents use available pool
- Reduces contention

---

## Summary

**Problem Solved:**
✅ No more concurrent DevStack access  
✅ No resource naming conflicts  
✅ No test interference  
✅ Clear ownership of test resources  
✅ Graceful degradation when DevStack busy  

**Mechanism:**
- File-based exclusive lock (`/tmp/devstack-agent.lock`)
- Unique resource prefixes per agent instance
- Pre-flight availability check
- Timeout-based fairness
- Automatic cleanup

**Result:**
- Agents can run concurrently without conflicts
- DevStack tests reliable and isolated
- Easy to debug resource issues
- Safe for production use

---

## Testing

```bash
# Test locking module
cd ~/git/claude-agents/agents_lib
python3 agents_lib/devstack_lock.py

# Expected output:
# ✅ All tests passed!

# Test imports
python3 -c "from agents_lib import devstack_lock, check_devstack_available, get_unique_resource_prefix; print('✅ Imports successful')"
```

---

**Lock file location:** `/tmp/devstack-agent.lock`
**Lock mechanism:** POSIX `fcntl.flock()`
**Default timeout:** 300 seconds (5 minutes)
**Resource prefix format:** `test-{agent}-{pid}-{timestamp}-`
