# Claude Agents

Collection of AI agents powered by Claude via Google Vertex AI.

## Agents

### [Code Review Agent](code-review-agent/)

AI-powered code review agent for OpenStack Octavia projects on OpenDev.

**Features:**
- 🔍 Monitors OpenDev for new changes
- 🧪 Runs unit, functional, and style tests
- 📊 Performs comprehensive code analysis
- 📝 Generates detailed review documents
- ⚖️ Provides recommendations and verdicts

**Quick start:**
```bash
cd code-review-agent
./review_single_change.py <change_number>
```

**Documentation:** [code-review-agent/README.md](code-review-agent/README.md)

---

## About

These agents use the [Claude Agent SDK](https://docs.anthropic.com/en/docs/build-with-claude/agent-sdk) to perform autonomous, multi-step tasks.

**Technology:**
- Claude models via Google Vertex AI
- Python 3.8+
- Claude Agent SDK

## Setup

Each agent has its own setup requirements. See individual agent directories for details.

**Global prerequisites:**
- Python 3.8+
- Claude Agent SDK: `pip install claude-agent-sdk`
- Vertex AI access: `export CLAUDE_CODE_USE_VERTEX=1`
- Google Cloud credentials configured

## Adding New Agents

Create a new directory under `claude-agents/` with:
- `README.md` - Agent documentation
- Python scripts - Agent implementation
- Configuration files - Agent settings
- `.gitignore` - Ignore patterns

## License

Custom tools for personal/team use. Modify as needed.
