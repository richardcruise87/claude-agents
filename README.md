# Claude Agents

AI-powered automation agents for OpenStack development, powered by Claude via Google Vertex AI.

## Agents

### [Bug Triage Agent](bug-triage-agent/)

Monitors Launchpad for new and updated Octavia bugs and generates intelligent triage reports.

**Features:**
- Fetches bugs in configurable statuses (New, Confirmed, Triaged, In Progress)
- AI analysis: severity, reproduction likelihood, root cause, suggested fix
- Re-triages bugs that have been updated since last triage
- Subprocess isolation prevents asyncio issues across multiple bugs

**Commands:**
```bash
octavia-triage-bugs
```

**Output:** `~/octavia_bug_triages/`  
**Schedule:** Daily at 09:00 (systemd timer)

---

### [Code Review Agent](code-review-agent/)

Monitors OpenDev Gerrit for open changes and produces comprehensive AI-powered code reviews.

**Features:**
- Fetches open changes from configured repositories via Gerrit, GitHub, or GitLab API
- Runs unit tests (`tox -e py3`), functional tests (`tox -e functional`), and style checks (`tox -e pep8`)
- Patchset-aware: provides previous review as context when a new patchset arrives
- Branch filtering: include/exclude lists with wildcard support
- Configurable cutoff date, max reviews per cycle, skip-WIP/draft options
- **Forge feedback posting**: optionally posts the review summary and inline line
  comments back to Gerrit/GitHub/GitLab, with optional Code-Review voting
  (+1 approve / -1 request changes / 0 minor suggestions) — disabled by default,
  enable via `feedback.post_to_forge` in config

**Commands:**
```bash
octavia-review-agent                       # monitoring mode
octavia-review-change <change_number>      # review a specific change
octavia-review-change <change_number> 3    # review a specific patchset
```

**Output:** `~/octavia_reviews/`  
**Schedule:** Every 4 hours (systemd timer)

---

### [CI Failure Agent](ci-failure-agent/)

Monitors Zuul CI for pipeline failures and uses AI to explain why each job failed and
whether a code fix or a re-run (`recheck`) is needed.

**Features:**
- Queries Zuul REST API for recent failures across configured projects and pipelines
- AI fetches actual job logs, quotes log evidence, and classifies each failure as
  `CODE_ISSUE`, `ENVIRONMENTAL`, `UNRELATED`, or `INFRA_FAILURE`
- Report includes Gerrit link, Zuul build links, per-job analysis, and overall recommendation
- Re-analyzes automatically when new failures appear after the last analysis
- `--print-prompt` flag outputs the formatted prompt for use with any AI tool (Cursor, Claude.ai, etc.)
- **Forge feedback posting**: optionally posts the analysis summary back to the Gerrit
  change / GitHub PR / GitLab MR — disabled by default, enable via `feedback.post_to_forge`

**Commands:**
```bash
# Monitoring mode (all configured repos)
octavia-ci-agent

# Manual: analyse latest failed pipeline for a specific Gerrit change
octavia-ci-agent --change 985404
octavia-ci-agent --change 985404 --pipeline check

# Manual: analyse a single Zuul build by UUID
octavia-ci-agent --build <zuul-uuid>

# Preview failures without running AI analysis
octavia-ci-agent --list-failures

# Print the formatted analysis prompt (for use with other AI tools)
octavia-analyze-ci --failure-data /tmp/data.json --print-prompt
```

**Output:** `~/octavia_ci_failures/`  
**Schedule:** Every 4 hours (systemd timer)

---

### [Bug Reproduction Agent](bug-reproduction-agent/)

Watches for new bug triage reports and attempts to reproduce bugs in a live DevStack environment.

**Features:**
- inotify-triggered: runs immediately when a new triage report appears
- AI generates and iteratively refines a reproduction script (up to 3 attempts)
- Pre-flight DevStack health check; aborts cleanly if environment is unhealthy
- Safe execution: `set -euo pipefail`, timeout, cleanup trap
- Report status: `REPRODUCED` / `NOT_REPRODUCED` / `ENVIRONMENT_ERROR` / `TIMEOUT`

**Commands:**
```bash
octavia-reproduce-bugs
```

**Output:** `~/octavia_bug_reproductions/`  
**Schedule:** Event-driven via inotify (path watcher)

---

### [DevStack Test Agent](devstack-test-agent/)

Picks up completed code reviews and runs live integration tests against a DevStack deployment,
then appends the results to the review file.

**Features:**
- Watches `~/octavia_reviews/` for new review files
- Acquires an exclusive DevStack lock before testing (prevents concurrent access)
- Deploys the change to DevStack, restarts affected services, runs integration tests
- Uses unique resource prefixes (`test-review-{pid}-{ts}-`) to avoid naming conflicts
- Appends a `DevStack Integration Tests` section to the original review file

