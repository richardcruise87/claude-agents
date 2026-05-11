# Changelog

All notable changes to the claude-agents project are documented here.

---

## 2026-05-11

### Added: Fix Verification Agent

New `fix-verification-agent` applies a proposed fix and re-runs the confirmed
bug reproduction script to verify whether the fix resolves the bug.

**Smart retry logic** (key difference from Bug Reproduction Agent):
- `FIX_FAILURE` — bug still triggers after patch → stop immediately (no point retrying)
- `ENVIRONMENTAL` — service down, API timeout, etc. → retry up to `max_attempts`
- `INCONCLUSIVE` — ambiguous → stop (safe default)

**Patch sources** (manual mode via `--bug N` CLI flag):
- `--patch FILE` — apply a local unified diff file
- `--branch NAME` — checkout a local git branch
- `--gerrit CHANGE` — fetch and checkout a Gerrit change
- `--already-applied` — skip patch step, just re-run the reproduction test

**Automated mode**: watches `~/octavia_fix_proposals/` for new proposals, applies
the embedded patch, and verifies. On `NOT_RESOLVED`, writes
`fix_proposal_{N}_feedback.txt` so the Fix Proposal Agent generates a revised fix.

**Launchpad posting**: optional (`feedback.post_to_launchpad: false` by default).
Distinct messages for RESOLVED / NOT_RESOLVED / ENVIRONMENTAL_ERROR (the last
makes clear that infrastructure issues are not a verdict on the fix).

**New files:** `fix-verification-agent/` directory, 11 new unit tests,
`systemd/octavia-fix-verification.{service,timer}` (daily at 17:00, 3h timeout)

---

## 2026-05-08

### Added: AI audit step to verify bug was actually triggered before marking REPRODUCED

`bug_reproduction_agent.py` was marking bugs as `REPRODUCED` whenever a script
exited 0, even if the script was empty and did nothing — a false positive observed
in bug #2150752 where attempt 7 consisted only of the cleanup trap.

`audit_reproduction()` in `script_generator.py` now runs before any exit-0 result
is accepted as REPRODUCED:
1. **Fast heuristic** (no API call): `execution_time < 5s` AND `stdout < 150 chars` → reject immediately
2. **Explicit marker** (no API call): `"BUG REPRODUCED"` in stdout → accept immediately
3. **AI audit**: query the model with script + output; answer NO → treat as `SCRIPT_FAILURE` and continue refinement loop

Also adds `prompts/script_audit_prompt.txt`. PR review feedback applied:
- Marker check moved before heuristic (valid short-output scripts were incorrectly rejected)
- `expected_error` derived from triage root cause instead of hardcoded Octavia-specific types

---

### Added: Per-attempt reasoning and final reproduction summary in reports

Reproduction reports previously showed raw script output with no explanation of the
agent's reasoning or why it changed the script between attempts.

Both generation/refinement prompts now request a brief explanation before the script.
`extract_reasoning_from_response()` captures text before the first code block.
`extract_script_changelog()` extracts `# Attempt N changes` comment blocks.

The report now includes per-attempt "Agent's Approach" / "Agent's Analysis" sections
and a final "How the Bug Was Reproduced" summary for successful runs. The reasoning
is also passed to the audit step so the auditor can evaluate whether the stated
approach matches the actual output.

The refinement prompt documents the exact `# Attempt N changes vs Attempt N-1:`
format so `extract_script_changelog()` reliably finds the block.

---

### Fixed: ValueError unpacking attempt tuples in Final Reproduction Script section

`generate_report()` stores attempts as `(script, result, usage_dict)` 3-tuples,
but the Final Reproduction Script section iterated with `for script, result in attempts:`,
raising `ValueError: too many values to unpack`. Fixed with starred assignment:
`for script, result, *_ in attempts:`.

---

### Fixed: TypeError comparing naive and aware datetimes in zuul_client

`fetch_recent_failures()` compared `end_time` (from Zuul build timestamps) against
`cutoff_time = datetime.now(timezone.utc)`. Some Zuul builds return timestamps without
a timezone suffix, causing `datetime.fromisoformat()` to return a naive datetime.
Fixed by assuming UTC for any naive timestamp: `end_time.replace(tzinfo=timezone.utc)`.

---

### Changed: Bug reproduction service timeout increased from 1800s to 10800s

