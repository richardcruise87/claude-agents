# Token Usage & Cost Tracking - Implementation Summary

**Date:** 2026-04-01
**Status:** ✅ Complete

## Overview

Added comprehensive token usage and cost tracking to all three agents. Each report now includes detailed information about:
- Token counts (input, output, cache creation, cache read)
- Total cost in USD
- Model used
- Duration of AI processing

## Changes Made

### 1. Shared Library (`agents_lib`)

**New Function:** `format_usage_info()`
- Location: `agents_lib/agents_lib/utils.py`
- Exports: Added to `agents_lib/__init__.py`

**Features:**
- Formats token usage data in consistent markdown format
- Handles all token types (input, output, cache creation, cache read)
- Displays cost in USD with 6 decimal precision
- Shows model name and duration
- Gracefully handles missing data

**Example Output:**
```markdown
## Token Usage & Cost

**Model:** `claude-sonnet-4-5-20250929`
**Duration:** 15.00s

### Token Usage

- **Input tokens:** 10,000
- **Cache creation tokens:** 5,000
- **Cache read tokens:** 1,000
- **Output tokens:** 2,000
- **Total tokens:** 18,000

### Cost

**Total Cost:** $0.045000 USD
```

### 2. Bug Triage Agent

**Updated Files:**
- `bug-triage-agent/bug_triage_agent.py`
- `bug-triage-agent/prompts/bug_triage_prompt.txt`

**Changes:**
- Captures usage data from `ResultMessage` after AI query completes
- Appends token usage section to triage report
- Only appends if not already present (idempotent)
- Prompt template updated to note automatic usage tracking

**Usage Data Captured:**
- Token counts from `message.usage`
- Cost from `message.total_cost_usd`
- Model from `message.model`
- Duration from `message.duration_ms`

### 3. Code Review Agent

**Updated Files:**
- `code-review-agent/review_single_change.py`
- `code-review-agent/prompts/code_review_prompt.txt`

**Changes:**
- Captures usage data from `ResultMessage` after review completes
- Appends token usage section to review document
- Only appends if not already present (idempotent)
- Prompt template updated to note automatic usage tracking

**Implementation:**
Same pattern as bug triage agent - captures and formats usage info after AI completes the review.

### 4. Bug Reproduction Agent

**Updated Files:**
- `bug-reproduction-agent/script_generator.py`
- `bug-reproduction-agent/report_generator.py`
- `bug-reproduction-agent/bug_reproduction_agent.py`

**Changes:**

#### `script_generator.py`:
- `generate_initial_script()` now returns `(script, usage_dict)` tuple
- `refine_script()` now returns `(script, usage_dict)` tuple
- Each AI call captures its own usage data

#### `bug_reproduction_agent.py`:
- Tracks usage across all attempts (initial + refinements)
- Accumulates total token counts and costs
- Stores usage info with each attempt: `(script, result, usage_dict)`

#### `report_generator.py`:
- Accepts `total_usage` parameter
- Displays usage for each individual attempt
- Displays total usage across all attempts at end of report
- Handles both old format (2-tuple) and new format (3-tuple) for backward compatibility

**Report Structure:**
```markdown
## Reproduction Attempts

### Attempt 1
... execution details ...

#### Token Usage (Attempt 1)
- Input tokens: 5,000
- Output tokens: 1,200
- Total Cost: $0.015 USD

**Script Used:**
...

---

### Attempt 2
... execution details ...

#### Token Usage (Attempt 2)
- Input tokens: 6,000
- Output tokens: 1,500
- Total Cost: $0.018 USD

**Script Used:**
...

---

## Total Token Usage & Cost

**Model:** `claude-sonnet-4-5-20250929`
**Duration:** 30.00s

### Token Usage

- **Input tokens:** 11,000
- **Output tokens:** 2,700
- **Total tokens:** 13,700

### Cost

**Total Cost:** $0.033000 USD
```

## Technical Implementation

### SDK Message Attributes

The Claude Agent SDK provides usage information on `ResultMessage` objects:

