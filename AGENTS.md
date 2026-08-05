---
name: claude-agents
description: AI-powered automation agents for OpenStack Octavia development
version: 1.0
---

# Claude Agents

Nine AI-powered agents for OpenStack Octavia maintenance. All agents share a
common virtual environment (`~/.venv/claude-agents`), the `agents_lib` shared
library, and optional multi-channel notifications.

> **AI assistant note**: When a user asks you to triage a bug, review a
> change, analyse a CI failure, reproduce a bug, run integration tests, triage
> a JIRA issue, propose a fix, verify a fix, or backport a change — delegate
> to the appropriate agent command below rather than doing the work inline.

---

## Quick start

```bash
# Install eight agents into ~/.venv/claude-agents/ (backport agent is separate)
./setup-agents.sh

# Optional: configure notification channels
cp notifications.sample.json notifications.json

# Optional: enable systemd scheduling
./setup-agents.sh --systemd

# Install the backport agent separately
bash backport-agent/install.sh --venv ~/.venv/claude-agents --systemd
```

---

## Developer commands

```bash
pip install tox

tox -e unit        # unit tests only (fast, no network, no API keys needed)
tox -e functional  # end-to-end flow tests
tox -e pep8        # flake8 (max-line-length=120) + pylint
tox -e bandit      # security scan (not in default envlist)
tox                # runs py312 (all tests) + pep8 — NOT the named unit/functional envs

# Run a focused subset
tox -e unit -- tests/unit/test_model_client.py -v
tox -e unit -- -k "test_slugify"
```

**Tox quirks:**
- `tox` (no `-e`) runs `py312` + `pep8`, not the `unit`/`functional` named envs.
- `skipsdist = true` — there is no top-level package; `PYTHONPATH` is set manually to include all nine agent dirs and `agents_lib`.
- `pylint` targets individually listed files in `tox.ini`. **Adding a new `.py` file requires also adding it to the `pylint` command in `tox.ini`**; flake8 uses directories and picks up new files automatically.
- Tests require `pytest`, `pytest-asyncio`, `pytest-mock` only. No network, no DevStack, no AI credentials needed.
- `bandit` job is independent in CI — a bandit failure does not block the test job.
- CI order: `pep8` must pass before `test` runs (`needs: lint` in `.github/workflows/ci.yml`). Run `tox -e pep8` before `tox -e unit` locally to match.

**Commit conventions (from CLAUDE.md):**
- Before every commit, update `CHANGELOG.md` (new features/behaviour changes) and `README.md` (agent/command/install changes). If neither needs updating, note it in the commit body.
- Commit message format: `<Action> <component>: <description>` with a `Co-Authored-By:` footer for AI-assisted commits.

---

## Available agents

### Bug Triage Agent

Fetches open bugs from Launchpad, performs AI-powered triage (severity,
component, duplicate check, fix status, reproduction steps), and saves a
detailed markdown report.

**When to use**: a Launchpad bug needs initial analysis or re-triage after an update.

**Commands**:
```bash
octavia-triage-bugs
octavia-triage-bugs --single-bug /tmp/bug_data.json
```

> **Note**: The agent spawns each AI call in a fresh subprocess via
> `--single-bug` mode to work around a `RuntimeError` in `claude-agent-sdk`
> when `query()` is called multiple times in the same process.

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
octavia-review-agent
octavia-review-change 982567
octavia-review-change 982567 3
octavia-review-change https://review.opendev.org/c/openstack/octavia/+/982567
```

**Configuration** (`code-review-agent/config.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `forge.type` | `gerrit` | `gerrit`, `github`, or `gitlab` |
| `repositories` | openstack/octavia, … | Repos to monitor |
| `monitoring.max_reviews_per_cycle` | `3` | Reviews per run |
| `filters.skip_wip` | `true` | Skip Work-In-Progress changes |
| `feedback.post_to_forge` | `false` | Post review as Gerrit/GitHub comment |

**Output**: `~/octavia_reviews/review_<repo>_<change>_ps<n>_<timestamp>.md`

**Tracking file**: `~/.octavia_reviewed_changes.json` (tracking key: `<change_id>~ps<n>`)

---

### CI Failure Agent

Queries the Zuul CI REST API for recent pipeline failures, fetches job logs,
and produces a report classifying each failure (`CODE_ISSUE`, `ENVIRONMENTAL`,
`INFRA_FAILURE`, or `UNRELATED`) with a recommendation: fix code or recheck.

**When to use**: CI is failing and you need to understand why or whether to recheck.

