# Octavia Code Review Agent

AI-powered code review agent for OpenStack Octavia using Claude via Google Vertex AI.

Automatically monitors OpenDev for new changes, downloads them to your local DevStack, runs comprehensive tests, analyzes code quality, and generates detailed review documents.

## Features

- 🔍 **Monitors OpenDev** for new Octavia changes
- ⬇️ **Downloads changes** to local DevStack environment
- 🧪 **Runs tests**: Unit tests, functional tests, PEP8 linting
- 📊 **Code analysis**: Security, performance, breaking changes, documentation
- 📝 **Generates reviews**: Comprehensive markdown documents with recommendations
- 🎯 **Categorized issues**: Critical, Major, Minor, Nit with file:line references
- ⚖️ **Final verdict**: Approve/Request Changes/Needs Discussion
- 🔄 **Patchset tracking**: Incremental reviews that compare with previous patchsets
- 📚 **Review history**: Preserves all previous reviews with proper versioning

## Prerequisites

### Required

1. **Python 3.8+**
2. **Claude Agent SDK**
   ```bash
   pip install claude-agent-sdk
   ```

3. **Google Cloud Vertex AI Access**
   - Enable Vertex AI API in your GCP project
   - Set up authentication (see below)

4. **DevStack** with Octavia repositories cloned

### Optional

- **git** - For fetching changes
- **tox** - For running tests (or configure custom test commands)

## Quick Start

### 1. Clone the Repository

```bash
git clone <repository-url>
cd code-review-agent
```

### 2. Run Installation Script

```bash
chmod +x install.sh
./install.sh
```

This will:
- Install the Claude Agent SDK
- Create `config.json` from `config.sample.json`
- Help you configure basic settings
- Set up the output directory

### 3. Configure Vertex AI

Set the environment variable:
```bash
export CLAUDE_CODE_USE_VERTEX=1
```

Configure Google Cloud credentials (choose one):

**Option A: Application Default Credentials** (Recommended)
```bash
gcloud auth application-default login
```

**Option B: Service Account**
```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
```

**Make it persistent** by adding to `~/.bashrc` or `~/.zshrc`:
```bash
echo 'export CLAUDE_CODE_USE_VERTEX=1' >> ~/.bashrc
```

### 4. Edit Configuration

Edit `config.json` to match your environment:

```json
{
  "devstack": {
    "path": "/opt/stack"  // ← Your DevStack location
  },
  "output": {
    "reviews_directory": "~/octavia_reviews"  // ← Where to save reviews
  },
  "repositories": [
    "openstack/octavia",
    "openstack/octavia-lib",
    // ... add or remove repos
  ]
}
```

### 5. Verify Setup

```bash
./setup_review_agent.sh
```

### 6. Review a Change!

```bash
# By change number
./review_single_change.py 912345

# Or by URL
./review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345
```

## Usage

### Review a Specific Change

The easiest way to get started:

```bash
# Review latest patchset
./review_single_change.py <change_number>

# Review specific patchset
./review_single_change.py <change_number> <patchset>

# Examples
./review_single_change.py 919846           # Latest patchset
./review_single_change.py 919846 2         # Patchset 2
./review_single_change.py 919846 -p 3      # Patchset 3 (alternative)
```

**Reviewing Specific Patchsets:**

You can review any patchset, not just the latest. This is useful for:
- 📜 Reviewing historical patchsets for context
- 🔍 Comparing different versions
- ✅ Validating bug fixes between patchsets
- 📊 Understanding change evolution

**What it does:**
1. Fetches the change from OpenDev
2. Downloads to your local repo (git fetch)
3. Runs unit tests (`tox -e py3`)
4. Runs functional tests (`tox -e functional`)
5. Runs style checks (`tox -e pep8`)
6. Analyzes code comprehensively
7. Generates detailed review document
8. Saves to output directory

**Output:** `~/octavia_reviews/review_openstack_octavia_<number>_<timestamp>.md`

### Monitor All Repos

Check all configured repositories for new changes:

