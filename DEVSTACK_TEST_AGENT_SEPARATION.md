# DevStack Test Agent Separation

**Date:** 2026-04-01
**Purpose:** Separate DevStack integration testing into dedicated agent for improved throughput

---

## Problem

Original design had code-review-agent performing DevStack integration testing inline:
- ❌ Reviews blocked while waiting for DevStack lock
- ❌ Long review times (tests can take 10+ minutes)
- ❌ Low throughput (can't review multiple changes concurrently)
- ❌ Complex agent doing too many things

---

## Solution: Separate DevStack Test Agent

Similar to bug-triage-agent → bug-reproduction-agent workflow:

```
Code Review Agent                 DevStack Test Agent
      ↓                                   ↓
Generates review                    Watches reviews directory
(fast: 2-3 minutes)                 Picks up new reviews
      ↓                                   ↓
Saves review file              Acquires DevStack lock
~/octavia_reviews/                  Tests change live
      ↓                                   ↓
Done! (can review next)            Updates review file
                                   Adds test results
                                        ↓
                                   Done! (releases lock)
```

---

## New Architecture

### Code Review Agent (`code-review-agent/`)

**Responsibilities:**
- Fetch change from Gerrit
- Analyze code changes
- Run unit tests (`tox -e py3`)
- Run functional tests (`tox -e functional`)
- Run code quality checks (`tox -e pep8`)
- Generate code review document
- Save to `~/octavia_reviews/`

**Does NOT:**
- ❌ Check DevStack health
- ❌ Acquire DevStack lock
- ❌ Test changes in DevStack
- ❌ Wait for DevStack availability

**Throughput:** Can review multiple changes concurrently!

### DevStack Test Agent (`devstack-test-agent/`)

**Responsibilities:**
- Watch `~/octavia_reviews/` for new reviews
- Parse review files to extract change info
- Acquire DevStack lock (exclusive access)
- Fetch and deploy change to DevStack
- Restart Octavia services
- Execute integration tests
- Generate test results
- Update original review file with test section
- Release DevStack lock

**Tracking:** `~/.octavia_devstack_tests.json`

---

## Workflow Example

### Step 1: Code Review (Fast - 2-3 minutes)

```bash
$ octavia-review-change 982615

🔍 Running pre-flight checks...
📋 Checking repository branch...
   ✅ On main branch

🤖 Starting comprehensive code review...

## Step 4: Run Unit Tests
✅ Unit tests passed

## Step 5: Run Functional Tests
✅ Functional tests passed

## Step 6: Code Quality Checks
✅ PEP8 checks passed

✅ Review Complete!
📄 Review saved to: review_openstack_octavia_982615_ps1_20260401_143000.md
```

Review file created immediately - no waiting for DevStack!

### Step 2: DevStack Testing (Async - 10-15 minutes)

```bash
$ octavia-devstack-test

DevStack Test Agent
================================================================================

🏥 Checking DevStack health...
   ✅ DevStack is healthy

📋 Found 5 review files

📌 Testing openstack/octavia #982615 PS1

🔒 Acquiring DevStack lock (timeout: 300s)...
   ✅ DevStack lock acquired

🤖 Starting DevStack integration testing...

## Step 2: Fetch and Checkout the Change
✅ Fetched change from Gerrit

## Step 3: Restart Affected Services
✅ Services restarted

## Step 5: Execute DevStack Integration Tests
✅ Load balancer created
✅ Tests passed

## Step 8: Cleanup Test Resources
✅ All test resources deleted

✅ Testing Complete!

📝 Updating review file with test results...
   ✅ Updated: review_openstack_octavia_982615_ps1_20260401_143000.md

✅ Test complete for openstack/octavia #982615
```

Original review file updated with DevStack test results!

---

## Files Created

### New Agent: `devstack-test-agent/`

```
devstack-test-agent/
├── setup.py                          # Package installation
├── config.sample.json                # Configuration template
├── config.py                         # Configuration loader
├── review_parser.py                  # Parse review files
├── devstack_test_agent.py           # Main agent
├── prompts/
│   └── devstack_test_prompt.txt     # Test execution prompt
└── README.md                         # Documentation
```

**Command:** `octavia-devstack-test`

### Modified Files

**Code Review Agent:**
- `review_single_change.py` - Removed DevStack checking/locking
- `prompts/__init__.py` - Removed resource_prefix parameter
- `prompts/code_review_prompt.txt` - Removed DevStack testing step

---

## Benefits

### 1. **Improved Throughput**

**Before:**
```
Review 1: [Code analysis 3min] → [Wait for DevStack 0-5min] → [DevStack test 10min] = 13-18min
Review 2: Must wait for Review 1 to complete
Total: 26-36 minutes for 2 reviews
```

**After:**
```
Review 1: [Code analysis 3min] → Done!
Review 2: [Code analysis 3min] → Done! (parallel)
Review 3: [Code analysis 3min] → Done! (parallel)

DevStack Agent (parallel):
  Test Review 1: [10min]
  Test Review 2: [10min]  (after Review 1)
  Test Review 3: [10min]  (after Review 2)

Total: 6 minutes for 3 reviews! (then tests run async)
```

### 2. **Cleaner Separation of Concerns**

- Code review agent: Fast code analysis
- DevStack test agent: Slow integration testing
- Each does one thing well

### 3. **Better Resource Utilization**

- Code reviews can happen anytime
- DevStack testing serialized (one at a time)
- No blocking on DevStack availability

### 4. **Easier Debugging**

- Review failures vs. DevStack test failures clearly separated
- Can re-run DevStack tests without re-reviewing
- Logs are cleaner and more focused

### 5. **Flexible Deployment**

- Can run code review agent frequently (every 30min)
- Can run DevStack test agent less frequently (every 2 hours)
- Can disable DevStack testing without affecting reviews

---

## Configuration

### Code Review Agent: `config.json`

```json
{
  "devstack": {
    "path": "/opt/stack",
    "verify_main_branch": true
  }
}
```

**Removed:**
- `test_in_devstack` - No longer relevant
- `lock_timeout` - No longer checks lock
- `cleanup_on_failure` - No longer tests

### DevStack Test Agent: `config.json`

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

---

## Tracking

### Code Review Agent
**Tracking File:** `~/.octavia_reviewed_changes.json`

Tracks:
- Change reviewed
- Patchset reviewed
- Timestamp

### DevStack Test Agent
**Tracking File:** `~/.octavia_devstack_tests.json`

Tracks:
- Review file tested
- Test timestamp
- Test result (success/failure)

**Format:**
```json
{
  "openstack/octavia~982615~ps1": {
    "tested_at": "2026-04-01T14:30:00",
    "review_file": "~/octavia_reviews/review_openstack_octavia_982615_ps1_20260401_143000.md",
    "test_result": "success"
  }
}
```

---

## Automation

### systemd Timer Setup

**Code Review Agent:**
```bash
# Run every 30 minutes
OnCalendar=*:0/30
```

**DevStack Test Agent:**
```bash
# Run every 2 hours
OnCalendar=00/2:00:00
```

**Or Event-Driven:**
```bash
# Path unit watches ~/octavia_reviews/
PathChanged=%h/octavia_reviews
```

---

## Migration from Old Design

### What Changed

**Old workflow:**
1. Review agent checks DevStack health
2. Review agent acquires DevStack lock
3. Review agent tests in DevStack
4. Review agent releases lock
5. Review completes

**New workflow:**
1. Review agent analyzes code (no DevStack)
2. Review completes immediately
3. DevStack test agent picks up review
4. DevStack test agent acquires lock
5. DevStack test agent tests change
6. DevStack test agent updates review

### Breaking Changes

None! Old review files work fine. DevStack test agent simply adds a new section.

### Backwards Compatibility

- Existing reviews: Can be tested by DevStack test agent
- Old config: Works (new options are optional)
- Tracking files: Independent (no conflicts)

---

## Testing

### Test Code Review Agent

```bash
cd ~/git/claude-agents/code-review-agent
octavia-review-change 982615

# Should complete in 2-3 minutes
# Should NOT check DevStack or acquire lock
```

### Test DevStack Test Agent

```bash
cd ~/git/claude-agents/devstack-test-agent
cp config.sample.json config.json
vim config.json  # Configure paths

# Install
pip install -e .

# Run
octavia-devstack-test

# Should:
# - Find review files
# - Acquire DevStack lock
# - Test changes
# - Update review files
```

### Test Full Workflow

```bash
# Terminal 1: Review a change
octavia-review-change 982615
# Completes quickly

# Terminal 2: Test in DevStack
octavia-devstack-test
# Picks up review and tests it

# Check review file
cat ~/octavia_reviews/review_openstack_octavia_982615_ps1_*.md
# Should have DevStack Integration Testing section at end
```

---

## Performance Comparison

### Before (Integrated Design)

| Metric | Value |
|--------|-------|
| Review time (with DevStack) | 13-18 minutes |
| Reviews per hour | 3-4 |
| Concurrent reviews | 1 |
| DevStack lock contention | High |

### After (Separated Design)

| Metric | Value |
|--------|-------|
| Review time (code only) | 2-3 minutes |
| Reviews per hour | 20+ |
| Concurrent reviews | Unlimited |
| DevStack lock contention | Low (serialized testing) |

**Improvement:** 5-6x faster review throughput!

---

## Future Enhancements

Potential improvements:
- Parallel DevStack testing (multiple DevStack instances)
- Priority queue (urgent reviews tested first)
- Test result caching (don't retest same code)
- Incremental testing (only test affected components)
- Test result notifications (Slack/email)

---

## Summary

**Key Changes:**
1. ✅ Created separate `devstack-test-agent/`
2. ✅ Removed DevStack logic from code-review-agent
3. ✅ Updated prompts and configuration
4. ✅ Added review file parsing
5. ✅ Added review file updating

**Benefits:**
- 5-6x faster review throughput
- Cleaner separation of concerns
- Better resource utilization
- More flexible deployment

**No Breaking Changes:**
- Existing reviews still work
- Tracking files independent
- Gradual migration possible

---

**Workflow:**
```
Code Review Agent  →  Review File  →  DevStack Test Agent  →  Updated Review
   (2-3 min)       (~/octavia_reviews/)     (10-15 min)          (+ test results)
```

Simple, fast, scalable!