**Commands**:
```bash
octavia-ci-agent
octavia-ci-agent --change 982567
octavia-ci-agent --change 982567 --pipeline check
octavia-ci-agent --build <zuul-build-uuid>
octavia-ci-agent --list-failures
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
| `log_scan_patterns` | (regex list) | Pre-classify log lines before AI analysis |

**Output**: `~/octavia_ci_failures/ci_failure_<project>_<change>_<timestamp>.md`

**Tracking file**: `~/.octavia_ci_failures.json`

---

### Bug Reproduction Agent

Reads bug triage reports from `~/octavia_bug_triages/`, generates a DevStack
bash reproduction script using AI, executes it with a timeout, and iteratively
refines the script on failure (up to 3 attempts). Saves a reproduction report
and the successful script.

**When to use**: a triaged bug needs to be reproduced in a live DevStack environment.

**Command**:
```bash
# Process the newest unprocessed triage (runs once and exits)
octavia-reproduce-bugs
```

> **Note**: In automated setups a systemd path watcher triggers this automatically
> when a new triage report appears. See `bug-reproduction-agent/systemd/`.

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

Picks up new code review files from `~/octavia_reviews/`, deploys the reviewed
change to DevStack, runs integration tests in an isolated environment (unique
resource prefix, exclusive DevStack lock), and writes a separate testing report.

**When to use**: a code review is ready and needs live integration testing.

**Command**:
```bash
# Process the newest untested review (runs once and exits)
octavia-devstack-test
```

> **Note**: The agent writes a separate `testing_report_*` file — it does NOT
> modify the original review file.

> In automated setups a systemd path watcher triggers this automatically when a
> new review appears. See `devstack-test-agent/systemd/`.

**Configuration** (`devstack-test-agent/config.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `reviews_directory` | `~/octavia_reviews` | Where to find review files |
| `devstack.path` | `/opt/stack` | DevStack installation path |
| `devstack.lock_timeout` | `300` | Seconds to wait for DevStack lock |
| `filters.only_test_repositories` | `[openstack/octavia]` | Repos to test |

**Output**: `~/octavia_reviews/testing_report_<repo>_<change>_ps<n>_<timestamp>.md`

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
| `feedback.post_to_jira` | `false` | Post triage/plan as JIRA comment |

**Output**:
- Bug triages: `~/jira_triages/jira_{KEY}_{title-slug}_{timestamp}_{seq}.md`
- Implementation plans: `~/jira_plans/jira_{KEY}_{title-slug}_{timestamp}_{seq}.md`

**Tracking file**: `~/.jira_triages.json`

---

### Fix Proposal Agent

Reads bug triage and reproduction reports for confirmed-REPRODUCED bugs, uses AI to
generate a targeted code patch, rates its risk, and saves a proposal document for
developer review.

**When to use**: a REPRODUCED bug needs a proposed fix with structured risk guidance.

**Command**:
```bash
octavia-propose-fix
```