The 30-minute systemd timeout was killing the bug reproduction service mid-run on
complex bugs requiring multiple script attempts. With up to 10 attempts at 900s each
(9000s maximum), increased to 10800s (3 hours) to give comfortable headroom.

---

## 2026-05-07

### Added: Fix Proposal Agent

New `fix-proposal-agent` reads confirmed-REPRODUCED bug triage and reproduction
reports, uses AI to generate a targeted code patch, rates its risk across four
dimensions (scope, confidence, test coverage, domain), and writes a structured
proposal document.

**Proposal workflow:**
- Developer receives a `fix_proposal_*.md` document with the patch embedded and
  a risk rating (LOW / MEDIUM / HIGH)
- Separate `fix_proposal_*_context.md` is a ready-to-paste Claude Code prompt
- Developer can accept the fix, paste the context packet into Claude Code, or abandon
- **Feedback loop**: write feedback to `fix_proposal_{N}_feedback.txt` — agent reads
  and deletes it on next run and generates a revised proposal (sequence 2+)

**Optional integrations (all off by default):**
- `gerrit.push_wip_draft: true` — push the patch to Gerrit as a WIP change
- `gerrit.remote_name` — configurable git remote name (default: `"gerrit"`)
- `feedback.post_to_launchpad: true` — post summary as a Launchpad bug comment
- `feedback.read_launchpad_comments / read_gerrit_comments` — read feedback online

**New files:** `fix-proposal-agent/` directory, 16 new unit tests,
`systemd/octavia-fix-proposal.{service,timer}` (daily at 15:00)

---

### Changed: DevStack Test Agent writes separate testing_report_* files

Previously modified the original `review_*.md` in place, inserting a DevStack
section by searching for `## Code Analysis`. When absent, fell back to appending
at the end, producing inconsistent formatting.

Now leaves `review_*.md` untouched and creates `testing_report_*` in the same
directory, containing the full review content followed by DevStack results.
Tracking record gains a `test_report_file` field. Desktop notification opens
the test report file.

---

### Fixed: Reproduction filenames missing bug number and title

Two bugs caused files named `reproduction___<timestamp>_1.md`:

1. `triage_parser.py` — `extract_bug_metadata()` only matched the old bold-field
   format. Added fallback regexes (anchored with `re.MULTILINE`) for the newer
   heading format (`# Bug Triage Report: Bug #N` / `## Title`).
2. `report_generator.py` — `generate_executive_summary()` used plain triple-quoted
   strings with `{triage.bug_title}` etc. without an `f` prefix, so placeholders
   appeared literally. Rewritten as f-string concatenation.

---

### Fixed: GNOME desktop notification — clicking Open now works

`notify-send 0.8.x` uses `--action=[NAME=]Text` (`=` separator). Using
`--action=open:Open` caused the name to default to `"0"` so `xdg-open` was
never called. Fixed to `--action=open=Open`.

---

### Fixed: Gerrit query encoding returning empty results

`list_open_changes()` passed the query string through `urllib.parse.urlencode`,
encoding `+`/`:`/`/` as `%2B`/`%3A`/`%2F`. Gerrit treats these as literals and
returns an empty list. The `q` parameter is now built separately, unencoded.

---

### Fixed: Review history tracking file corruption crash

`load_review_history()` called `raw.items()` on a JSON array (old tracking
format), causing `'list' object has no attribute 'items'`. Now returns `{}`
for non-dict files so the agent continues and rebuilds the file correctly.

---

### Fixed: DevStack health check — openrc tilde not expanded and bashrc not sourced

- `Path("~/git/devstack/openrc").exists()` always returned `False` — added
  `.expanduser()` in `devstack_checks.py`.
- `openstack loadbalancer list` failed with `not an openstack command` because
  `~/.bashrc` (which activates the Octavia client venv) was not sourced. The
  health check now sources `~/.bashrc` before the openrc file.

---

### Changed: Default model aligned to claude-sonnet-4-6

Code review agent service had `claude-opus-4-6`; all other agents use
`claude-sonnet-4-6`. Aligned all agent service files.

---

### Changed: Systemd services log to ~/octavia-logs/ files

Changed from `StandardOutput=journal` to `StandardOutput=append:%h/octavia-logs/<agent>.log`
to work around a RHEL 10 journald issue where user service logs were inaccessible
via `journalctl --user`.

