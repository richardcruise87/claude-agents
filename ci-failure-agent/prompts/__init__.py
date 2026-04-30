"""
Prompt template loader for the CI Failure Analysis Agent.
"""
from datetime import datetime, timezone
from pathlib import Path

from agents_lib import load_agent_prompt as _load_agent_prompt

PROMPTS_DIR = Path(__file__).parent


def get_ci_failure_prompt(
    project,
    change_number,
    patchset,
    pipeline,
    gerrit_base_url,
    zuul_base_url,
    zuul_tenant,
    failing_jobs,
    output_file,
    provider: str = "anthropic",
    save_path: str = None,
):
    """
    Return a formatted CI failure analysis prompt.

    Args:
        project: Project name (e.g., "openstack/octavia")
        change_number: Gerrit change number (string)
        patchset: Patchset number (string)
        pipeline: Zuul pipeline name (e.g., "check")
        gerrit_base_url: Base URL of Gerrit instance
        zuul_base_url: Base URL of Zuul instance
        zuul_tenant: Zuul tenant name (e.g., "openstack")
        failing_jobs: List of dicts, each with: job_name, uuid, log_url,
                      duration, voting, end_time, nodeset
        output_file: Absolute path where the report should be written

    Returns:
        Formatted prompt string ready to send to an AI agent
    """
    template = _load_agent_prompt(
        "ci_failure", provider=provider, prompts_dir=PROMPTS_DIR, save_path=save_path
    )

    # Build the failing jobs table for the prompt
    table_lines = [
        "| Job | UUID | Log URL | Duration | Voting |",
        "|-----|------|---------|----------|--------|",
    ]
    detail_sections = []

    for job in failing_jobs:
        job_name = job.get("job_name", "unknown")
        uuid = job.get("uuid", "")
        log_url = job.get("log_url", "")
        duration = job.get("duration", 0)
        voting = job.get("voting", True)

        minutes = int(duration // 60) if duration else 0
        secs = int(duration % 60) if duration else 0
        duration_str = f"{minutes}m {secs}s" if duration else "unknown"
        voting_str = "yes" if voting else "no"
        uuid_short = uuid[:12] + "..." if len(uuid) > 12 else uuid

        build_url = f"{zuul_base_url}/t/{zuul_tenant}/build/{uuid}" if uuid else "N/A"
        log_url_display = log_url if log_url else "N/A"

        table_lines.append(
            f"| {job_name} | {uuid_short} | {log_url_display} | {duration_str} | {voting_str} |"
        )

        detail_sections.append(f"""### Job: {job_name}
- **Full UUID:** {uuid}
- **Build URL:** {build_url}
- **Log URL:** {log_url_display}
- **Duration:** {duration_str}
- **Voting:** {'Yes (blocks merge)' if voting else 'No (informational only)'}
- **Nodeset:** {job.get('nodeset', 'unknown')}""")

    failing_jobs_table = "\n".join(table_lines)
    failing_jobs_detail = "\n\n".join(detail_sections)
    gerrit_url = f"{gerrit_base_url}/c/{project}/+/{change_number}"
    analysis_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    formatted = template
    formatted = formatted.replace("{project}", project)
    formatted = formatted.replace("{change_number}", str(change_number))
    formatted = formatted.replace("{patchset}", str(patchset))
    formatted = formatted.replace("{pipeline}", pipeline)
    formatted = formatted.replace("{gerrit_url}", gerrit_url)
    formatted = formatted.replace("{gerrit_base_url}", gerrit_base_url)
    formatted = formatted.replace("{zuul_base_url}", zuul_base_url)
    formatted = formatted.replace("{zuul_tenant}", zuul_tenant)
    formatted = formatted.replace("{failing_jobs_table}", failing_jobs_table)
    formatted = formatted.replace("{failing_jobs_detail}", failing_jobs_detail)
    formatted = formatted.replace("{total_failures}", str(len(failing_jobs)))
    formatted = formatted.replace("{output_file}", str(output_file))
    formatted = formatted.replace("{analysis_date}", analysis_date)

    return formatted
