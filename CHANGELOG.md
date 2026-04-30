# Changelog

All notable changes to the claude-agents project are documented here.

---

## 2026-04-30

### Added: CI Failure Analysis Agent (`ci-failure-agent/`)

New agent that monitors Zuul CI for failures across configured OpenStack
repositories and uses AI to explain each failure and recommend action.

**Features:**
- Queries Zuul REST API for recent failures, grouped by change+patchset
- AI fetches job logs, analyses root cause, and classifies each failure as
  `CODE_ISSUE`, `ENVIRONMENTAL`, `UNRELATED`, or `INFRA_FAILURE`
- Report includes: Gerrit link, Zuul pipeline link, per-job log excerpts,
  overall recommendation (re-run vs code fix), and token cost
- Re-analysis triggered automatically when new failures appear after last run
- `--print-prompt` flag outputs the formatted prompt for use with any AI tool

**Manual mode (run immediately on a specific failure):**
```bash
octavia-ci-agent --change 985404          # latest patchset for a Gerrit change
octavia-ci-agent --change 985404 --pipeline check
octavia-ci-agent --build <zuul-uuid>      # single Zuul build by UUID
```

**Monitoring mode (automated / systemd timer):**
```bash
octavia-ci-agent                          # all configured repos
octavia-ci-agent --list-failures          # preview without analysis
```

**Commands:** `octavia-ci-agent`, `octavia-analyze-ci`  
**Output:** `~/octavia_ci_failures/`  
**Tracking:** `~/.octavia_ci_failures.json`  
**Systemd:** `octavia-ci-failure.timer` (every 4 hours)

**Bug fixed during development:** Zuul API returns `patchset`, `project`,
`change`, and `ref_url` nested inside a `ref` sub-object rather than at the
top level. Added `normalize_build()` in `zuul_client.py` to flatten these
fields consistently.

---

## 2026-04-02

### Added: Branch Filtering for Code Review Agent

Branch filtering lets the code review agent skip changes on unwanted branches.
Supports include/exclude lists with wildcard (`*`) matching.

**Config example** (only review master/main):
```json
{ "filters": { "exclude_branches": [], "include_branches": ["master", "main"] } }
```

**Logic:** Exclude list is processed first, then include overrides. This
enables "exclude all except X" patterns:
```json
{ "exclude_branches": ["*"], "include_branches": ["master", "stable/*"] }
```

**Files:** `octavia_review_agent.py`, `config.sample.json`  
**Commit:** `d55a0e7`

---

### Added: Token Usage & Cost Tracking

All agents now append a `## Token Usage & Cost` section to every output report,
showing token counts (input, output, cache creation, cache read), total cost
in USD, model used, and duration.

**New shared function:** `agents_lib.format_usage_info(usage_data, cost_usd, model, duration_ms)`

**Data source:** `ResultMessage` attributes from the Claude Agent SDK:
`message.usage`, `message.total_cost_usd`, `message.model`, `message.duration_ms`

The bug reproduction agent additionally tracks usage per attempt and shows a
cumulative total across all attempts.

**Files:** `agents_lib/utils.py`, `agents_lib/__init__.py`, all three agent
main scripts and prompt templates  
**Commit:** `f8caea7`

---

### Added: Configurable Model Setting

Model can now be set in `config.json` or via the `CLAUDE_MODEL` environment
variable. Default is `claude-sonnet-4-6`.

```json
{ "model": "claude-sonnet-4-6" }
```

Systemd service files also pass `CLAUDE_MODEL=claude-sonnet-4-6`.

**Commit:** `c15df57`

---

### Added: One-Shot Update Script

`update-agents.sh` updates all agents, the shared library, and systemd
services in one command. Handles pip reinstall and daemon reload.

**Commit:** `5a24674`

---

## 2026-04-01

### Added: DevStack Test Agent (`devstack-test-agent/`)

Separated DevStack integration testing out of the code review agent into a
dedicated agent. This removes the blocking DevStack wait from code reviews,
improving throughput from ~3 reviews/hour to 20+.

**Workflow:**
```
Code Review Agent  (2–3 min)  →  review file saved  →  DevStack Test Agent  (10–15 min)  →  review updated
```

The DevStack test agent:
- Watches `~/octavia_reviews/` for new review files
- Acquires the DevStack lock before testing
- Deploys the change to DevStack, runs integration tests
- Appends a `DevStack Integration Tests` section to the review file

**Command:** `octavia-devstack-test`  
**Tracking:** `~/.octavia_devstack_tests.json`  
**Commits:** `12e9bd8`, `3e2dbb4`

---

### Added: DevStack Locking (`agents_lib/devstack_lock.py`)

File-based exclusive lock (`/tmp/devstack-agent.lock`) using POSIX
`fcntl.flock()` prevents concurrent DevStack access between agents.

**Features:**
- Automatic lock release on process exit (even on crash)
- Configurable timeout (default: 300 s); agents skip DevStack tests if timeout exceeded
- Unique resource prefix per agent instance: `test-{agent}-{pid}-{timestamp}-`
  avoids naming conflicts and enables precise cleanup

**Usage:**
```python
with devstack_lock("code-review-agent"):
    run_tests_in_devstack()
```

**Exported:** `check_devstack_available()`, `get_unique_resource_prefix()`

---

### Added: DevStack Health Checks & Branch Verification (`agents_lib/devstack_checks.py`)

New shared module providing pre-flight checks run before any DevStack operation:

- `check_devstack_health()` — verifies required systemd services are active,
  OpenStack API is reachable, and disk space meets minimum threshold
