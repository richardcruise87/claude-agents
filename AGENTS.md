---
name: claude-agents
description: AI-powered automation agents for OpenStack Octavia development
version: 1.0
---

# Claude Agents

Six specialised AI agents for OpenStack Octavia maintenance — bug triage,
code review, CI failure analysis, bug reproduction, DevStack integration
testing, and JIRA issue triage.  All agents share a common virtual environment,
a unified install script, and optional multi-channel notifications.

> **AI assistant note**: When a user in this repo asks you to triage a bug,
> review a change, analyse a CI failure, reproduce a bug, run integration
> tests, delegate to the appropriate agent command listed below rather than
> doing the work inline.

---

## Quick start

```bash
# Install all agents into ~/.venv/claude-agents/
./setup-agents.sh

# Optional: configure notification channels
cp notifications.sample.json notifications.json
# Edit notifications.json with your SMTP / Slack / ntfy settings

# Optional: enable systemd scheduling
./setup-agents.sh --systemd
```

---

## Available agents

### Bug Triage Agent

Fetches open bugs from Launchpad, performs AI-powered triage (severity,
component, duplicate check, fix status, reproduction steps), and saves a
detailed markdown report.

**When to use**: a Launchpad bug needs initial analysis or re-triage after an update.

**Commands**:
```bash
# Monitor all configured bugs (runs the full triage loop)
octavia-triage-bugs

# Triage one specific bug by passing a JSON data file
octavia-triage-bugs --single-bug /tmp/bug_data.json
```