```python
async for message in query(prompt=prompt, options=options):
    if hasattr(message, 'result'):
        # Message attributes available:
        # - message.usage: Dict with token counts
        # - message.total_cost_usd: Float with total cost
        # - message.model: String with model name
        # - message.duration_ms: Int with duration in milliseconds
```

### Usage Data Structure

```python
usage_dict = {
    'usage': {
        'input_tokens': 10000,
        'output_tokens': 2000,
        'cache_creation_input_tokens': 5000,
        'cache_read_input_tokens': 1000,
    },
    'cost_usd': 0.045,
    'model': 'claude-sonnet-4-5-20250929',
    'duration_ms': 15000,
}
```

## Testing

### Manual Test

```bash
# Test the format_usage_info function
python3 -c "
from agents_lib import format_usage_info

usage_data = {
    'input_tokens': 10000,
    'output_tokens': 2000,
    'cache_creation_input_tokens': 5000,
    'cache_read_input_tokens': 1000
}

result = format_usage_info(
    usage_data=usage_data,
    cost_usd=0.045,
    model='claude-sonnet-4-5-20250929',
    duration_ms=15000
)

print(result)
"
```

### Integration Testing

To verify the changes work end-to-end:

1. **Bug Triage Agent:**
   ```bash
   cd bug-triage-agent
   # Set to process only 1 bug for testing
   export MAX_BUGS=1
   ./bug_triage_agent.py
   # Check latest triage file for "## Token Usage & Cost" section
   ```

2. **Code Review Agent:**
   ```bash
   cd code-review-agent
   ./review_single_change.py <change_number>
   # Check review file for "## Token Usage & Cost" section
   ```

3. **Bug Reproduction Agent:**
   ```bash
   cd bug-reproduction-agent
   # Place a triage file in the monitored directory
   ./bug_reproduction_agent.py
   # Check reproduction report for usage sections
   ```

## Backward Compatibility

### Bug Reproduction Agent

The report generator handles both old and new format:

```python
# Old format (existing reports won't break)
attempts = [(script, result), ...]

# New format (with usage tracking)
attempts = [(script, result, usage_dict), ...]
```

Code automatically detects which format and processes accordingly.

### Other Agents

Changes are purely additive - appending usage info to reports. No existing functionality is affected.

## Benefits

1. **Cost Tracking:** Teams can monitor AI usage costs per triage/review/reproduction
2. **Performance Monitoring:** Duration tracking shows how long AI operations take
3. **Token Optimization:** Identify high-token operations for optimization
4. **Transparency:** Users see exactly what each AI operation cost
5. **Budgeting:** Historical data helps with budget planning
6. **Cache Effectiveness:** See how much benefit comes from prompt caching

## Future Enhancements

Possible future improvements:

1. **Aggregate Statistics:**
   - Daily/weekly cost summaries
   - Average tokens per bug/review
   - Cache hit rates

2. **Cost Alerts:**
   - Warning if single operation exceeds threshold
   - Daily budget notifications

3. **Database Tracking:**
   - Store usage data in SQLite
   - Query historical patterns
   - Generate cost reports

4. **Dashboard:**
   - Web interface for viewing costs
   - Graphs and trends
   - Cost projections

## Files Modified

```
agents_lib/
├── agents_lib/
│   ├── __init__.py          # Added format_usage_info export
│   └── utils.py             # Added format_usage_info function

bug-triage-agent/
├── bug_triage_agent.py      # Capture and append usage
└── prompts/
    └── bug_triage_prompt.txt # Note about automatic tracking

code-review-agent/
├── review_single_change.py  # Capture and append usage
└── prompts/
    └── code_review_prompt.txt # Note about automatic tracking

bug-reproduction-agent/
├── bug_reproduction_agent.py # Track total usage across attempts
├── script_generator.py      # Return usage with scripts
└── report_generator.py      # Include usage in reports
```

## Installation

The agents_lib package needs to be reinstalled for the changes to take effect:

```bash
cd agents_lib
pip install -e .
```

Systemd services will automatically use the updated code on next run.

## Conclusion

Token usage and cost tracking is now fully integrated across all three agents. Each report provides complete transparency about AI usage, enabling better cost management and performance monitoring.

---

*Implementation completed: 2026-04-01*
