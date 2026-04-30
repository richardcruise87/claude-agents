# DevStack Test Agent

An AI-powered agent that performs DevStack integration testing for OpenStack code reviews.

## Overview

This agent works in conjunction with the code-review-agent to provide comprehensive testing:

1. **Code Review Agent** - Analyzes code, runs unit/functional tests, generates review (2-3 minutes)
2. **DevStack Test Agent** - Tests changes in live DevStack, updates review with results (10-15 minutes)

This separation improves throughput by **5-6x** - code reviews complete quickly without waiting for DevStack availability.

## Features

- ✅ Event-driven (watches for new review files)
- ✅ DevStack exclusive locking (prevents conflicts)
- ✅ Unique resource prefixes (prevents naming collisions)
- ✅ Updates original review files with test results
- ✅ Comprehensive test execution and cleanup
- ✅ Configurable repository filtering

## Installation

### Using setup-agents.sh (recommended)

Run from the repository root:

```bash
cd ~/git/claude-agents
./setup-agents.sh devstack-test             # install this agent only
./setup-agents.sh --systemd devstack-test   # also install systemd path watcher
./setup-agents.sh --update devstack-test    # update to latest version
```

### Standalone

Run directly from the agent directory:

```bash
cd ~/git/claude-agents/devstack-test-agent
./install.sh               # install package, prompt for systemd
./install.sh --systemd     # install package + systemd path watcher
./install.sh --no-systemd  # install package only
```

This installs the `octavia-devstack-test` command into `~/.venv/claude-agents`.

### Configure

```bash
cp config.sample.json config.json
vim config.json
```

## Configuration

Edit `config.json`:

```json
{
  "reviews_directory": "~/octavia_reviews",
  "devstack": {
    "path": "/opt/stack",
    "openrc_file": "~/git/devstack/openrc",
    "lock_timeout": 300
  },
  "testing": {
    "test_timeout": 600,
    "cleanup_on_failure": true
  },
  "filters": {
    "only_test_repositories": ["openstack/octavia"]
  }
}
```

**Key Settings:**
- `reviews_directory` - Where to find code reviews
- `lock_timeout` - Seconds to wait for DevStack lock
- `only_test_repositories` - Filter which repos to test (empty = test all)

## Usage

### Manual Execution

```bash
octavia-devstack-test
```

### Automated with systemd

The agent is designed to run automatically via systemd path watcher:

```bash
# Enable path watcher (watches ~/octavia_reviews/)
systemctl --user enable octavia-devstack-test.path
systemctl --user start octavia-devstack-test.path

# Check status
systemctl --user status octavia-devstack-test.path

# View logs
journalctl --user -u octavia-devstack-test.service -f
```

**How it works:**
1. Code review agent creates review file in `~/octavia_reviews/`
2. systemd path watcher detects new file (inotify)
3. Service triggered automatically
4. Agent tests change in DevStack
5. Updates review file with test results

## Workflow

### For Each Review

1. **Parse Review File**
   - Extract repository, change number, patchset
   - Determine if testing needed (based on filters)

2. **Pre-flight Checks**
   - DevStack health (services, API, disk space)
   - Repository on main/master branch

3. **Acquire DevStack Lock**
   - Exclusive access prevents conflicts
   - Timeout if another agent is testing
   - Unique resource prefix: `test-devstack-{pid}-{timestamp}-`

4. **Fetch and Test Change**
   - Fetch change from Gerrit
   - Checkout in DevStack
   - Restart affected services
   - Execute integration tests

5. **Update Review File**
   - Insert DevStack test results section
   - Add to original review (non-destructive)

6. **Cleanup**
   - Delete test resources
   - Release DevStack lock
   - Return to main branch

## Output Format

Updates review files with:

```markdown
## DevStack Integration Testing

**Status**: ✅ PASS / ❌ FAIL / ⏭️ SKIPPED

**Test Details:**
- Load balancer creation: ✅ PASS
- Service health: ✅ PASS
- Cleanup: ✅ PASS

**Errors:** (if any)
```

## Tracking

Tracking file: `~/.octavia_devstack_tests.json`

```json
{
  "openstack/octavia~982615~ps1": {
    "tested_at": "2026-04-01T14:30:00",
    "test_result": "success",
    "review_file": "~/octavia_reviews/review_openstack_octavia_982615_ps1_20260401_143000.md"
  }
}
```

**Prevents:**
- Re-testing same patchset
- Testing changes that are already merged
- Testing repositories not in filter list

## DevStack Locking

Uses file-based locking (`/tmp/devstack-agent.lock`) with:

- **POSIX fcntl.flock()** - Automatic release on crash
- **Timeout** - Maximum wait time (default: 300s)
- **Unique prefixes** - No resource naming conflicts
- **Observable** - Lock file shows who has DevStack

See `DEVSTACK_LOCKING.md` in repository root for details.

## Troubleshooting

### "DevStack locked by another agent"

Another agent is using DevStack. Wait for it to complete or increase `lock_timeout`.

### "Review file not found"

Check `reviews_directory` path and ensure code review agent is running.

### "DevStack unhealthy"

Check DevStack services:
```bash
sudo systemctl status devstack@o-api devstack@o-cw devstack@o-hm
```

### "Repository not on main branch"

Agent will auto-checkout main/master. If this fails, manually checkout main.

## Environment Variables

Override config via environment:

```bash
export REVIEWS_DIRECTORY=~/my_reviews
export DEVSTACK_PATH=/opt/stack
export LOCK_TIMEOUT=600
export TEST_TIMEOUT=900
```

## See Also

- **DEVSTACK_TEST_AGENT_SEPARATION.md** - Architecture and design
- **DEVSTACK_LOCKING.md** - Locking mechanism details
- **DEVSTACK_CHECKS_AND_TESTING.md** - Health checks and testing

## Performance

**Review Throughput Improvement:**
- Before (integrated): 13-18 minutes per review (serialized)
- After (separated): 2-3 minutes per review (parallel)
- **Improvement:** 5-6x faster

Code reviews complete immediately without waiting for DevStack. Testing happens asynchronously.
