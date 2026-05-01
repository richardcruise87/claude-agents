#!/usr/bin/env python3
"""
Octavia Bug Triage Agent

Monitors Launchpad for Octavia bugs, performs triage, suggests reproduction
strategies, checks for duplicates and potential fixes.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))
from config import load_config
from agents_lib import (
    build_feedback_comment,
    notify_report,
    load_notifications_config,
    create_model_client,
    format_usage_info,
)
from bug_tracker import (
    load_triage_history,
    should_triage_bug,
    record_triage,
    create_triage_filename,
    find_previous_triages,
    get_previous_triage_summary,
)
from prompts import get_bug_triage_prompt

# Load configuration
CONFIG = load_config()


# ---------------------------------------------------------------------------
# Launchpad feedback posting (OAuth 1.0a, stdlib only)
# ---------------------------------------------------------------------------

def _launchpad_auth_header(method: str, url: str,
                           consumer_key: str, access_token: str,
                           token_secret: str) -> str:
    """Build an OAuth 1.0a HMAC-SHA1 Authorization header for Launchpad.

    Launchpad uses a blank consumer secret for registered applications.
    """
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_token": access_token,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp,
        "oauth_nonce": nonce,
        "oauth_version": "1.0",
    }
    # Signature base string
    param_string = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(oauth_params.items())
    )
    base_string = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(param_string, safe=""),
    ])
    # Consumer secret is empty for Launchpad desktop/service integrations
    signing_key = f"&{urllib.parse.quote(token_secret, safe='')}"
    raw_sig = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    oauth_params["oauth_signature"] = base64.b64encode(raw_sig).decode()
    auth = "OAuth " + ", ".join(
        f'{k}="{urllib.parse.quote(v, safe="")}"' for k, v in oauth_params.items()
    )
    return auth


def _post_launchpad_comment(
    bug_id: str, subject: str, content: str,
    consumer_key: str, access_token: str, token_secret: str,
) -> bool:
    """Post a comment to a Launchpad bug via the REST API.

    Returns True on success, False on any error (logged, never raised).
    """
    url = f"https://api.launchpad.net/1.0/bugs/{bug_id}/messages"
    body = urllib.parse.urlencode({"subject": subject, "content": content}).encode("utf-8")
    auth = _launchpad_auth_header("POST", url, consumer_key, access_token, token_secret)
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", auth)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detail = ""
        print(f"⚠️  Launchpad comment failed (HTTP {exc.code}): {exc.reason} — {detail}")
        return False
    except urllib.error.URLError as exc:
        print(f"⚠️  Launchpad comment failed (network): {exc.reason}")
        return False


def _post_bug_feedback(bug_info: dict, triage_file: "Path", config: dict) -> None:
    """Post the triage report as a comment on the Launchpad bug.

    Reads OAuth credentials from env vars named in config. Errors are logged
    but never raised — a failed post must not prevent local recording.
    """
    if not config.get("feedback_enabled"):
        return
    consumer_key = os.environ.get(config.get("feedback_consumer_key_env", ""), "")
    access_token = os.environ.get(config.get("feedback_access_token_env", ""), "")
    token_secret = os.environ.get(config.get("feedback_access_token_secret_env", ""), "")
    if not all([consumer_key, access_token, token_secret]):
        print(
            "⚠️  Launchpad feedback skipped — set "
            f"{config.get('feedback_consumer_key_env')}, "
            f"{config.get('feedback_access_token_env')}, and "
            f"{config.get('feedback_access_token_secret_env')} env vars."
        )
        return
    try:
        content = triage_file.read_text(encoding="utf-8")
        model_name = config.get("model", "claude-sonnet-4-6")
        comment = build_feedback_comment(content, model_name, max_chars=5000)
        bug_id = bug_info["number"]
        subject = "AI Triage Report (automated, may contain errors)"
        print(f"\n📤 Posting comment to Launchpad bug #{bug_id}...")
        ok = _post_launchpad_comment(bug_id, subject, comment,
                                     consumer_key, access_token, token_secret)
        if ok:
            print(f"   ✅ Comment posted to bug #{bug_id}")
        else:
            print("   ⚠️  Comment post returned failure (see warning above)")
    except Exception as exc:
        print(f"   ⚠️  Could not post Launchpad feedback: {exc}")


async def fetch_bugs_from_launchpad(project: str, statuses: list, max_bugs: int = 10):
    """
    Fetch bugs from Launchpad API.

    Args:
        project: Launchpad project name (e.g., "octavia")
        statuses: List of bug statuses to fetch
        max_bugs: Maximum number of bugs to fetch

    Returns:
        List of bug dictionaries
    """
    print(f"\n🔍 Fetching bugs from Launchpad for {project}...")

    # Construct Launchpad API URL
    # Format: https://api.launchpad.net/1.0/<project>?ws.op=searchTasks&status=New&status=Confirmed
    status_params = '&'.join([f'status={s}' for s in statuses])
    launchpad_url = (
        f"{CONFIG['launchpad_api_url']}/{project}?"
        f"ws.op=searchTasks&{status_params}&order_by=-date_last_updated"
    )

    try:
        # Use httpx for async HTTP requests
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            print(f"📡 Querying: {launchpad_url}")
            response = await client.get(launchpad_url)
            response.raise_for_status()

            data = response.json()
            entries = data.get('entries', [])

            print(f"✓ Found {len(entries)} bugs")

            # Parse bug information
            bugs = []
            for entry in entries[:max_bugs]:
                bug_link = entry.get('bug_link')
                if not bug_link:
                    continue

                try:
                    # Fetch bug details
                    bug_response = await client.get(bug_link)
                    bug_response.raise_for_status()
                    bug_data = bug_response.json()

                    bug_info = {
                        'number': str(bug_data.get('id', '')),
                        'title': bug_data.get('title', 'No title'),
                        'description': bug_data.get('description', 'No description'),
                        'status': entry.get('status', 'Unknown'),
                        'importance': entry.get('importance', 'Undecided'),
                        'date_created': bug_data.get('date_created', ''),
                        'date_last_updated': entry.get('date_last_updated', ''),
                        'web_link': bug_data.get('web_link', ''),
                        'owner_link': bug_data.get('owner_link', ''),
                    }

                    # Get reporter name
                    if bug_data.get('owner_link'):
                        try:
                            owner_response = await client.get(bug_data['owner_link'])
                            owner_response.raise_for_status()
                            owner_data = owner_response.json()
                            bug_info['reporter'] = owner_data.get('display_name', 'Unknown')
                        except Exception:
                            bug_info['reporter'] = 'Unknown'
                    else:
                        bug_info['reporter'] = 'Unknown'

                    bugs.append(bug_info)

                    print(f"  - Bug #{bug_info['number']}: {bug_info['title'][:60]}...")

                except Exception as e:
                    # Skip this bug and continue with others
                    bug_num = bug_link.split('/')[-1] if bug_link else 'unknown'
                    print(f"  ⚠️  Skipping bug {bug_num}: {e}")
                    continue

            return bugs

    except ImportError:
        print("⚠️  httpx not available, using urllib...")
        try:
            with urllib.request.urlopen(launchpad_url, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                entries = data.get('entries', [])
                print(f"✓ Found {len(entries)} bugs (limited functionality)")

                # Simplified parsing without detailed bug info
                bugs = []
                for entry in entries[:max_bugs]:
                    # Extract bug number from bug_link
                    bug_link = entry.get('bug_link', '')
                    bug_number = bug_link.split('/')[-1] if bug_link else 'unknown'

                    bugs.append({
                        'number': bug_number,
                        'title': entry.get('title', 'No title'),
                        'description': 'Description unavailable (install httpx for full details)',
                        'status': entry.get('status', 'Unknown'),
                        'importance': entry.get('importance', 'Undecided'),
                        'date_created': entry.get('date_created', ''),
                        'date_last_updated': entry.get('date_last_updated', ''),
                        'web_link': f"https://bugs.launchpad.net/bugs/{bug_number}",
                        'reporter': 'Unknown',
                    })

                return bugs
        except Exception as e:
            print(f"❌ Error fetching from Launchpad: {e}")
            return []

    except Exception as e:
        print(f"❌ Error fetching from Launchpad: {e}")
        return []


async def triage_bug(bug_info: dict, sequence: int, previous_summary: str = None, previous_seq: int = None):
    """
    Perform triage on a single bug.

    Args:
        bug_info: Bug information dictionary
        sequence: Sequence number for this triage
        previous_summary: Optional summary from previous triage
        previous_seq: Previous sequence number

    Returns:
        Path to the triage file created, or None on error
    """
    bug_number = bug_info['number']
    bug_title = bug_info['title']

    print(f"\n{'='*80}")
    print(f"🐛 Triaging Bug #{bug_number} (Sequence #{sequence})")
    print(f"📋 Title: {bug_title}")
    print(f"{'='*80}\n")

    # Create output directory
    output_dir = Path(CONFIG['triages_output_dir'])
    output_dir.mkdir(exist_ok=True, parents=True)

    # Create triage filename
    triage_file = create_triage_filename(
        output_dir,
        bug_number,
        bug_title,
        sequence
    )

    print(f"📄 Triage will be saved to: {triage_file.name}\n")

    # Get the prompt
    _provider = CONFIG.get("model_provider", "anthropic")
    prompt = get_bug_triage_prompt(
        bug_number=bug_number,
        bug_title=bug_title,
        bug_status=bug_info['status'],
        bug_importance=bug_info['importance'],
        launchpad_url=bug_info['web_link'],
        date_created=bug_info['date_created'],
        date_updated=bug_info['date_last_updated'],
        reporter=bug_info['reporter'],
        bug_description=bug_info['description'],
        devstack_path=CONFIG['devstack_path'],
        triage_file=triage_file,
        sequence=sequence,
        previous_triage_summary=previous_summary,
        previous_sequence=previous_seq,
        provider=_provider,
    )

    print("🤖 Starting bug triage analysis...\n")

    triage_result = None
    usage_info = None
    try:
        _client = create_model_client(CONFIG)
        _result = await _client.query(
            prompt=prompt,
            tools=["Bash", "Read", "Write", "Grep", "Glob"],
            on_progress=lambda text: print(f"  {text}"),
        )
        triage_result = _result.text
        usage_info = format_usage_info(
            usage_data=_result.usage,
            cost_usd=_result.cost_usd,
            model=_result.model,
            duration_ms=_result.duration_ms,
        )

        print(f"\n{'='*80}")
        print("✅ Triage Complete!")
        print(f"{'='*80}")
        print(f"\n📄 Triage saved to: {triage_file}")
        print(f"\nSummary:\n{(triage_result or '')[:500]}...")

        # Append usage info to triage if available
        if triage_result and usage_info:
            triage_result = triage_result + "\n\n---\n\n" + usage_info

        # Verify triage file was created before marking as complete
        if not triage_file.exists() and triage_result:
            print("\n⚠️  Triage file not found - saving result now...")
            triage_file.write_text(triage_result)
            print(f"✓ Saved triage to: {triage_file}")
        elif not triage_file.exists():
            print("\n❌ ERROR: Triage file not found and no result received!")
            print(f"   Expected: {triage_file}")
            print("   Will retry on next pass")
            return None
        else:
            # If file exists but we have usage info, append it
            if usage_info:
                existing_content = triage_file.read_text()
                # Only append if not already present
                if "## Token Usage & Cost" not in existing_content:
                    triage_file.write_text(existing_content + "\n\n---\n\n" + usage_info)
            print(f"\n✓ Triage file confirmed at: {triage_file}")

        # Record that we triaged this bug (only after confirming file exists)
        tracking_file = Path(CONFIG['triage_tracking_file'])
        record_triage(
            tracking_file,
            bug_number,
            bug_info['date_last_updated'],
            sequence
        )
        print("   ✓ Recorded in tracking file")

        notify_report(
            report_path=triage_file,
            subject=f"Bug Triage: #{bug_number} – {bug_title}",
            summary=(
                f"Sequence {sequence} | "
                f"Status: {bug_info.get('status', 'unknown')} | "
                f"Importance: {bug_info.get('importance', 'unknown')}"
            ),
            agent_config=CONFIG,
            notifications_config=load_notifications_config(),
        )

        _post_bug_feedback(bug_info, triage_file, CONFIG)

        return triage_file

    except Exception as e:
        print(f"\n❌ Error during triage: {e}")
        import traceback
        traceback.print_exc()
        return None


def triage_bug_subprocess(bug_info: dict, sequence: int, previous_summary: str = None, previous_seq: int = None):
    """
    Triage a bug in a subprocess to avoid asyncio cleanup issues.

    Args:
        bug_info: Bug information dictionary
        sequence: Sequence number for this triage
        previous_summary: Optional summary from previous triage
        previous_seq: Previous sequence number

    Returns:
        True if successful, False otherwise
    """
    # Create a temporary file with bug info
    import tempfile
    bug_data = {
        'bug_info': bug_info,
        'sequence': sequence,
        'previous_summary': previous_summary,
        'previous_seq': previous_seq,
    }

    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(bug_data, f)
        temp_file = f.name

    try:
        # Run this script in single-bug mode
        # Use -u for unbuffered output
        result = subprocess.run(
            [sys.executable, '-u', __file__, '--single-bug', temp_file],
            stdout=sys.stdout,
            stderr=sys.stderr,
            text=True,
            check=False,
        )
        return result.returncode == 0
    finally:
        # Clean up temp file
        Path(temp_file).unlink(missing_ok=True)


async def monitor_and_triage(project: str, max_bugs: int = 5):
    """
    Monitor Launchpad and triage bugs.

    Args:
        project: Launchpad project name
        max_bugs: Maximum number of bugs to triage in one run
    """
    print(f"\n{'#'*80}")
    print(f"# Bug Triage Agent - Monitoring {project}")
    print(f"{'#'*80}")

    # Load triage history
    tracking_file = Path(CONFIG['triage_tracking_file'])
    history = load_triage_history(tracking_file)

    # Fetch bugs from Launchpad
    bugs = await fetch_bugs_from_launchpad(
        project,
        CONFIG['bug_statuses'],
        max_bugs * 2  # Fetch more since some might be skipped
    )

    if not bugs:
        print(f"\n✓ No bugs found for {project}")
        return

    print("\n📋 Checking which bugs need triage...")
    print(f"📅 Cutoff date: {CONFIG['cutoff_date']} (ignoring bugs created before this date)")

    triaged_count = 0
    skipped_count = 0
    output_dir = Path(CONFIG['triages_output_dir'])
    cutoff_date = CONFIG['cutoff_date']

    for bug in bugs:
        if triaged_count >= max_bugs:
            break

        bug_number = bug['number']
        bug_created = bug['date_created']
        bug_last_updated = bug['date_last_updated']

        # Skip bugs created before cutoff date
        if bug_created:
            # Parse bug creation date (format: 2026-03-30T08:36:48.382279+00:00)
            bug_created_date = bug_created.split('T')[0]  # Get YYYY-MM-DD part
            if bug_created_date < cutoff_date:
                skipped_count += 1
                if skipped_count <= 5:  # Only show first 5 skipped bugs
                    print(f"⏭️  Skipping Bug #{bug_number} - Created {bug_created_date} (before cutoff)")
                continue

        # Check if we should triage this bug
        should_triage, sequence = should_triage_bug(
            bug_number,
            bug_last_updated,
            history
        )

        if not should_triage:
            print(f"⏭️  Skipping Bug #{bug_number} - No updates since last triage")
            continue

        # Get previous triage summary if this is a re-triage
        previous_summary = None
        previous_seq = None
        if sequence > 1:
            previous_triages = find_previous_triages(output_dir, bug_number)
            if previous_triages:
                latest_prev = previous_triages[-1]
                previous_summary = get_previous_triage_summary(latest_prev)
                previous_seq = sequence - 1

        print(f"\n📌 Bug #{bug_number}: {bug['title'][:60]}")
        print(f"   Status: {bug['status']} | Importance: {bug['importance']} | Sequence: {sequence}")

        # Triage the bug in a subprocess to avoid asyncio cleanup issues
        if max_bugs > 1:
            # Use subprocess for multiple bugs
            success = triage_bug_subprocess(bug, sequence, previous_summary, previous_seq)
            if success:
                triaged_count += 1
        else:
            # Use direct async call for single bug (simpler for debugging)
            await triage_bug(bug, sequence, previous_summary, previous_seq)
            triaged_count += 1

    print(f"\n✅ Completed {triaged_count} triages for {project}")
    if skipped_count > 5:
        print(f"⏭️  Skipped {skipped_count} bugs created before cutoff date")


async def main_single_bug(bug_data_file: str):
    """
    Main entry point for single-bug triage mode (called from subprocess).

    Args:
        bug_data_file: Path to JSON file with bug data
    """
    # Load bug data
    with open(bug_data_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    bug_info = data['bug_info']
    sequence = data['sequence']
    previous_summary = data.get('previous_summary')
    previous_seq = data.get('previous_seq')

    # Triage the bug
    try:
        await triage_bug(bug_info, sequence, previous_summary, previous_seq)
        return True
    except Exception as e:
        print(f"❌ Error during triage: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main entry point for the bug triage agent."""
    # Create output directory
    Path(CONFIG['triages_output_dir']).mkdir(exist_ok=True, parents=True)

    print("🚀 Bug Triage Agent Starting...")
    print(f"📁 Output directory: {CONFIG['triages_output_dir']}")
    print(f"🏠 DevStack path: {CONFIG['devstack_path']}")
    print(f"🐛 Project: {CONFIG['launchpad_project']}")
    print(f"🤖 Model: {CONFIG.get('model', 'claude-sonnet-4-6')}")
    print(f"📅 Cutoff date: {CONFIG['cutoff_date']}")

    try:
        await monitor_and_triage(
            CONFIG['launchpad_project'],
            max_bugs=CONFIG['max_bugs_per_run']
        )
    except Exception as e:
        print(f"❌ Error during triage: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*80)
    print("✅ Triage cycle complete!")
    print(f"📊 Triages saved to: {CONFIG['triages_output_dir']}")
    print("="*80)


def cli_main():
    """Main entry point for command-line usage."""
    import argparse

    parser = argparse.ArgumentParser(description='Octavia Bug Triage Agent')
    parser.add_argument('--single-bug', metavar='BUG_DATA_FILE',
                        help='Triage a single bug (used internally for subprocess mode)')
    args = parser.parse_args()

    if args.single_bug:
        # Single-bug mode (called from subprocess)
        success = asyncio.run(main_single_bug(args.single_bug))
        sys.exit(0 if success else 1)
    else:
        # Normal mode
        asyncio.run(main())


if __name__ == "__main__":
    cli_main()
