"""
CI failure tracking for the CI Failure Analysis Agent.

Tracks which change+patchset+pipeline combinations have been analyzed,
and supports re-analysis when new failures appear after the last analysis.
"""
from agents_lib import load_tracking_file, should_process_item, record_processed_item


def get_failure_key(change_number, patchset, pipeline):
    """Generate the unique tracking key for a CI failure group."""
    return f"{change_number}~ps{patchset}~{pipeline}"


def has_been_analyzed(tracking_file, change_number, patchset, pipeline, last_updated):
    """
    Check if a CI failure has already been analyzed.

    Re-analysis is triggered if new failures appeared (last_updated is newer
    than what was recorded during the last analysis).

    Args:
        tracking_file: Path to tracking JSON file
        change_number: Gerrit change number
        patchset: Patchset number
        pipeline: Zuul pipeline name
        last_updated: ISO timestamp of the most recent failing build

    Returns:
        Tuple of (already_analyzed: bool, next_sequence: int)
    """
    history = load_tracking_file(tracking_file)
    key = get_failure_key(change_number, patchset, pipeline)
    should, sequence = should_process_item(
        item_id=key,
        item_last_updated=last_updated,
        history=history,
        id_prefix="",
    )
    return not should, sequence


def record_analyzed_failure(
    tracking_file,
    change_number,
    patchset,
    pipeline,
    last_updated,
    sequence,
    extra_data=None,
):
    """
    Record that a CI failure has been analyzed.

    Args:
        tracking_file: Path to tracking JSON file
        change_number: Gerrit change number
        patchset: Patchset number
        pipeline: Zuul pipeline name
        last_updated: ISO timestamp of the most recent failing build
        sequence: Sequence number for this analysis (1 = first, 2 = re-analysis, etc.)
        extra_data: Optional dict with additional data (e.g., report file path)
    """
    key = get_failure_key(change_number, patchset, pipeline)
    record_processed_item(
        tracking_file=tracking_file,
        item_id=key,
        item_last_updated=last_updated,
        sequence=sequence,
        id_prefix="",
        extra_data=extra_data,
    )
