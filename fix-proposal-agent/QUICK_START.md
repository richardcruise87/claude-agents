# Fix Proposal Agent — Quick Start

Get the agent running in a few minutes.

## Prerequisites

- Bug Triage Agent and Bug Reproduction Agent installed and have produced at
  least one `REPRODUCED` reproduction report in `~/octavia_bug_reproductions/`
- Vertex AI access configured (or another AI provider via `model_provider`)

## 1. Install

```bash
cd ~/git/claude-agents
./setup-agents.sh fix-proposal
```

Or manually:

```bash
pip install -e fix-proposal-agent/
```

## 2. Configure

```bash
cp fix-proposal-agent/config.sample.json fix-proposal-agent/config.json
```

Minimum settings to check in `config.json`:

```json
{
  "devstack_path": "/opt/stack"
}
```

Everything else defaults to sensible values. All external integrations (Launchpad
posting, Gerrit push) are **off by default**.

## 3. Run

```bash
octavia-propose-fix
```

The agent finds the newest unprocessed `REPRODUCED` bug and generates a proposal.

## 4. Read the proposal

```bash
ls -lt ~/octavia_fix_proposals/fix_proposal_*.md | grep -v context
```

Open the most recent file and review:
- **Risk Rating** (LOW / MEDIUM / HIGH) at the top
- **Proposed Patch** — the actual diff to apply
- **Why This Fix** — AI explanation of root cause and fix rationale
- **Your Options** — accept, use Claude Code, or self-fix

## 5. Act on the proposal

### Accept the fix

Apply the patch directly:

```bash
cd /opt/stack/octavia   # or wherever the repo lives
git apply < /path/to/the.patch
git review             # submit to Gerrit
```

Or copy the diff from the proposal and apply it manually.

### Use Claude Code

Open the context packet in any editor:

```bash
cat ~/octavia_fix_proposals/fix_proposal_<N>_context.md
```

Paste its contents into Claude Code and work on the fix independently.

### Request a revision

Write feedback to the feedback file:

```bash
cat > ~/octavia_fix_proposals/fix_proposal_<bug_number>_feedback.txt << 'EOF'
The fix is too broad — it changes the default VNIC type which may affect
other network paths. Please scope the fix to only the VIP network lookup.
EOF
```

Then run the agent again:

```bash
octavia-propose-fix
```

The agent reads and deletes the feedback file and generates a revised proposal
(`_2.md`).

## 6. Enable automation (optional)

```bash
./setup-agents.sh --systemd fix-proposal

# Enable daily 15:00 timer
systemctl --user enable --now octavia-fix-proposal.timer

# Monitor logs
tail -f ~/octavia-logs/octavia-fix-proposal.log
```

## Common issues

| Problem | Solution |
|---------|----------|
| "No REPRODUCED reports found" | Run `octavia-reproduce-bugs` first |
| "repo not found at /opt/stack/octavia" | Set `devstack_path` in config.json |
| Agent proposes same bug again | Check `~/.octavia_fix_proposals.json` — may need to clear the entry |
| Patch doesn't apply cleanly | Fetch latest changes: `cd /opt/stack/octavia && git pull` |
