"""
Functional tests for the full item tracking lifecycle.

Exercises: new item → process → skip (same timestamp) → update → re-process.
"""
from agents_lib import (
    load_tracking_file,
    record_processed_item,
    should_process_item,
)


class TestTrackingLifecycle:
    ITEM_ID = "bug_12345"
    TS_V1 = "2026-03-01T10:00:00"
    TS_V2 = "2026-04-01T10:00:00"

    def test_new_item_processed(self, tmp_path):
        tf = tmp_path / "track.json"
        history = load_tracking_file(tf)
        should, seq = should_process_item(self.ITEM_ID, self.TS_V1, history)
        assert should is True
        assert seq == 1

    def test_processed_item_skipped(self, tmp_path):
        tf = tmp_path / "track.json"
        record_processed_item(tf, self.ITEM_ID, self.TS_V1, 1)
        history = load_tracking_file(tf)
        should, seq = should_process_item(self.ITEM_ID, self.TS_V1, history)
        assert should is False
        assert seq == 1

    def test_updated_item_reprocessed(self, tmp_path):
        tf = tmp_path / "track.json"
        record_processed_item(tf, self.ITEM_ID, self.TS_V1, 1)
        history = load_tracking_file(tf)
        should, seq = should_process_item(self.ITEM_ID, self.TS_V2, history)
        assert should is True
        assert seq == 2

    def test_second_processing_recorded(self, tmp_path):
        tf = tmp_path / "track.json"
        record_processed_item(tf, self.ITEM_ID, self.TS_V1, 1)
        record_processed_item(tf, self.ITEM_ID, self.TS_V2, 2)
        history = load_tracking_file(tf)
        entry = history[self.ITEM_ID]
        assert entry["sequence"] == 2
        assert entry["last_updated"] == self.TS_V2

    def test_multiple_items_independent(self, tmp_path):
        tf = tmp_path / "track.json"
        record_processed_item(tf, "bug_1", "2026-01-01", 1)
        record_processed_item(tf, "bug_2", "2026-01-01", 1)

        history = load_tracking_file(tf)

        # Bug 1 updated → should reprocess
        should1, seq1 = should_process_item("bug_1", "2026-06-01", history)
        # Bug 2 not updated → should skip
        should2, seq2 = should_process_item("bug_2", "2026-01-01", history)

        assert should1 is True
        assert seq1 == 2
        assert should2 is False
        assert seq2 == 1

    def test_extra_data_persisted_across_calls(self, tmp_path):
        tf = tmp_path / "track.json"
        record_processed_item(
            tf, "bug_42", "2026-01-01", 1,
            extra_data={"status": "REPRODUCED", "attempts": 2}
        )
        history = load_tracking_file(tf)
        assert history["bug_42"]["status"] == "REPRODUCED"
        assert history["bug_42"]["attempts"] == 2