**Commands:**
```bash
octavia-devstack-test
```

**Output:** Updates existing review files in `~/octavia_reviews/`  
**Schedule:** Every 2 hours (or event-driven on new review files)

---

## Installation

### Prerequisites

- Python 3.8+
- Vertex AI access configured:
  ```bash
  export CLAUDE_CODE_USE_VERTEX=1
  gcloud auth application-default login
  # Or: export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
  ```

### Quick Setup (Recommended)

```bash
cd ~/git/claude-agents
./setup-agents.sh
```

The setup script walks you through each step interactively:
- Creates `~/.venv/claude-agents/` and installs all agent packages
- Optionally deploys systemd unit files for automated scheduling
- Optionally configures notifications (email, Slack, ntfy.sh, desktop)

Install specific agents or add flags to skip prompts:
```bash
./setup-agents.sh bug-triage code-review   # specific agents only
./setup-agents.sh --systemd --notifications # skip prompts, enable both
./setup-agents.sh --update                  # update all agents
```

### Manual Package Installation

```bash
python3 -m venv ~/.venv/claude-agents
source ~/.venv/claude-agents/bin/activate

pip install -e agents_lib/
pip install -e bug-triage-agent/
pip install -e code-review-agent/
pip install -e bug-reproduction-agent/
pip install -e ci-failure-agent/
pip install -e devstack-test-agent/
```

### Available Commands After Installation

| Command | Description |
|---------|-------------|
| `octavia-triage-bugs` | Bug triage agent |
| `octavia-review-agent` | Code review monitoring agent |
| `octavia-review-change <change>` | Review a specific Gerrit change |
| `octavia-ci-agent` | CI failure analysis agent |
| `octavia-analyze-ci` | Analyze a single CI failure (see `--help`) |
| `octavia-reproduce-bugs` | Bug reproduction agent |
| `octavia-devstack-test` | DevStack integration test agent |

### Configuration

Each agent requires a `config.json` (created from the sample template):

```bash
for agent in bug-triage-agent code-review-agent ci-failure-agent bug-reproduction-agent devstack-test-agent; do
    cp $agent/config.sample.json $agent/config.json
    # Edit $agent/config.json with your settings
done
```

Key settings common to all agents:
- `model` — Claude model to use (default: `claude-sonnet-4-6`)
- `output.*_directory` — where to save reports
- `monitoring.max_*_per_cycle` — items to process per run
- `filters.cutoff_date` — ignore items older than this date (default: 30 days ago)

---

## Running Tests

Tests require `tox`:

```bash
pip install tox
```

### Run all tests

```bash
tox
```

### Unit tests only (fast, no network)

```bash
tox -e unit
```

### Functional tests (end-to-end flows, still no network)

```bash
tox -e functional
```

### PEP8 / style check

```bash
tox -e pep8
```

### Run a specific test file or test

```bash
tox -e unit -- tests/unit/test_utils.py -v
tox -e unit -- -k "test_slugify"
```

All tests use `pytest`. The test suite covers `agents_lib` utilities, all agent tracking/parsing modules, the notification system, and the model client provider detection — 240 tests in total.

---

## Notifications

Agents can notify you when they produce a new report. Four channels are supported — all use Python stdlib, no extra packages needed.

### Supported channels

| Channel | Mechanism | Best for |
|---------|-----------|----------|
| **Email** | SMTP (smtplib) | Full report in body |
| **Slack** | Incoming webhook | Team visibility |
| **ntfy.sh** | HTTP push | Personal phone alerts |
| **Desktop** | `notify-send` | Local machine use |

### Setup

**1. Create `notifications.json` from the sample:**

```bash
cp notifications.sample.json notifications.json
```

**2. Edit `notifications.json` to configure your channels:**

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "smtp_host": "smtp.company.com",
      "smtp_port": 587,
      "smtp_user": "you@company.com",
      "smtp_password_env": "SMTP_PASSWORD",
      "from": "claude-agents@company.com",
      "to": ["you@company.com"],
      "use_tls": true,
      "include_report_body": true
    },
    "ntfy": {
      "enabled": true,
      "url": "https://ntfy.sh/your-unique-topic"
    }
  }
}
```

Sensitive values use `*_env` keys — the agent reads the credential from that environment variable at runtime rather than storing it in the file.

**3. Enable notifications in each agent's `config.json`:**

```json
{
  "notifications": { "enabled": true }
}
```

`setup-agents.sh` can handle steps 1–3 automatically when you answer **y** to the notifications prompt.

### ntfy.sh quick start (simplest option)

[ntfy.sh](https://ntfy.sh) requires no account for basic use — just pick a unique topic name:

```json
{ "channels": { "ntfy": { "enabled": true, "url": "https://ntfy.sh/my-agents-abc123" } } }
```

Subscribe in a browser or the ntfy app and you'll get a push notification whenever a report is saved.

---

## Automation with Systemd

All agents run as systemd user services (no root required).

### Enable and Start

```bash
# Run setup first (if not already done)
./setup-agents.sh --systemd

