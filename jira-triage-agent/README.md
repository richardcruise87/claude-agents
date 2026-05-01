# JIRA Triage Agent

AI-powered triage and planning agent for JIRA issues.

## Features

- **Bug / Defect triage** — validates the bug, checks for duplicates, assesses
  severity, outlines a reproduction strategy, and proposes a fix
- **Story / Task / Epic planning** — breaks down the requirement, proposes an
  ordered implementation, identifies risks with likelihood and mitigation, and
  estimates complexity (T-shirt size)
- **JQL-driven** — all issue selection lives in a single JQL string in config;
  no filtering logic is baked into the agent
- **JIRA Cloud & Server** — supports Atlassian Document Format (ADF) rich text
  as well as plain-text descriptions (Server / Data Center)
- **Sequence tracking** — re-triages / re-plans issues when they are updated;
  sequence numbers let you see how thinking evolved
- **Notifications** — optional email, Slack, ntfy.sh, or desktop notifications
  when a report is saved

## Installation

### Using `setup-agents.sh` (recommended)

```bash
cd ~/git/claude-agents
./setup-agents.sh jira-triage             # install this agent only
./setup-agents.sh --systemd jira-triage   # also install the systemd timer
./setup-agents.sh --update jira-triage    # update to latest version
```

### Standalone

```bash
cd ~/git/claude-agents/jira-triage-agent
./install.sh               # installs into ~/.venv/claude-agents
./install.sh --systemd     # also installs the systemd timer
```

This provides the `octavia-jira-triage` command.

## Configuration

Copy the sample config and edit it:

```bash
cp config.sample.json config.json
```

Key settings:

| Key | Description |
|-----|-------------|
| `jira.base_url` | Your Atlassian instance URL, e.g. `https://myco.atlassian.net` |
| `jira.email` | Your Atlassian account email address |
| `jira.token_env` | Name of the env var holding your API token (default: `JIRA_API_TOKEN`) |
| `jira.jql` | JQL query — all filtering (project, status, dates, labels) goes here |
| `processing.max_issues_per_run` | Maximum issues processed per execution (default: 5) |
| `processing.cutoff_date` | Skip issues created before this date (`YYYY-MM-DD`); `null` = 30 days ago |
| `issue_types.bugs` | Issue type names treated as bugs (default: `["Bug", "Defect"]`) |
| `issue_types.planning` | Issue type names that get implementation plans (default: `["Story", "Task", "Epic"]`) |

### API token

Generate a JIRA API token at <https://id.atlassian.com/manage-profile/security/api-tokens> and export it:

```bash
export JIRA_API_TOKEN=your_token_here
```

Add this to `~/.bashrc` (or configure it in the systemd service file) to persist it.

### Example JQL queries

```
# All open bugs in a project, updated in the last week
project = MYPROJ AND issuetype in ("Bug", "Defect") AND status != Done AND updated >= -7d ORDER BY updated DESC

# High-priority stories not yet started
project = MYPROJ AND issuetype = Story AND status = "To Do" AND priority in (High, Critical) ORDER BY priority DESC

# Everything assigned to me
assignee = currentUser() AND status != Done ORDER BY updated DESC
```

## Running manually

```bash
# Activate the virtual environment
source ~/.venv/claude-agents/bin/activate

# Run the agent (processes up to max_issues_per_run issues)
octavia-jira-triage
```

## Automated scheduling with systemd

```bash
# Install systemd files
./setup-agents.sh --systemd jira-triage

# Enable and start the timer (runs every 4 hours by default)
systemctl --user enable --now octavia-jira-triage.timer

# Check status
systemctl --user status octavia-jira-triage.timer
journalctl --user -u octavia-jira-triage.service -f

# Persist across logout
loginctl enable-linger $USER
```

Edit `~/.config/systemd/user/octavia-jira-triage.timer` to change the schedule.

## Output

| Issue type | Output directory | Filename pattern |
|------------|-----------------|-----------------|
| Bug / Defect | `~/jira_triages/` | `jira_{KEY}_{slug}_{timestamp}_{seq}.md` |
| Story / Task / Epic | `~/jira_plans/` | `jira_{KEY}_{slug}_{timestamp}_{seq}.md` |

The sequence number (`_1`, `_2`, …) increments each time an issue is updated and
re-processed, letting you see how the analysis evolved over time.

## Tracking

Processed issues are recorded in `~/.jira_triages.json`. The agent skips
issues that haven't been updated since the last run. Reset this file to
re-process all issues from scratch.

## See Also

- [`QUICK_START.md`](QUICK_START.md) — fastest path from zero to first triage
- [Root README](../README.md) — overview of all agents
- [AGENTS.md](../AGENTS.md) — agent discovery file for AI tools