```bash
./octavia_review_agent.py
```

- Reviews up to 3 changes per repo (configurable)
- Tracks reviewed changes to avoid duplicates
- Saves all reviews to output directory

### Automated Monitoring

Set up cron for periodic monitoring:

```bash
crontab -e

# Add (runs every hour):
0 * * * * cd /path/to/code-review-agent && ./octavia_review_agent.py >> monitor.log 2>&1
```

## Patchset Tracking (Incremental Reviews)

The agent automatically tracks patchsets and provides **incremental reviews** when developers upload new versions.

### How It Works

When you review the same change multiple times:

1. **First review (PS 1)**:
   ```bash
   ./review_single_change.py 919846
   # Creates: review_openstack_octavia_919846_ps1_20260326_120000-latest.md
   # Finds 4 critical issues
   ```

2. **Developer uploads PS 2** fixing 2 issues:
   ```bash
   ./review_single_change.py 919846
   # Old review renamed: review_..._ps1_....md (removes -latest)
   # Creates: review_..._ps2_...-latest.md
   # New review includes:
   #   - ✅ Fixed: Issues 1 and 2
   #   - ❌ Still present: Issues 3 and 4
   #   - Focus on what changed
   ```

3. **Developer uploads PS 3** fixing remaining issues:
   ```bash
   ./review_single_change.py 919846
   # Old PS 2 renamed, new PS 3 created
   # Review confirms all issues resolved!
   ```

### Review File Naming

- **Current review**: `review_repo_change_ps2_timestamp-latest.md`
- **Historical reviews**: `review_repo_change_ps1_timestamp.md` (no -latest)

### Benefits

- ✅ **Don't repeat yourself** - Agent remembers previous findings
- ✅ **Focus on changes** - See only what's new
- ✅ **Track progress** - Which issues were addressed?
- ✅ **Full history** - All reviews preserved

See [PATCHSET_TRACKING.md](PATCHSET_TRACKING.md) for detailed documentation.

## Configuration

### Configuration File: `config.json`

Created from `config.sample.json` during installation. Key settings:

```json
{
  "repositories": [
    "openstack/octavia",
    // ... list of repos to monitor
  ],

  "devstack": {
    "path": "/opt/stack"  // DevStack installation path
  },

  "output": {
    "reviews_directory": "~/octavia_reviews"  // Where to save reviews
  },

  "testing": {
    "run_unit_tests": true,
    "run_functional_tests": true,
    "run_pep8": true,
    "unit_test_command": "tox -e py3",
    "functional_test_command": "tox -e functional",
    "pep8_command": "tox -e pep8"
  },

  "monitoring": {
    "max_reviews_per_cycle": 3,  // Max changes to review per run
    "reviewed_changes_file": "~/.octavia_reviewed_changes.json"
  }
}
```

### Environment Variables

Override configuration with environment variables:

```bash
export DEVSTACK_PATH=/custom/path/to/devstack
export REVIEWS_OUTPUT_DIR=/custom/output/directory
export GERRIT_URL=https://custom.gerrit.server
export MAX_REVIEWS=5
```

Environment variables take precedence over `config.json`.

## Review Document Structure

Each review generates a comprehensive markdown document:

### Change Summary
- Description, files modified, lines changed
- Commit message analysis

### Test Results
```
✅ Unit Tests: PASS (45 passed, 0 failed)
✅ Functional Tests: PASS (12 passed, 0 failed)
✅ PEP8: PASS (no violations)
```

### Code Analysis

**Issues categorized by severity:**

- 🔴 **Critical**: Must fix before merge (security, data loss, crashes)
- 🟡 **Major**: Should fix (bugs, performance, API breaks)
- 🔵 **Minor**: Nice to have (code quality, optimizations)
- 🟢 **Nit**: Style suggestions

Each issue includes:
- File path and line number
- Description of the problem
- Impact explanation
- Suggested fix (often with code)

### Testing Strategy
- Tests executed
- Recommended additional testing
- Manual test procedures