**Configuration** (`fix-proposal-agent/config.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `triage_reports_dir` | `~/octavia_bug_triages` | Triage reports to read |
| `reproduction_reports_dir` | `~/octavia_bug_reproductions` | Reproduction reports |
| `proposals_output_dir` | `~/octavia_fix_proposals` | Where to save proposals |
| `max_proposals_per_run` | `2` | Proposals generated per run |
| `gerrit.push_wip_draft` | `false` | Push patch to Gerrit as WIP |
| `feedback.post_to_launchpad` | `false` | Post summary to Launchpad |

**Output**:
- `~/octavia_fix_proposals/fix_proposal_<number>_<title>_<timestamp>_<seq>.md`
- `~/octavia_fix_proposals/fix_proposal_<number>_context.md` (Claude Code prompt)

**Tracking file**: `~/.octavia_fix_proposals.json`

**Developer feedback loop**: write feedback to
`~/octavia_fix_proposals/fix_proposal_{bug_number}_feedback.txt` — the agent
reads and deletes it on the next run and produces a revised proposal.

---

### Fix Verification Agent

Applies a proposed fix and re-runs the confirmed bug reproduction script to
verify whether the fix resolves the bug. Supports automated operation and
manual invocation by a developer testing their own fix.

**When to use**: after a fix proposal is generated, or when a developer wants
to validate their own fix against the reproduction test before submitting.

**Commands**:
```bash
octavia-verify-fix
octavia-verify-fix --bug 2150752 --patch ~/my-fix.patch
octavia-verify-fix --bug 2150752 --branch fix/my-branch
octavia-verify-fix --bug 2150752 --gerrit 987701
octavia-verify-fix --bug 2150752 --already-applied
```

**Configuration** (`fix-verification-agent/config.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `fix_proposals_dir` | `~/octavia_fix_proposals` | Fix proposal files to verify |
| `reproduction_reports_dir` | `~/octavia_bug_reproductions` | Reproduction reports/scripts |
| `verifications_output_dir` | `~/octavia_fix_verifications` | Where to save reports |
| `verification.max_attempts` | `3` | Max retries for environmental failures |
| `verification.script_timeout` | `600` | Per-attempt timeout in seconds |
| `verification.retry_delay_seconds` | `60` | Wait between environmental retries |
| `feedback.post_to_launchpad` | `false` | Post result as Launchpad comment |

**Retry behaviour**: environmental failures (service down, API timeout) are retried up
to `max_attempts`; fix failures stop immediately.

**Output**: `~/octavia_fix_verifications/verification_<number>_<title>_<timestamp>.md`

**Tracking file**: `~/.octavia_fix_verifications.json`

**Feedback loop**: on `NOT_RESOLVED`, automatically writes
`fix_proposal_{bug_number}_feedback.txt` so the Fix Proposal Agent generates a revised fix.

---

### Backport Agent

**Not included in `setup-agents.sh`** — install separately:
```bash
bash backport-agent/install.sh --venv ~/.venv/claude-agents --systemd
```

Two binaries with distinct functions:

**`octavia-backport-monitor`** — finds recently merged changes with
`Backport-Candidate=+1`, cherry-picks them to configured stable branches, and
pushes to Gerrit as `refs/for/<branch>%topic=backport-<change_id>`. On
conflict: aborts, cleans up, records `CONFLICT`.

```bash
octavia-backport-monitor
octavia-backport-monitor --dry-run
octavia-backport-monitor --repo openstack/octavia --lookback 14
```

**`octavia-backport-review`** — reviews open backport changes in Gerrit using
the same AI infrastructure as the code-review agent. Filters for changes whose
target branch starts with `stable/` or `unmaintained/`.

```bash
octavia-backport-review
octavia-backport-review 923456
```

> **Cross-agent coupling**: `backport_review_agent.py` does
> `sys.path.insert(0, code-review-agent/)` at module level to import
> `config.py` from the code-review agent. Both agents must be present in the
> same monorepo checkout for this to work.

**Configuration** (`backport-agent/config.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `monitored_repos` | (required) | List of `owner/repo` strings |
| `source_branch` | `master` | Branch to cherry-pick from |
| `backport_branches` | (required) | Target stable branches (wildcards OK) |
| `repo_path` | (required) | Local git checkout path |
| `gerrit_remote` | `origin` | Remote name for Gerrit pushes |
| `lookback_days` | `7` | How far back to look for merged changes |

**Tracking file**: `~/.octavia_backports.json` (key: `<change_id>:<branch>`)

**Systemd**: timer at 08:00 daily for monitor; every 4 hours for review.

---

## Shared configuration

All agents share these top-level `config.json` keys:

| Key | Default | Description |
|-----|---------|-------------|
| `model` | `claude-sonnet-4-6` | AI model name |
| `model_provider` | inferred from model name | `anthropic`, `openai`, or `google` |
| `notifications.enabled` | `false` | Enable notification dispatch |
| `context.rules_file` | `~/.claude-agents/rules.md` | Read-only rules prepended to every prompt |
| `context.save_learnings` | `true` | Write post-run learnings to context file |

**Config fallback**: if `config.json` is absent, `load_agent_config()` silently
falls back to `config.sample.json`. Agents will run with sample defaults
(including `model_provider: "anthropic"`) without warning.

**Provider auto-detection**: if `model_provider` is absent, the client infers
from the model name: `claude*` → anthropic, `gpt-*`/`o1`/`o3`/`o4*` → openai,
`gemini*` → google, `litellm/*` → litellm. An explicit `model_provider` field
always wins.

**Switching to LiteLLM proxy** (OpenAI-compatible, runs locally on port 4000):
```json
{ "model": "litellm/gpt-4o" }
```
The `litellm/` prefix is stripped before the model name reaches the proxy.
No extra config keys — configure via env vars:

| Variable | Default | Description |
|----------|---------|-------------|
| `LITELLM_BASE_URL` | `http://localhost:4000/v1` | Proxy endpoint |
| `LITELLM_API_KEY` | `no-key` | API key (omit for unauthenticated local proxies) |

Or with an explicit provider and any model name the proxy supports:
```json
{ "model": "gpt-4o", "model_provider": "litellm" }
```
Requires `pip install openai` (LiteLLM speaks the OpenAI-compatible API).

**Switching AI provider** (non-LiteLLM):
```json
{ "model": "gpt-4o", "model_provider": "openai" }
```
Then `pip install openai` and set `OPENAI_API_KEY`.

**Environment variable overrides** (all agents):

| Variable | Config key |
|----------|-----------|
| `CUTOFF_DATE` | `cutoff_date` |
| `DEVSTACK_PATH` | `devstack.path` |
| `GERRIT_URL` | `gerrit.base_url` |
| `LAUNCHPAD_PROJECT` | `launchpad_project` |
| `MAX_BUGS` | `max_bugs_per_run` |
| `MAX_REVIEWS` | `monitoring.max_reviews_per_cycle` |

Credentials are stored at `~/.config/claude-agents/credentials.env` (chmod 600)
and referenced by systemd unit files via `EnvironmentFile=`.

---

## Required environment variables

| Variable | Used by | Notes |
|----------|---------|-------|
| `ANTHROPIC_API_KEY` or Vertex config | All agents (default provider) | For Vertex: set `CLAUDE_CODE_USE_VERTEX=1` + `GOOGLE_APPLICATION_CREDENTIALS` |
| `OPENAI_API_KEY` | OpenAI provider | Only when `model_provider=openai` |
| `GERRIT_USERNAME` / `GERRIT_HTTP_PASSWORD` | code-review, ci-failure, devstack-test, backport | Basic auth; omit for anonymous read-only access |
| `LAUNCHPAD_CONSUMER_KEY` / `LAUNCHPAD_ACCESS_TOKEN` / `LAUNCHPAD_ACCESS_TOKEN_SECRET` | bug-triage, fix-proposal, fix-verification | OAuth 1.0a; required only when `feedback.post_to_launchpad=true` |
| `JIRA_API_TOKEN` | jira-triage | Key name configurable via `jira.token_env` |

---

## Common multi-agent workflows

**Bug triage → reproduction** (can be fully automated):
```bash
octavia-triage-bugs           # produces triage reports
octavia-reproduce-bugs        # picks up the newest triage and tries to reproduce
```

**Reproduction → fix → verify**:
```bash
octavia-propose-fix           # reads REPRODUCED reports, generates patch
octavia-verify-fix            # applies patch, re-runs reproduction script
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

```bash
./setup-agents.sh --systemd   # install unit files

# Timer-based agents
systemctl --user enable --now octavia-bug-triage.timer      # daily at 09:00
systemctl --user enable --now octavia-code-review.timer     # every 4 hours
systemctl --user enable --now octavia-ci-failure.timer      # every 4 hours
systemctl --user enable --now octavia-fix-proposal.timer    # daily at 15:00
systemctl --user enable --now octavia-fix-verification.timer # daily at 17:00
systemctl --user enable --now octavia-backport-monitor.timer # daily at 08:00
systemctl --user enable --now octavia-backport-review.timer  # every 4 hours

# Event-driven agents (inotify path watchers)
systemctl --user enable --now octavia-bug-reproduction.path
systemctl --user enable --now octavia-devstack-test.path

# Persist services across logout
loginctl enable-linger $USER
```

---

## Key architecture notes

- **Shared library**: `agents_lib/` is a pip-installable package (`agents-lib`)
  with no mandatory external dependencies. It provides: `ModelClient`
  (multi-provider AI), `ForgeClient` (Gerrit/GitHub/GitLab), config loading,
  deduplication tracking, notifications (SMTP/Slack/ntfy/desktop — all stdlib),
  DevStack lock/checks, and prompt loading.
- **All packaging uses `setup.py`**, not `pyproject.toml`. The `pyproject.toml`
  at root contains only `[tool.bandit]` config.
- **DevStack mutex**: `DevStackLock` in `devstack_lock.py` is a file-based mutex
  shared between the devstack-test and bug-reproduction agents so they do not run
  simultaneously. Each run gets a unique resource prefix (`test-review-{pid}-{ts}-`).
- **Notifications config**: `notifications.json` lives at the repo root and is
  shared by all agents. Credential values use `*_env` suffix — the actual value
  is read from the named environment variable at runtime.
- **Context learning**: after notable outcomes, agents call `generate_learning()`
  (a second AI call) to summarise lessons, appended to
  `~/.claude-agents/<agent>_context.md`. This file is prepended to the main
  prompt on the next run, capped at 2000 chars by default.
- **Test count**: ~575 unit test functions across 32 files; ~17 functional test
  functions across 3 files (all in `tests/`).
