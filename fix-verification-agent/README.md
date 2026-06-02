# Fix Verification Agent

Applies proposed fixes to OpenStack Octavia bugs and re-runs the confirmed
reproduction script to verify whether the fix actually resolves the bug.

## How it fits in the pipeline

```
Bug Triage Agent
       ↓
Bug Reproduction Agent  ──── confirms bug + saves reproduction script
       ↓
Fix Proposal Agent      ──── generates a candidate patch
       ↓
Fix Verification Agent  ──── applies patch, re-runs script, classifies result
       ↓
Fix Proposal Agent      ◄─── feedback loop: refine patch if NOT_RESOLVED
```

## Verification outcomes

| Status | Meaning |
|--------|---------|
| `RESOLVED` | Patch applied; bug no longer triggers — fix candidate |
| `NOT_RESOLVED` | Patch applied; bug still triggers — fix needs revision |
| `ENVIRONMENTAL_ERROR` | Infrastructure issue prevented a verdict; will retry automatically |
| `PATCH_ERROR` | Patch could not be applied cleanly |

`ENVIRONMENTAL_ERROR` verifications are automatically retried on the next
scheduled run (tracked via `retry_on_recovery` in the tracking file).

## Installation

```bash
# Create and activate a virtual environment
python3 -m venv ~/.venv/claude-agents
source ~/.venv/claude-agents/bin/activate

# Install (editable)
pip install -e .
# Or run the setup script which also installs the other agents:
./install.sh
```

Installed command: `octavia-verify-fix`

## Configuration

Copy the sample config and edit it:

```bash
cp config.sample.json config.json
```

Key fields:

| Field | Default | Description |
|-------|---------|-------------|
| `fix_proposals_dir` | `~/octavia_fix_proposals` | Where fix proposals are read from |
| `reproduction_reports_dir` | `~/octavia_bug_reproductions` | Where reproduction scripts live |
| `verifications_output_dir` | `~/octavia_fix_verifications` | Where verification reports are written |
| `verification.max_attempts` | `3` | Retry attempts for ENVIRONMENTAL failures |
| `verification.script_timeout` | `600` | Script execution timeout (seconds) |
| `verification.retry_delay_seconds` | `60` | Delay between retries |
| `feedback.post_to_launchpad` | `false` | Post results as Launchpad comments |

### Launchpad feedback credentials

Set these environment variables (or add them to
`~/.config/claude-agents/credentials.env`):

```bash
export LAUNCHPAD_CONSUMER_KEY="..."
export LAUNCHPAD_ACCESS_TOKEN="..."
export LAUNCHPAD_ACCESS_TOKEN_SECRET="..."
```

## Usage

### Automated mode (default)

Watches `fix_proposals_dir` for new fix proposal `.md` files written by the
Fix Proposal Agent and processes them:

```bash
octavia-verify-fix
```

### Manual modes

```bash
# Verify using a local patch file
octavia-verify-fix --bug 2148461 --patch /path/to/fix.patch

# Verify using a local branch
octavia-verify-fix --bug 2148461 --branch fix/my-branch

# Verify using a Gerrit change number
octavia-verify-fix --bug 2148461 --gerrit 990312

# Verify when the fix is already applied to the local repo
octavia-verify-fix --bug 2148461 --already-applied

# Re-post an existing report to Launchpad without re-running
octavia-verify-fix --bug 2148461 --post-only
```

## Output

For each verified proposal the agent writes:

### Verification report

`~/octavia_fix_verifications/verification_{bug}_..._{seq}.md`

Contains: status, patch description, per-attempt script output, AI failure
analysis, and recommendations.

### Feedback file

`~/octavia_fix_proposals/fix_proposal_{bug}_feedback.txt`

Written when the fix was NOT_RESOLVED. The Fix Proposal Agent reads this on
its next run to generate a revised patch.

### Launchpad comment

Posted to the bug when `feedback.post_to_launchpad` is `true` (requires OAuth
credentials).

## Systemd automation

```bash
# Enable the daily timer (runs at 17:00)
systemctl --user enable --now fix-verification-agent/systemd/octavia-fix-verification.timer

# Run once immediately
systemctl --user start octavia-fix-verification.service

# View logs
journalctl --user -u octavia-fix-verification.service -f

# Check timer schedule
systemctl --user list-timers octavia-fix-verification.timer
```

Logs are also written to `~/octavia-logs/octavia-fix-verification.log`.
