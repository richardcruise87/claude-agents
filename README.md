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
- Fetches open changes from configured repositories via Gerrit API
- Runs unit tests (`tox -e py3`), functional tests (`tox -e functional`), and style checks (`tox -e pep8`)
- Patchset-aware: provides previous review as context when a new patchset arrives
- Branch filtering: include/exclude lists with wildcard support
- Configurable cutoff date, max reviews per cycle, skip-WIP/draft options

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

The setup script creates a shared virtual environment, installs all packages, and deploys systemd services:

```bash
cd ~/git/claude-agents/systemd
./setup-systemd.sh
```

This installs the `~/.venv/claude-agents/` virtual environment and provides all commands below.

### Manual Package Installation

```bash
python3 -m venv venv
source venv/bin/activate

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

## Automation with Systemd

All agents run as systemd user services (no root required).

### Enable and Start

```bash
# Run setup first (if not already done)
cd systemd && ./setup-systemd.sh

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

See [systemd/README.md](systemd/README.md) for full documentation including resource limits, environment variables, and advanced scheduling.

---

## Keeping Agents Up To Date

### One-Shot Update Script

```bash
cd ~/git/claude-agents
./update-agents.sh
```

This script:
1. Pulls the latest code from git
2. Reinstalls all packages in `~/.venv/claude-agents/`
3. Reloads the systemd daemon
4. Optionally restarts running services

### Manual Update

```bash
cd ~/git/claude-agents
git pull

source ~/.venv/claude-agents/bin/activate
pip install -e agents_lib/ -e bug-triage-agent/ -e code-review-agent/ \
            -e ci-failure-agent/ -e bug-reproduction-agent/ -e devstack-test-agent/

systemctl --user daemon-reload

# Restart services to apply changes immediately (optional)
systemctl --user restart octavia-bug-triage.timer
systemctl --user restart octavia-code-review.timer
systemctl --user restart octavia-ci-failure.timer
systemctl --user restart octavia-bug-reproduction.path
```

### After Updating

```bash
# Confirm services are running
systemctl --user list-timers octavia-*

# Check for recent errors
journalctl --user -u octavia-code-review.service -n 20
```

### Configuration Changes

The update script only updates code, not your `config.json` files. After an update:

```bash
# Compare your config with the new sample to find new options
diff bug-triage-agent/config.json bug-triage-agent/config.sample.json
diff code-review-agent/config.json code-review-agent/config.sample.json
diff ci-failure-agent/config.json ci-failure-agent/config.sample.json
```

### Rollback

```bash
cd ~/git/claude-agents
git log --oneline -5          # find the previous commit hash
git checkout <commit-hash>    # revert to that version
./update-agents.sh            # reinstall

# Return to latest
git checkout main && git pull && ./update-agents.sh
```

### Troubleshooting

| Problem | Solution |
|---------|----------|
| `Virtual environment not found` | Run `systemd/setup-systemd.sh` first |
| `Unit not found` when restarting | Enable the service: `systemctl --user enable <service>` |
| Git pull fails with conflict | `git stash && ./update-agents.sh && git stash pop` |
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

---

## Project Structure

```
claude-agents/
├── agents_lib/              Shared utilities package
├── bug-triage-agent/        Launchpad bug triage
├── code-review-agent/       Gerrit code review
├── ci-failure-agent/        Zuul CI failure analysis
├── bug-reproduction-agent/  DevStack bug reproduction
├── devstack-test-agent/     DevStack integration testing
├── systemd/                 Service/timer files and setup script
├── CHANGELOG.md             Full change history
├── CLAUDE.md                Context for AI instances
├── update-agents.sh         One-shot update script
└── README.md                This file
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