# Bug triage — daily at 09:00
systemctl --user enable octavia-bug-triage.timer
systemctl --user start octavia-bug-triage.timer

# Code review — every 4 hours
systemctl --user enable octavia-code-review.timer
systemctl --user start octavia-code-review.timer

# CI failure analysis — every 4 hours
systemctl --user enable octavia-ci-failure.timer
systemctl --user start octavia-ci-failure.timer

# Bug reproduction — event-driven (inotify on ~/octavia_bug_triages/)
systemctl --user enable octavia-bug-reproduction.path
systemctl --user start octavia-bug-reproduction.path

# Persist services across logout
loginctl enable-linger $USER
```

### Schedules

| Service | Schedule | Trigger |
|---------|----------|---------|
| `octavia-bug-triage.timer` | Daily at 09:00 | Time-based |
| `octavia-code-review.timer` | Every 4 hours | Time-based |
| `octavia-ci-failure.timer` | Every 4 hours | Time-based |
| `octavia-bug-reproduction.path` | Immediately | New triage report (inotify) |

### Useful Commands

```bash
# Status overview
systemctl --user list-timers octavia-*
systemctl --user list-units --type=path

# Run a service manually (for testing)
systemctl --user start octavia-bug-triage.service
systemctl --user start octavia-code-review.service
systemctl --user start octavia-ci-failure.service
systemctl --user start octavia-bug-reproduction.service

# View logs
journalctl --user -u octavia-bug-triage.service -f
journalctl --user -u octavia-code-review.service -n 50
journalctl --user -u octavia-ci-failure.service -n 50
journalctl --user -u octavia-bug-reproduction.service -f
```

See the `systemd/` directory inside each agent folder for the unit files. Schedules and environment variables can be customised by editing the installed copies in `~/.config/systemd/user/`.

---

## Keeping Agents Up To Date

```bash
cd ~/git/claude-agents
./setup-agents.sh --update
```

This pulls the latest code, reinstalls all packages, reloads the systemd daemon, and offers to restart any running services. Update a single agent:

```bash
./setup-agents.sh --update ci-failure
```

### Configuration Changes

The update script does not touch your `config.json` files. After an update, compare with the sample to spot new options:

```bash
diff bug-triage-agent/config.json bug-triage-agent/config.sample.json
diff notifications.json notifications.sample.json
```

### Rollback

```bash
cd ~/git/claude-agents
git log --oneline -5           # find the previous commit hash
git checkout <commit-hash>     # revert to that version
./setup-agents.sh --update     # reinstall

# Return to latest
git checkout main && git pull && ./setup-agents.sh --update
```

### Troubleshooting

| Problem | Solution |
|---------|----------|
| `Virtual environment not found` | Run `./setup-agents.sh` first |
| `Unit not found` when restarting | Enable the service: `systemctl --user enable <service>` |
| Git pull fails with conflict | `git stash && ./setup-agents.sh --update && git stash pop` |
| Service runs but produces no output | Check `journalctl --user -u <service> -n 50` |

---

## Shared Library (`agents_lib/`)

Common utilities used by all agents:

| Module | Key functions |
|--------|--------------|
| `config_loader.py` | `load_agent_config()`, `apply_cutoff_date()`, `expand_config_paths()` |
| `tracking.py` | `should_process_item()`, `record_processed_item()` |
| `utils.py` | `expand_path()`, `slugify()`, `format_usage_info()` |
| `prompt_loader.py` | `load_prompt_template()` |
| `devstack_checks.py` | `check_devstack_health()`, `check_repo_on_main_branch()` |
| `devstack_lock.py` | `DevStackLock`, `check_devstack_available()`, `get_unique_resource_prefix()` |
| `notifications.py` | `notify_report()`, `load_notifications_config()` |

---

## Project Structure

```
claude-agents/
├── agents_lib/                  Shared utilities package
├── bug-triage-agent/            Launchpad bug triage
│   ├── install.sh               Per-agent installer
│   └── systemd/                 Unit files for this agent
├── code-review-agent/           Gerrit code review
│   ├── install.sh
│   └── systemd/
├── ci-failure-agent/            Zuul CI failure analysis
│   ├── install.sh
│   └── systemd/
├── bug-reproduction-agent/      DevStack bug reproduction
│   ├── install.sh
│   └── systemd/
├── devstack-test-agent/         DevStack integration testing
│   ├── install.sh
│   └── systemd/
├── setup-agents.sh              Install / update all agents
├── notifications.sample.json    Notification channel config template
├── CHANGELOG.md                 Full change history
├── CLAUDE.md                    Context for AI instances
└── README.md                    This file
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