### Final Verdict
- ✅ **Approve** - Ready to merge
- 🔄 **Request Changes** - Issues must be fixed
- 💬 **Needs Discussion** - Architectural questions
- 🔍 **Needs More Information** - Clarification required

## Customization

### Custom Test Commands

Edit `config.json`:

```json
{
  "testing": {
    "unit_test_command": "pytest tests/unit",
    "functional_test_command": "./run_tests.sh",
    "pep8_command": "flake8 ."
  }
}
```

### Filter Changes

Edit the Gerrit query in `octavia_review_agent.py`:

```python
# Only review changes from specific author
gerrit_query_url = (
    f"{CONFIG['gerrit_base_url']}/changes/"
    f"?q=project:{repo_name}+status:open+owner:email@example.com"
)

# Only review changes with specific topic
gerrit_query_url = (
    f"{CONFIG['gerrit_base_url']}/changes/"
    f"?q=project:{repo_name}+status:open+topic:bug/12345"
)
```

### Review Different Projects

This agent is designed for Octavia but can be adapted for any OpenStack project:

1. Update `repositories` in `config.json`
2. Adjust test commands if needed
3. Modify review prompt for project-specific guidelines

## Files

- **`review_single_change.py`** - Review a specific change (main script)
- **`octavia_review_agent.py`** - Monitor repos for new changes
- **`config.py`** - Configuration loader
- **`config.sample.json`** - Sample configuration (copy to config.json)
- **`install.sh`** - Initial setup script
- **`setup_review_agent.sh`** - Verify setup and dependencies
- **`test_agent.py`** - Test Vertex AI connectivity
- **`README.md`** - This file
- **`QUICK_START.md`** - Quick reference guide
- **`OCTAVIA_REVIEW_README.md`** - Detailed documentation

## Troubleshooting

### "Repository not found"
- Check `devstack.path` in `config.json`
- Ensure repos are cloned: `ls $DEVSTACK_PATH/octavia`

### "Vertex AI authentication error"
- Verify: `gcloud auth application-default login`
- Check: `echo $CLAUDE_CODE_USE_VERTEX` (should be "1")
- Ensure Vertex AI API is enabled in GCP

### "Tests failed to run"
- Install tox: `pip install tox`
- Or customize test commands in `config.json`

### "Config not found"
- Run: `./install.sh` to create from sample
- Or: `cp config.sample.json config.json`

## Cost Considerations

Each comprehensive review on Vertex AI uses approximately:
- 50k-100k input tokens (code + tests + prompts)
- 10k-20k output tokens (review document)

**Tips to reduce costs:**
- Review fewer changes per cycle (`max_reviews_per_cycle`)
- Skip functional tests for minor changes
- Use filters to only review relevant changes
- Run during off-peak hours if you have time-based pricing

## Security Note

**The agent does NOT post reviews automatically.**

All reviews are saved locally as markdown files. You must:
1. Read the generated review
2. Decide what to post
3. Manually copy comments to Gerrit

This ensures human oversight of all feedback.

## Contributing

Contributions welcome! Areas for improvement:
- Support for other OpenStack projects
- Additional code analysis checks
- Integration with other CI/CD tools
- Custom review templates
- Post to Gerrit (with approval workflow)

## License

MIT License - See LICENSE file

## Support

For issues or questions:
- Check the documentation: `OCTAVIA_REVIEW_README.md`
- Test configuration: `./setup_review_agent.sh`
- Verify Vertex AI: `./test_agent.py`

## Example Workflow

```bash
# 1. Daily: Check for new changes
./octavia_review_agent.py

# 2. Read generated reviews
ls -lt ~/octavia_reviews/ | head -5
cat ~/octavia_reviews/review_openstack_octavia_*.md

# 3. Post your reviews on Gerrit
# Use the AI insights to inform your human review

# 4. Or review specific changes on demand
./review_single_change.py 923456
```

---

**Powered by Claude via Google Vertex AI**

Built with [Claude Agent SDK](https://docs.anthropic.com/en/docs/build-with-claude/agent-sdk)