---

### Changed: Desktop notifications open report on click

`_send_desktop()` now uses `notify-send --action=open=Open` and spawns a
background shell (`subprocess.Popen`) that calls `xdg-open <report_path>`
on click, without blocking the agent.

---

## 2026-05-01

### Added: Feedback posting for Launchpad and JIRA triage agents

The Launchpad bug triage agent and the JIRA triage agent can now post
their generated report as a comment back to the original bug/issue.

**Launchpad:**
- Posts the triage report as a bug message via `POST /bugs/{id}/messages`
- Uses OAuth 1.0a HMAC-SHA1 signing implemented with stdlib `hmac`/`hashlib`
  (no new runtime dependencies)
- Credentials via env vars: `LAUNCHPAD_CONSUMER_KEY`, `LAUNCHPAD_ACCESS_TOKEN`,
  `LAUNCHPAD_ACCESS_TOKEN_SECRET` (obtain once via launchpadlib)
- Configure: `bug-triage-agent/config.json` → `feedback.post_to_launchpad: true`

**JIRA:**
- Posts the triage/plan report as a JIRA comment via
  `POST /rest/api/3/issue/{key}/comment`
- All JIRA comments are **private by default** (visibility restricted to a
  configurable role, default `"Service Desk Team"`)
- Comment body converted from plain text/markdown to Atlassian Document Format
  (ADF) via the new `_text_to_adf()` helper in `jira_client.py`
- Configure: `jira-triage-agent/config.json` → `feedback.post_to_jira: true`

**Shared:**
- New `build_feedback_comment(report_content, model_name, max_chars)` in
  `agents_lib` strips token-usage sections, caps length, sanitizes credentials
  via `sanitize_for_forge()`, and wraps with AI attribution header/footer
- All posting is disabled by default (`post_to_*: false`)
- Comments clearly state they were generated by AI (model name included)

**New/changed files:**
- `agents_lib/agents_lib/utils.py` — `build_feedback_comment()`
- `agents_lib/agents_lib/__init__.py` — exports `build_feedback_comment`
- `jira-triage-agent/jira_client.py` — `add_comment()`, `_text_to_adf()`
- `jira-triage-agent/config.{py,sample.json}` — `feedback` section
- `jira-triage-agent/jira_triage_agent.py` — `_post_jira_feedback()`
- `bug-triage-agent/bug_triage_agent.py` — OAuth helpers, `_post_bug_feedback()`
- `bug-triage-agent/config.{py,sample.json}` — `feedback` section
- `tests/unit/test_jira_client.py` — `_text_to_adf` and `add_comment` tests
- `tests/unit/test_utils.py` — `build_feedback_comment` tests
- `tests/unit/test_bug_triage_feedback.py` — OAuth, post, and feedback tests

---

### Added: Forge feedback posting for code review and CI failure agents

The code review agent and CI failure agent can now post their analysis results
directly back to the source forge (Gerrit, GitHub, or GitLab) after each run.

**What gets posted:**

- **Code review agent** — Posts a condensed review summary (verdict, test
  results, key findings) as an overall comment.  Where the review identifies
  specific line-level issues, those are posted as inline comments on the
  relevant file and line.  Optionally casts a `Code-Review` vote:
  `+1` (approve), `-1` (major issues found), or `0` (minor suggestions only).
- **CI failure agent** — Posts the overall recommendation and failing-jobs
  summary table as an informational comment on the change.  No vote is cast
  (voting disabled by default for CI analysis).

Both posts include an AI attribution line: *"Reviewed/analysed by <model>"*
and a *"generated by AI"* footer.

**How to enable (code review agent — `code-review-agent/config.json`):**
```json
"feedback": {
  "post_to_forge": true,
  "enable_voting": true,
  "vote_label": "Code-Review",
  "approval_score": 1,
  "major_issues_score": -1,
  "minor_only_score": 0
}
```
Requires `forge.token_env` to point to an env var holding a valid API token.

**How to enable (CI failure agent — `ci-failure-agent/config.json`):**
```json
"forge": { "type": "gerrit", "base_url": "...", "token_env": "GERRIT_TOKEN" },
"feedback": { "post_to_forge": true }
```

