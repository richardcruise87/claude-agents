# JIRA Triage Agent — Quick Start

## 1. Install

```bash
cd ~/git/claude-agents
./setup-agents.sh --no-systemd jira-triage
```

## 2. Get a JIRA API token

Go to <https://id.atlassian.com/manage-profile/security/api-tokens>, create a
token, and export it:

```bash
export JIRA_API_TOKEN=your_token_here
```

## 3. Configure

```bash
cd jira-triage-agent
cp config.sample.json config.json
```

Edit `config.json` — the three required fields:

```json
{
  "jira": {
    "base_url": "https://yourcompany.atlassian.net",
    "email": "you@yourcompany.com",
    "jql": "project = MYPROJ AND status != Done AND updated >= -7d ORDER BY updated DESC"
  }
}
```

## 4. Run

```bash
octavia-jira-triage
```

Reports are saved to `~/jira_triages/` (bugs) and `~/jira_plans/` (stories/tasks).

---

## Common JQL examples

```
# Bugs only, past 7 days
project = PROJ AND issuetype = Bug AND status != Done AND updated >= -7d ORDER BY priority DESC

# Stories ready for development
project = PROJ AND issuetype = Story AND status = "Ready" ORDER BY priority DESC

# Everything assigned to you
assignee = currentUser() AND status not in (Done, Closed) ORDER BY updated DESC

# Specific sprint
project = PROJ AND sprint in openSprints() AND status != Done ORDER BY updated DESC
```

## Troubleshooting

**`JIRA config incomplete`** — `JIRA_API_TOKEN` env var is not set.

**`HTTP 401`** — wrong email or token. Check that `jira.email` matches the
account the token belongs to.

**`HTTP 403`** — your account doesn't have permission to read the project in
the JQL.

**`HTTP 400`** — invalid JQL syntax. Test it in the JIRA issue search UI first.

**No issues processed** — all issues were already up-to-date (in
`~/.jira_triages.json`) or the JQL returned nothing. Delete
`~/.jira_triages.json` to reprocess, or widen the JQL time range.