**Configuration** (`bug-triage-agent/config.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `launchpad_project` | `octavia` | Launchpad project to watch |
| `max_bugs_per_run` | `5` | Bugs analysed per execution |
| `bug_statuses` | New, Confirmed, Triaged, In Progress | Statuses to fetch |
| `cutoff_date` | 30 days ago | Ignore bugs older than this |

**Output**: `~/octavia_bug_triages/bug_<number>_<title>_<timestamp>_<seq>.md`

**Tracking file**: `~/.octavia_bug_triages.json`

---

### Code Review Agent

Monitors OpenDev Gerrit for open changes, downloads them to DevStack, runs
unit tests / functional tests / pep8, analyses code quality, and saves a
comprehensive markdown review with a verdict (Approve / Request Changes).

**When to use**: a Gerrit change needs review or incremental re-review after a new patchset.

**Commands**:
```bash
# Monitor all configured repositories
octavia-review-agent

# Review a specific change (latest patchset)
octavia-review-change 982567

# Review a specific patchset
octavia-review-change 982567 3

# Review by full Gerrit URL
octavia-review-change https://review.opendev.org/c/openstack/octavia/+/982567
```

**Configuration** (`code-review-agent/config.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `repositories` | openstack/octavia, … | Repos to monitor |
| `monitoring.max_reviews_per_cycle` | `3` | Reviews per run |
| `filters.cutoff_date` | 30 days ago | Ignore older changes |
| `filters.skip_wip` | `true` | Skip Work-In-Progress changes |

**Output**: `~/octavia_reviews/review_<repo>_<change>_ps<n>_<timestamp>.md`

**Tracking file**: `~/.octavia_reviewed_changes.json`

---

### CI Failure Agent

Queries the Zuul CI REST API for recent pipeline failures, fetches job logs,
and produces a report classifying each failure (`CODE_ISSUE`, `ENVIRONMENTAL`,
`INFRA_FAILURE`, or `UNRELATED`) with a recommendation: fix code or recheck.

**When to use**: CI is failing and you need to understand why or whether to recheck.

**Commands**:
```bash
# Monitor all configured repositories
octavia-ci-agent

# Analyse failures for a specific Gerrit change
octavia-ci-agent --change 982567

# Analyse failures in a specific pipeline
octavia-ci-agent --change 982567 --pipeline check

# Analyse a single Zuul build by UUID
octavia-ci-agent --build <zuul-build-uuid>

# List recent failures without running AI analysis
octavia-ci-agent --list-failures

# Print the formatted prompt only (for use with any AI tool)
octavia-analyze-ci --failure-data /tmp/data.json --print-prompt
```

**Configuration** (`ci-failure-agent/config.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `zuul.base_url` | zuul.opendev.org | Zuul instance URL |
| `zuul.tenant` | `openstack` | Zuul tenant |
| `zuul.pipelines` | check, gate | Pipelines to monitor |
| `zuul.hours_back` | `24` | Look-back window in hours |
| `monitoring.max_changes_per_cycle` | `5` | Changes analysed per run |

**Output**: `~/octavia_ci_failures/ci_failure_<project>_<change>_<timestamp>.md`

**Tracking file**: `~/.octavia_ci_failures.json`

---

### Bug Reproduction Agent

Reads bug triage reports from `~/octavia_bug_triages/`, generates a DevStack
bash reproduction script using AI, executes it with a timeout, and iteratively
refines the script on failure (up to 3 attempts).  Saves a reproduction report
and the successful script.

**When to use**: a triaged bug needs to be reproduced in a live DevStack environment.

**Command**:
```bash
# Process the newest unprocessed triage (runs once and exits)
octavia-reproduce-bugs
```

> **Note**: In automated setups a systemd path watcher triggers this automatically
> when a new triage report appears.  See `bug-reproduction-agent/systemd/`.

**Configuration** (`bug-reproduction-agent/config.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `triage_reports_dir` | `~/octavia_bug_triages` | Where to find triage reports |
| `reproductions_output_dir` | `~/octavia_bug_reproductions` | Where to save reports |
| `devstack.path` | `/opt/stack` | DevStack installation path |
| `reproduction.max_attempts` | `3` | Script refinement attempts |
| `reproduction.script_timeout` | `600` | Execution timeout (seconds) |

**Output**:
- `~/octavia_bug_reproductions/reproduction_<number>_<title>_<timestamp>.md`
- `~/octavia_bug_reproductions/scripts/bug_<number>_reproduction.sh`

**Tracking file**: `~/.octavia_bug_reproductions.json`

---

### DevStack Test Agent

Watches `~/octavia_reviews/` for new review files, deploys the reviewed change
to DevStack, runs integration tests in an isolated environment (unique resource
prefix, exclusive DevStack lock), and appends a "DevStack Integration Tests"
section to the original review file.

**When to use**: a code review is ready and needs live integration testing.

**Command**:
```bash
# Process the newest untested review (runs once and exits)
octavia-devstack-test
```

> **Note**: In automated setups a systemd path watcher triggers this automatically
> when a new review appears.  See `devstack-test-agent/systemd/`.

**Configuration** (`devstack-test-agent/config.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `reviews_directory` | `~/octavia_reviews` | Where to find review files |
| `devstack.path` | `/opt/stack` | DevStack installation path |
| `devstack.lock_timeout` | `300` | Seconds to wait for DevStack lock |
| `filters.only_test_repositories` | `[openstack/octavia]` | Repos to test |

**Output**: appends results to the existing review file in `~/octavia_reviews/`

**Tracking file**: `~/.octavia_devstack_tests.json`

---

### JIRA Triage Agent

Reads JIRA issues matching a configurable JQL query and produces:
- **Bugs / Defects** → triage report (same structure as the Launchpad bug triage agent)
- **Stories / Tasks** → implementation plan with risk assessment, complexity estimate, and open questions

**When to use**: triage JIRA bugs, or produce implementation plans for stories and tasks.

**Command**:
```bash
octavia-jira-triage
```

**Key configuration** (`jira-triage-agent/config.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `jira.base_url` | (required) | Atlassian Cloud URL, e.g. `https://myco.atlassian.net` |
| `jira.email` | (required) | Your Atlassian account email |
| `jira.token_env` | `JIRA_API_TOKEN` | Env var holding your API token |
| `jira.jql` | (required) | JQL query — all filtering goes here |
| `processing.max_issues_per_run` | `5` | Issues processed per execution |
| `issue_types.bugs` | `["Bug", "Defect"]` | Types treated as bugs |
| `issue_types.planning` | `["Story", "Task", "Epic"]` | Types that get implementation plans |

**Output**:
- Bug triages: `~/jira_triages/jira_{KEY}_{title-slug}_{timestamp}_{seq}.md`
- Implementation plans: `~/jira_plans/jira_{KEY}_{title-slug}_{timestamp}_{seq}.md`

**Tracking file**: `~/.jira_triages.json`

---

## Shared configuration

All agents share these top-level `config.json` keys:

| Key | Description |
|-----|-------------|
| `model` | AI model name (default: `claude-sonnet-4-6`) |
| `model_provider` | `anthropic` (default), `openai`, or `google` |
| `notifications.enabled` | `true`/`false` — send reports via configured channels |

To switch to a different AI provider:
```json
{ "model": "gpt-4o", "model_provider": "openai" }
```
Then `pip install openai` and set `OPENAI_API_KEY`.

---

## Running the test suite

```bash
pip install tox

tox -e unit        # 223 unit tests — fast, no network required
tox -e functional  # end-to-end flow tests
tox -e pep8        # flake8 + pylint (10.00/10 score)
tox                # run everything
```

---

## Common multi-agent workflows

**Bug triage → reproduction** (can be fully automated):
```bash
octavia-triage-bugs           # produces triage reports
octavia-reproduce-bugs        # picks up the newest triage and tries to reproduce
```

**Code review → integration test** (can be fully automated):
```bash
octavia-review-change 982567  # produces a review file
octavia-devstack-test         # picks up the newest review and runs live tests
```

**CI failure investigation**:
```bash
octavia-ci-agent --change 982567
# Read ~/octavia_ci_failures/*.md for analysis and recommendation
```

---

## Automated scheduling

Each agent ships with systemd unit files for unattended operation:

```bash
./setup-agents.sh --systemd   # install unit files

# Timer-based agents
systemctl --user enable --now octavia-bug-triage.timer      # daily at 09:00
systemctl --user enable --now octavia-code-review.timer     # every 4 hours
systemctl --user enable --now octavia-ci-failure.timer      # every 4 hours

# Event-driven agents (inotify path watchers)
systemctl --user enable --now octavia-bug-reproduction.path
systemctl --user enable --now octavia-devstack-test.path

# Persist services across logout
loginctl enable-linger $USER
```