- `check_repo_on_main_branch(repo_path)` — confirms a repo is on main/master
- `checkout_main_branch(repo_path)` — auto-checkouts main if not already there
- `cleanup_test_environment(prefix)` — deletes test resources created by agents

Both the code review agent and bug reproduction agent run these checks before
starting work. Unhealthy DevStack → agent aborts or degrades gracefully.

**Commit:** `439654c`

---

### Changed: Functional Tests Always Enabled

The code review agent's prompt previously skipped functional tests assuming
they required DevStack. Functional tests run without DevStack and are now
always attempted. The status in review documents changed from `⏭️ SKIPPED`
to `⚠️ NOT AVAILABLE` for repos that genuinely lack a functional tox environment.

---

## 2026-03-30

### Added: Bug Reproduction Agent (`bug-reproduction-agent/`)

Watches for new bug triage reports and attempts to reproduce bugs in a live
DevStack environment.

**Workflow:**
1. systemd path unit detects new triage report via inotify
2. Parses the triage markdown to extract reproduction steps
3. Runs DevStack health check; aborts if unhealthy
4. AI generates a reproduction script (bash, with `set -euo pipefail`)
5. Executes script with timeout; on failure the AI refines and retries (up to 3 attempts)
6. Generates a markdown report: `REPRODUCED` / `NOT_REPRODUCED` / `ENVIRONMENT_ERROR` / `SCRIPT_ERROR` / `TIMEOUT`

**Command:** `octavia-reproduce-bugs`  
**Output:** `~/octavia_bug_reproductions/`  
**Tracking:** `~/.octavia_bug_reproductions.json`  
**Systemd:** `octavia-bug-reproduction.path` (inotify-triggered)

---

### Added: Shared Library (`agents_lib/`)

Common utilities extracted from individual agents into an installable package,
eliminating ~170 lines of duplicated code:

| Module | Key exports |
|--------|------------|
| `config_loader.py` | `load_agent_config()`, `apply_cutoff_date()`, `expand_config_paths()` |
| `tracking.py` | `should_process_item()`, `record_processed_item()`, `create_output_filename()` |
| `utils.py` | `expand_path()`, `slugify()`, `format_usage_info()` |
| `prompt_loader.py` | `load_prompt_template()` |
| `devstack_checks.py` | `check_devstack_health()`, `check_repo_on_main_branch()` |
| `devstack_lock.py` | `DevStackLock`, `check_devstack_available()`, `get_unique_resource_prefix()` |

---

### Added: Systemd Automation

All agents can be managed as systemd user services. Setup script:
`systemd/setup-systemd.sh` installs a shared virtualenv at
`~/.venv/claude-agents`, installs all packages, and deploys service/timer
files to `~/.config/systemd/user/`.

| Service | Schedule |
|---------|----------|
| `octavia-bug-triage.timer` | Daily at 09:00 |
| `octavia-code-review.timer` | Every 4 hours |
| `octavia-ci-failure.timer` | Every 4 hours |
| `octavia-bug-reproduction.path` | inotify-triggered |

Enable linger to persist services across logout: `loginctl enable-linger $USER`

---

### Added: Bug Triage Agent (`bug-triage-agent/`)

Monitors Launchpad for Octavia bugs (New, Confirmed, Triaged, In Progress)
and uses AI to triage each one.

**Subprocess isolation:** Multiple bugs are triaged by spawning one subprocess
per bug (`--single-bug <json-file>`), giving each a clean asyncio loop and
avoiding SDK cleanup errors from sequential `query()` calls.

**Command:** `octavia-triage-bugs`  
**Output:** `~/octavia_bug_triages/`  
**Tracking:** `~/.octavia_bug_triages.json`

---

## 2026-03-26

### Added: Patchset Tracking & Incremental Reviews

The code review agent tracks each patchset separately using keys of the form
`{change}~ps{patchset}`. When a new patchset is uploaded:
- Previous review is renamed to include its patchset number
- New review receives the previous review as context
- AI focuses on what changed between patchsets and whether prior issues were addressed

**Filename format:** `review_{repo}_{change}_ps{N}_{timestamp}.md`

---

### Added: Generic/Portable Refactor

The code review agent was refactored from a personal tool with hardcoded paths
to a configurable application anyone can use.

**Changes:**
- `config.py` + `config.sample.json`: hierarchical config with env var overrides
- All hardcoded paths replaced with `CONFIG["key"]` lookups
- `DEVSTACK_PATH`, `REVIEWS_OUTPUT_DIR`, `GERRIT_URL`, `MAX_REVIEWS`, `CUTOFF_DATE`
  all overridable via environment variables
- `.gitignore` excludes `config.json` (user-specific); `config.sample.json` committed

---

### Added: Code Review Agent (`code-review-agent/`)

Initial AI-powered code review agent for OpenStack changes on OpenDev/Gerrit.

**Features:**
- Fetches open changes from Gerrit API (strips `)]}'` security prefix)
- Applies cutoff date and patchset filters
- Runs unit tests (`tox -e py3`), functional tests (`tox -e functional`),
  and code quality checks (`tox -e pep8`) against the local DevStack repo
- AI analyses the diff and produces a structured markdown review
- Monitoring loop runs via systemd timer; single-change mode via CLI

**Commands:** `octavia-review-agent` (monitoring), `octavia-review-change <change>` (manual)  
**Output:** `~/octavia_reviews/`  
**Tracking:** `~/.octavia_reviewed_changes.json`
