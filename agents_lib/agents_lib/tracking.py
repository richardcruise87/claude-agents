"""
Item tracking utilities for Claude agents.

Helps agents track what items (bugs, changes, etc.) have been processed.
"""
import json
from pathlib import Path
from datetime import datetime
from .utils import slugify as _default_slugify


def load_tracking_file(tracking_file):
    """
    Load tracking history from file.

    Args:
        tracking_file: Path to tracking file

    Returns:
        Dictionary with tracking history
    """
    tracking_file = Path(tracking_file)
    if tracking_file.exists():
        with open(tracking_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_tracking_file(tracking_file, history):
    """
    Save tracking history to file.

    Args:
        tracking_file: Path to tracking file
        history: Dictionary with tracking history
    """
    tracking_file = Path(tracking_file)
    tracking_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tracking_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2)


def should_process_item(
    item_id,
    item_last_updated,
    history,
    id_prefix=""
):
    """
    Determine if an item should be processed.

    Args:
        item_id: Unique identifier for the item
        item_last_updated: ISO timestamp when item was last updated
        history: Tracking history dictionary
        id_prefix: Optional prefix for item key (e.g., "bug_", "change_")

    Returns:
        Tuple of (should_process: bool, sequence_number: int)
    """
    item_key = f"{id_prefix}{item_id}" if id_prefix else item_id

    if item_key not in history:
        # Never processed before
        return (True, 1)

    last_processing = history[item_key]
    last_updated_tracked = last_processing.get('last_updated', '')

    # Compare timestamps
    # If item has been updated since last processing, process again with incremented sequence
    if item_last_updated > last_updated_tracked:
        next_sequence = last_processing.get('sequence', 0) + 1
        return (True, next_sequence)

    # Item hasn't been updated since last processing
    return (False, last_processing.get('sequence', 1))


def record_processed_item(
    tracking_file,
    item_id,
    item_last_updated,
    sequence,
    id_prefix="",
    extra_data=None
):
    """
    Record that an item was processed.

    Args:
        tracking_file: Path to tracking file
        item_id: Unique identifier for the item
        item_last_updated: ISO timestamp when item was last updated
        sequence: Sequence number for this processing
        id_prefix: Optional prefix for item key (e.g., "bug_", "change_")
        extra_data: Optional dictionary with additional data to store
    """
    history = load_tracking_file(tracking_file)
    item_key = f"{id_prefix}{item_id}" if id_prefix else item_id

    record = {
        "last_processed": datetime.now().isoformat(),
        "last_updated": item_last_updated,
        "sequence": sequence
    }

    if extra_data:
        record.update(extra_data)

    history[item_key] = record
    save_tracking_file(tracking_file, history)


def create_output_filename(
    output_dir,
    item_id,
    item_title,
    sequence,
    prefix="",
    extension=".md",
    slugify_func=None
):
    """
    Create output filename with proper format.

    Format: <prefix>_<id>_<title-slug>_<timestamp>_<sequence><extension>

    Args:
        output_dir: Output directory
        item_id: Item identifier
        item_title: Item title
        sequence: Sequence number
        prefix: Filename prefix (e.g., "bug", "review")
        extension: File extension (default: ".md")
        slugify_func: Function to slugify title (uses simple default if None)

    Returns:
        Path to the output file
    """
    if slugify_func is None:
        slugify_func = _default_slugify

    title_slug = slugify_func(item_title)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if prefix:
        filename = f"{prefix}_{item_id}_{title_slug}_{timestamp}_{sequence}{extension}"
    else:
        filename = f"{item_id}_{title_slug}_{timestamp}_{sequence}{extension}"

    return Path(output_dir) / filename
