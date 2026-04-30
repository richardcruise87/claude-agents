#!/usr/bin/env python3
"""
Review a specific Octavia change from OpenDev.

Usage:
    python review_single_change.py <change_number> [patchset]
    python review_single_change.py 912345
    python review_single_change.py 912345 2
    python review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345
    python review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345 3
"""
import asyncio
import sys
import re
import argparse
from datetime import datetime
from pathlib import Path
# Add current directory to path to import config
sys.path.insert(0, str(Path(__file__).parent))
from config import load_config
from patchset_tracker import (
    prepare_review_context,
    create_review_filename,
)
from prompts import get_code_review_prompt
from agents_lib import (
    check_repo_on_main_branch,
    checkout_main_branch,
    create_model_client,
    format_usage_info,
)

# Load configuration
CONFIG = load_config()
DEVSTACK_PATH = CONFIG["devstack_path"]
REVIEWS_OUTPUT_DIR = CONFIG["reviews_output_dir"]
GERRIT_BASE_URL = CONFIG["gerrit_base_url"]


async def review_specific_change(change_url_or_number, requested_patchset=None):
    """
    Review a specific change by URL or change number.

    Args:
        change_url_or_number: Change number or Gerrit URL
        requested_patchset: Optional specific patchset number to review (e.g., 2)
                          If None, reviews the latest patchset
    """

    # Parse change number from URL or direct number
    if "review.opendev.org" in change_url_or_number:
        # Extract from URL like: https://review.opendev.org/c/openstack/octavia/+/912345
        match = re.search(r'/c/([^/]+/[^/]+)/\+/(\d+)', change_url_or_number)
        if not match:
            print(f"❌ Could not parse URL: {change_url_or_number}")
            return
        repo_name = match.group(1)
        change_number = match.group(2)
    else:
        # Assume it's just a change number - need to find which repo
        change_number = change_url_or_number.strip()
        print(f"🔍 Looking up change {change_number}...")

        # Fetch change details from Gerrit
        _client = create_model_client(CONFIG)
        _r = await _client.query(
            prompt="""
            Fetch the change details from Gerrit API:
            {GERRIT_BASE_URL}/changes/{change_number}

            Extract the project/repository name from the response.
            Return ONLY the repository name in format: openstack/project-name
            Note: Gerrit prepends ")]]}}'" to JSON - strip it.
            """,
            tools=["WebFetch"],
        )
        repo_name = None
        result_text = _r.text.strip()
        match = re.search(r'(openstack/[\w-]+)', result_text)
        if match:
            repo_name = match.group(1)
        if not repo_name:
            print(f"❌ Could not determine repository for change {change_number}")
            print(f"Response: {_r.text}")
            return

    print(f"\n{'='*80}")
    print("📋 Change Details:")
    print(f"  Repository: {repo_name}")
    print(f"  Change Number: {change_number}")
    print(f"  URL: {GERRIT_BASE_URL}/c/{repo_name}/+/{change_number}")
    print(f"{'='*80}\n")

    # Create output directory
    output_dir = Path(REVIEWS_OUTPUT_DIR)
    output_dir.mkdir(exist_ok=True, parents=True)

    # Fetch patchset number from Gerrit
    if requested_patchset:
        print(f"🔍 Fetching patchset {requested_patchset} information from Gerrit...")
        current_patchset = requested_patchset
        # Construct the ref for the specific patchset
        # Format: refs/changes/NN/NNNN/P where last NN are last 2 digits of change
        last_two = str(change_number)[-2:]
        patchset_ref = f"refs/changes/{last_two}/{change_number}/{requested_patchset}"
        print(f"✓ Patchset: {current_patchset} (requested)")
        print(f"✓ Ref: {patchset_ref}")
    else:
        print("🔍 Fetching latest patchset information from Gerrit...")
        current_patchset = None
        patchset_ref = None

        _r2 = await _client.query(
            prompt="""
            Fetch the change details from Gerrit API:
            {GERRIT_BASE_URL}/changes/{change_number}?o=CURRENT_REVISION&o=ALL_REVISIONS

            Extract:
            1. The current revision number (latest patchset number)
            2. The git ref for fetching (refs/changes/.../...)
            3. All available patchset numbers

            Return as JSON with keys: patchset_number, ref, all_patchsets
            Note: Gerrit prepends ")]]}}'" to JSON - strip it.
            The patchset number is under revisions -> _number field.
            """,
            tools=["WebFetch"],
        )
        result_text = _r2.text.strip()
        try:
            import json as _json
            if 'patchset_number' in result_text:
                data = _json.loads(result_text)
                current_patchset = data.get('patchset_number')
                patchset_ref = data.get('re')
            else:
                match = re.search(r'"_number":\s*(\d+)', result_text)
                if match:
                    current_patchset = int(match.group(1))
                match = re.search(r'"re":\s*"([^"]+)"', result_text)
                if match:
                    patchset_ref = match.group(1)
        except Exception:
            pass
        if current_patchset:
            print(f"✓ Patchset: {current_patchset} (latest)")
        if patchset_ref:
            print(f"✓ Ref: {patchset_ref}")

    # Check for previous reviews and prepare context
    previous_review_content, previous_patchset, _old_review_file = prepare_review_context(
        output_dir, repo_name, change_number, current_patchset
    )

    # Create the new review filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_file = create_review_filename(
        output_dir, repo_name, change_number, current_patchset, timestamp
    )

    print(f"📄 Review will be saved to: {review_file.name}\n")

    repo_path = Path(DEVSTACK_PATH) / repo_name.split('/')[-1]

    if not repo_path.exists():
        print(f"❌ Repository not found at: {repo_path}")
        print("   Please ensure DevStack is set up correctly.")
        return

    # Pre-flight checks
    print("🔍 Running pre-flight checks...\n")

    # Check repository is on main/master branch
    devstack_config = CONFIG.get("devstack", {})
    if devstack_config.get("verify_main_branch", True):
        print("📋 Checking repository branch...")
        branch_check = check_repo_on_main_branch(repo_path)
        if not branch_check.on_main:
            print(f"   ⚠️  {branch_check.error}")
            print(f"   Current branch: {branch_check.current_branch}")
            print("   Attempting to checkout main/master...")
            success, message = checkout_main_branch(repo_path)
            if success:
                print(f"   ✅ {message}")
            else:
                print(f"   ❌ {message}")
                print("   Review will proceed but may have issues")
        else:
            print(f"   ✅ On {branch_check.current_branch} branch")

    print("\n" + "="*80 + "\n")

    # Build the prompt with previous review context if available
    previous_review_section = ""
    if previous_review_content and previous_patchset:
        previous_review_section = """

## IMPORTANT: Previous Review Context

This change has been reviewed before. You previously reviewed **Patchset {previous_patchset}**.

**Previous Review Summary** (for context):
```
{previous_review_content[:3000]}
... (truncated for brevity)
```

**Your Task for This Review:**
- Focus on what changed between PS {previous_patchset} and PS {current_patchset or 'current'}
- Note if previous issues were addressed
- Identify new issues introduced in this patchset
- Comment on whether the change is moving in the right direction
- Include a "Changes Since Previous Review" section

"""
    elif previous_review_content:
        previous_review_section = """

## IMPORTANT: Previous Review Context

This change has been reviewed before.

**Previous Review Summary** (for context):
```
{previous_review_content[:3000]}
... (truncated for brevity)
```

**Your Task for This Review:**
- Note if previous issues were addressed
- Identify any new issues
- Include a "Changes Since Previous Review" section if you can determine what changed

"""

    # Add note if reviewing a specific (potentially not latest) patchset
    specific_patchset_note = ""
    if requested_patchset:
        specific_patchset_note = (
            f"\n**NOTE**: You are reviewing a SPECIFIC patchset (PS {requested_patchset}), "
            "which may not be the latest version of this change.\n"
        )

    # Load and format the code review prompt from template
    _provider = CONFIG.get("model_provider", "anthropic")
    prompt = get_code_review_prompt(
        repo_name=repo_name,
        change_number=change_number,
        current_patchset=current_patchset,
        gerrit_base_url=GERRIT_BASE_URL,
        repo_path=repo_path,
        patchset_ref=patchset_ref,
        specific_patchset_note=specific_patchset_note,
        previous_review_section=previous_review_section,
        previous_patchset=previous_patchset,
        provider=_provider,
        save_path=str(review_file),
    )

    # Prompt loaded from prompts/code_review_prompt.txt
    # This keeps the code clean and makes the prompt easier to maintain and edit.

    print("🤖 Starting comprehensive code review...\n")

    review_result = None
    usage_info = None
    try:
        _result = await _client.query(
            prompt=prompt,
            tools=["Bash", "Read", "Write", "Grep", "Glob"],
            on_progress=lambda text: print(f"  {text}"),
        )
        review_result = _result.text
        usage_info = format_usage_info(
            usage_data=_result.usage,
            cost_usd=_result.cost_usd,
            model=_result.model,
            duration_ms=_result.duration_ms,
        )

        print(f"\n{'='*80}")
        print("✅ Review Complete!")
        print(f"{'='*80}")
        print(f"\n📄 Review Document: {review_file}")
        print(f"\nSummary:\n{(review_result or '')[:500]}...")

        # Append usage info to review if available
        if review_result and usage_info:
            review_result = review_result + "\n\n---\n\n" + usage_info

        # Ensure the review file was created
        if not review_file.exists() and review_result:
            print("\n⚠️  Review file not found - saving result now...")
            review_file.write_text(review_result)
            print(f"✓ Saved review to: {review_file}")
        elif not review_file.exists():
            print("\n❌ WARNING: Review file was not created and no result received!")
            return
        else:
            # If file exists but we have usage info, append it
            if usage_info:
                existing_content = review_file.read_text()
                # Only append if not already present
                if "## Token Usage & Cost" not in existing_content:
                    review_file.write_text(existing_content + "\n\n---\n\n" + usage_info)
            print(f"\n✓ Review file confirmed at: {review_file}")

    except Exception as e:
        print(f"\n❌ Error during review: {e}")
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(
        description='Review an OpenStack Octavia change from OpenDev',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Review latest patchset
  %(prog)s 919846

  # Review specific patchset
  %(prog)s 919846 2
  %(prog)s 919846 --patchset 3

  # Review using URL
  %(prog)s https://review.opendev.org/c/openstack/octavia/+/919846

  # Review specific patchset using URL
  %(prog)s https://review.opendev.org/c/openstack/octavia/+/919846 2
        """
    )

    parser.add_argument(
        'change',
        help='Change number or Gerrit URL (e.g., 919846 or https://review.opendev.org/c/openstack/octavia/+/919846)'
    )

    parser.add_argument(
        'patchset',
        nargs='?',
        type=int,
        default=None,
        help='Specific patchset number to review (e.g., 2). If omitted, reviews the latest patchset.'
    )

    parser.add_argument(
        '--patchset', '-p',
        dest='patchset_flag',
        type=int,
        help='Alternative way to specify patchset number'
    )

    args = parser.parse_args()

    # Determine which patchset to use (positional arg takes precedence)
    patchset = args.patchset if args.patchset else args.patchset_flag

    if patchset:
        print(f"📌 Reviewing patchset {patchset}\n")

    asyncio.run(review_specific_change(args.change, patchset))


def cli_main():
    """Main entry point for command-line usage."""
    main()


if __name__ == "__main__":
    cli_main()