**New files:**
- `agents_lib/agents_lib/forge_client.py` — `LineComment` dataclass, `_http_post`
  helper, and `post_feedback()` method on `ForgeClient`, `GerritClient`,
  `GitHubClient`, and `GitLabClient`.
- `code-review-agent/review_parser.py` — `extract_forge_comment()`,
  `extract_line_comments()`, `determine_vote()`.

**Changed files:**
- `agents_lib/agents_lib/__init__.py` — exports `LineComment`.
- `code-review-agent/config.sample.json` — new `feedback` section.
- `code-review-agent/config.py` — loads feedback keys into flat config.
- `code-review-agent/review_single_change.py` — calls `_post_forge_feedback()`
  after the review file is confirmed.
- `ci-failure-agent/config.sample.json` — new `forge` and `feedback` sections.
- `ci-failure-agent/config.py` — loads forge and feedback config.
- `ci-failure-agent/analyze_ci_failure.py` — calls `_post_ci_feedback()` after
  the report is saved.

**Forge posting is disabled by default** (`post_to_forge: false`) — no
change to existing behaviour unless the option is explicitly enabled.

---

### Added: JIRA Triage Agent (`jira-triage-agent/`)

New standalone agent that reads JIRA issues via a user-supplied JQL query and
produces AI-powered outputs depending on issue type:

- **Bugs / Defects** — triage report: validate the bug, check for duplicates,
  assess severity, outline a reproduction strategy, and propose a fix approach.
  Follows the same analytical steps as the existing Launchpad bug triage agent.
- **Stories / Tasks / Epics** — implementation plan: break down the requirement,
  list implementation steps in order, identify technical/scope/integration/
  compatibility risks (each with likelihood and mitigation), propose a testing
  strategy, and give a T-shirt size complexity estimate.

**Key design decisions:**
- The JQL query is opaque to the agent — all filtering (project, status, date
  range, labels) lives in config rather than being baked into the agent code.
- Uses stdlib `urllib` for the JIRA REST API (no third-party SDK dependency).
- Converts Atlassian Document Format (ADF) rich text to plain text for prompt
  injection.
- Subprocess isolation (same pattern as the bug triage agent) gives each issue
  a fresh asyncio event loop.
- Re-processes issues when they are updated (sequence tracking via agents_lib).

**New files:** `jira-triage-agent/` directory with `jira_client.py`,
`issue_tracker.py`, `jira_triage_agent.py`, `config.py`, `config.sample.json`,
two prompt/template pairs (bug triage + planning), systemd unit files, and a
Claude Code sub-agent definition at `.claude/agents/jira-triage.md`.

**Updated:** `setup-agents.sh` (adds `jira-triage` agent name), `AGENTS.md`.

### Added: Multi-forge code review support (Gerrit / GitHub / GitLab)

The code review agent can now work with GitHub and GitLab in addition to Gerrit,
selected via `forge.type` in `config.json`.

**New in `agents_lib`:**
- `forge_client.py` — `ForgeClient` base class + `GerritClient`, `GitHubClient`,
  `GitLabClient` implementations; `ChangeInfo` normalised dataclass; `create_forge_client(config)` factory.  All HTTP calls use stdlib `urllib` (no new deps).
- `review_history.py` — forge-agnostic review tracking.  `ReviewRecord` dataclass;
  `should_review_change()` detects new Gerrit patchsets OR new HEAD SHA (GitHub/GitLab);
  `create_review_filename()` generates backward-compatible names for Gerrit and
  sequence-based names for GitHub/GitLab.

**Changes to code-review-agent:**
- Two AI `WebFetch` calls that resolved Gerrit change details are replaced by direct
  `forge_client.get_change()` calls — faster and reliable.
- `octavia_review_agent.py`: `fetch_pending_changes()` replaced by `forge_client.list_open_changes()`; Gerrit JSON parsing removed.
- `review_single_change.py`: forge client resolves change details; `patchset` argument silently ignored for GitHub/GitLab.
- `prompts/code_review_prompt_pr.txt` — shared GitHub/GitLab prompt using `{pr_or_mr}` placeholder.
- `config.sample.json` gains a `forge` section; existing `gerrit.base_url` configs continue to work unchanged.

**Tests:** `tests/unit/test_forge_client.py` and `tests/unit/test_review_history.py`.

## 2026-04-30

