# Fix Proposal Agent

An AI-powered agent that reads confirmed-REPRODUCED bug triage and reproduction
reports, generates a targeted code fix, rates its risk, and presents the
developer with a structured proposal.

## Overview

This agent is the fourth stage of the automated bug pipeline:

1. **Bug Triage Agent** — analyses the bug, identifies root cause, sketches a fix strategy
2. **Bug Reproduction Agent** — confirms the bug is reproducible in a live DevStack environment
3. **Fix Proposal Agent** — generates a concrete patch with risk assessment ← this agent
4. **Developer** — reviews the proposal and decides whether to accept, refine, or self-fix

## Features

- Only proposes fixes for bugs confirmed `REPRODUCED` by the Bug Reproduction Agent
- AI reads triage + reproduction reports, examines source code, and generates a minimal patch
- Structured **risk rating** across four dimensions (LOW / MEDIUM / HIGH):
  - **Scope** — files/lines changed, core vs peripheral code, API surface
  - **Confidence** — reproduction certainty, root cause clarity
  - **Test coverage** — existing tests, whether the fix adds tests
  - **Domain** — security paths, DB migrations, amphora protocol
- Writes a proposal document with the patch embedded
- Writes a **Claude Code context packet** — a ready-to-paste prompt for independent work
- **Feedback loop** — developer writes feedback to a local file; agent refines on next run
- Optional: post proposal summary to Launchpad bug (off by default)
- Optional: push patch to Gerrit as a WIP draft change (off by default)
- Optional: read feedback from Launchpad comments or Gerrit review comments (off by default)

## Installation

### Using setup-agents.sh (recommended)

```bash
cd ~/git/claude-agents
./setup-agents.sh fix-proposal             # install this agent only
./setup-agents.sh --systemd fix-proposal   # also install systemd timer
./setup-agents.sh --update fix-proposal    # update to latest version
```

### Standalone

```bash
cd ~/git/claude-agents/fix-proposal-agent
pip install -e .
```

This installs the `octavia-propose-fix` command into the active Python environment.

## Configuration

```bash
cp config.sample.json config.json
vim config.json
```

Key settings:

| Key | Default | Description |
|-----|---------|-------------|
| `triage_reports_dir` | `~/octavia_bug_triages` | Where to find triage reports |
| `reproduction_reports_dir` | `~/octavia_bug_reproductions` | Where to find reproduction reports |
| `proposals_output_dir` | `~/octavia_fix_proposals` | Where to save proposals |
| `max_proposals_per_run` | `2` | Proposals generated per run |
| `cutoff_date` | 30 days ago | Ignore bugs older than this |
| `gerrit.push_wip_draft` | `false` | Push patch to Gerrit as WIP |
| `gerrit.remote_name` | `"gerrit"` | Git remote name for Gerrit pushes |
| `feedback.post_to_launchpad` | `false` | Post summary to Launchpad bug |
| `feedback.read_launchpad_comments` | `false` | Read developer feedback from Launchpad |
| `feedback.read_gerrit_comments` | `false` | Read reviewer feedback from Gerrit WIP |

## Usage

### Manual Execution

```bash
octavia-propose-fix
```

### Automated with systemd

```bash
# Enable daily timer (fires at 15:00, after triage and reproduction agents)
systemctl --user enable octavia-fix-proposal.timer
systemctl --user start octavia-fix-proposal.timer

# Run manually
systemctl --user start octavia-fix-proposal.service

# View logs
tail -f ~/octavia-logs/octavia-fix-proposal.log
```

## Output

Two files are written per proposal:

### Proposal document

`~/octavia_fix_proposals/fix_proposal_<bug_number>_<title>_<timestamp>_<seq>.md`

```markdown
# Fix Proposal: Bug #2150752 — Loadbalancer KeyError when adding a member

**Risk Rating**: LOW
**Confidence**: HIGH
**Scope**: 1 file changed, ~5 lines
**Reproduction Status**: REPRODUCED

## Proposed Patch
```diff
--- a/octavia/controller/worker/v2/tasks/network_tasks.py
+++ b/octavia/controller/worker/v2/tasks/network_tasks.py
@@ -125,7 +125,7 @@
-        vnic_type = net_vnic_type_map[add_net_id]
+        vnic_type = net_vnic_type_map.get(add_net_id, 'normal')
```

## Why This Fix
...

## Risk Assessment
...

## Your Options
- Accept AI fix — apply the patch above
- Use Claude Code — context packet at: ~/octavia_fix_proposals/fix_proposal_2150752_context.md
- Write your own fix
- Reject
```

### Claude Code context packet

`~/octavia_fix_proposals/fix_proposal_<bug_number>_context.md`

A complete prompt ready to paste into Claude Code, containing the root cause,
reproduction status, AI proposed fix, risk rating, and relevant file paths.

## Developer Feedback Loop

To request a revised proposal:

1. Write your feedback to:
   ```
   ~/octavia_fix_proposals/fix_proposal_{bug_number}_feedback.txt
   ```
2. Run the agent (or wait for the next scheduled run):
   ```bash
   octavia-propose-fix
   ```
3. The agent reads and deletes the feedback file, then generates a revised
   proposal with sequence number incremented (e.g., `_2.md`, `_3.md`).

Feedback can also be provided via Launchpad comments or Gerrit review comments
on a pushed WIP draft — enable via `feedback.read_launchpad_comments` and
`feedback.read_gerrit_comments` in config.

## Tracking

Tracking file: `~/.octavia_fix_proposals.json`

```json
{
  "fix_2150752": {
    "last_processed": "2026-05-07T15:00:22.123456",
    "last_updated": "2026-05-05T09:11:09",
    "sequence": 1,
    "proposal_file": "~/octavia_fix_proposals/fix_proposal_2150752_..._1.md",
    "status": "proposed"
  }
}
```

Status values: `proposed` | `accepted` | `rejected` | `human-fix`

## Integration with Other Agents

The Fix Proposal Agent sits between the Bug Reproduction Agent and the developer:

```
Bug Triage Agent  ──►  ~/octavia_bug_triages/
                              │
                              ▼ (inotify)
Bug Reproduction Agent ──►  ~/octavia_bug_reproductions/
                              │
                              ▼ (daily timer, 15:00)
Fix Proposal Agent     ──►  ~/octavia_fix_proposals/
                              │
                              ▼ (notification → developer)
Developer decides: accept / Claude Code / self-fix / reject
```

When `feedback.read_gerrit_comments: true` is enabled and `gerrit.push_wip_draft: true`
is used, the Code Review Agent can indirectly feed back: a reviewer comments on the
Gerrit WIP draft → Fix Proposal Agent reads it on the next run → revised proposal.