### Added: AGENTS.md and Claude Code sub-agent definitions

Makes all five agents discoverable and invokable from AI coding assistants:

- **`AGENTS.md`** (repo root) — follows the open `agents.md` standard.
  Describes each agent's purpose, CLI commands, key configuration, output
  locations, and common multi-agent workflows.

- **`.claude/agents/*.md`** — Claude Code sub-agent definitions for all five
  agents.  Each file has YAML front matter (`name`, `description`, `tools`)
  and a prompt that tells Claude Code how to invoke the agent and summarise
  its output.  Accessible via the `/agents` command in a Claude Code session.

### Added: Provider-agnostic model client (`agents_lib/model_client.py`)

Agents no longer import `claude_agent_sdk` directly.  A new abstraction layer
lets them run on Anthropic (Claude), OpenAI (GPT-4o, o3…), or Google (Gemini)
by changing two config values.

**New in `agents_lib`:**
- `model_client.py` — `ModelResult` dataclass, `ModelClient`, `create_model_client(config)`
- Three provider backends: Anthropic (delegates to claude-agent-sdk, unchanged
  behaviour), OpenAI (`openai` package, optional dep), Google Gemini
  (`google-generativeai` package, optional dep)
- Tool execution loop for OpenAI/Gemini implements: `bash`, `read_file`,
  `write_file`, `grep`, `glob`, `web_fetch`
- `load_agent_prompt(name, provider, prompts_dir, save_path)` added to
  `prompt_loader.py` — selects provider-specific prompt file if present, appends
  template file, and injects the Write-tool save instruction only for Anthropic

**Config:** `"model_provider": "anthropic"` added to all `config.sample.json`
files.  Switching providers: set `"model": "gpt-4o", "model_provider": "openai"`.

**Prompt changes:** Write-tool save instructions removed from prompt files and
injected dynamically by `load_agent_prompt()`.  Bug triage prompt split into
analysis instructions + `bug_triage_template.txt` (output format).

### Added: Multi-channel notification system

All agents now call `notify_report()` after saving each report, dispatching
to any combination of configured channels.

**New in `agents_lib`:**
- `agents_lib/notifications.py` — `notify_report()` and `load_notifications_config()`
  exported from `agents_lib.__init__`
- Four channel backends, all using Python stdlib (no new pip dependencies):
  - **Email** — SMTP with STARTTLS/SSL; optionally includes full report body
  - **Slack** — incoming webhook; sends subject, summary, and a report excerpt
  - **ntfy.sh** — HTTP push; configurable priority; works with self-hosted instances
  - **Desktop** — `notify-send`; skipped gracefully when no display is available
- Channel failures are caught per-channel and logged to stderr; they never
  crash or interrupt the agent

**Configuration:**
- `notifications.sample.json` (repo root) — shared channel credentials template;
  copy to `notifications.json` (gitignored) and fill in your credentials
- Each agent's `config.sample.json` gains `"notifications": {"enabled": false}`;
  set `enabled: true` in your local `config.json` to activate

**Sensitive values** use `*_env` keys (e.g. `smtp_password_env: "SMTP_PASSWORD"`)
so credentials stay in environment variables rather than config files.

## 2026-04-30

### Changed: Unified agent installation scripts

Consolidated `update-agents.sh`, `systemd/setup-systemd.sh`, and the old
`code-review-agent/install.sh` into a single, consistent approach:

- **New `setup-agents.sh`** (repo root) — installs or updates any combination
  of agents; accepts `--update`, `--systemd`/`--no-systemd`, `--venv PATH`, and
  individual agent names as arguments.  Replaces both `update-agents.sh` and
  `systemd/setup-systemd.sh`.
- **Per-agent `install.sh`** — each agent directory now has its own `install.sh`
  that can be run standalone or called by `setup-agents.sh`.  Handles venv
  creation, `agents_lib` bootstrapping, package install, config copy, and
  optional systemd file installation.
- **Per-agent `systemd/` directories** — unit files (`*.service`, `*.timer`,
  `*.path`) now live alongside the agent code instead of in a shared `systemd/`
  directory.  Covers all five agents including `devstack-test-agent`.
- Removed the root-level `systemd/` directory, `update-agents.sh`, and
  `code-review-agent/setup_review_agent.sh`.
- Updated Installation sections in all agent READMEs.

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
