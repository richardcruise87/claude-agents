"""Unit tests for bug-triage-agent/bug_tracker.py."""
import json
from bug_tracker import (
    should_triage_bug,
    record_triage,
    create_triage_filename,
    find_previous_triages,
    get_previous_triage_summary,
    load_triage_history,
)


class TestShouldTriageBug:
    def test_new_bug_should_triage(self):
        should, seq = should_triage_bug("12345", "2026-03-01T10:00:00", {})
        assert should is True
        assert seq == 1

    def test_no_update_should_not_retriage(self, sample_tracking_file):
        history = load_triage_history(sample_tracking_file)
        should, seq = should_triage_bug("12345", "2026-03-30T08:00:00", history)
        assert should is False
        assert seq == 1

    def test_updated_bug_should_retriage(self, sample_tracking_file):
        history = load_triage_history(sample_tracking_file)
        # Use a timestamp newer than "2026-03-30T08:00:00" in sample
        should, seq = should_triage_bug("12345", "2026-04-01T00:00:00", history)
        assert should is True
        assert seq == 2

    def test_different_bug_unaffected(self, sample_tracking_file):
        history = load_triage_history(sample_tracking_file)
        should, seq = should_triage_bug("99999", "2026-01-01T00:00:00", history)
        assert should is True
        assert seq == 1


class TestRecordTriage:
    def test_creates_entry(self, tmp_path):
        tf = tmp_path / "track.json"
        record_triage(tf, "42", "2026-03-01T10:00:00", 1)
        history = json.loads(tf.read_text())
        assert "bug_42" in history
        assert history["bug_42"]["sequence"] == 1

    def test_sequence_preserved(self, tmp_path):
        tf = tmp_path / "track.json"
        record_triage(tf, "1", "2026-01-01", 1)
        record_triage(tf, "1", "2026-06-01", 2)
        history = json.loads(tf.read_text())
        assert history["bug_1"]["sequence"] == 2


class TestCreateTriageFilename:
    def test_format(self, tmp_path):
        path = create_triage_filename(tmp_path, "12345", "Load balancer fails", 1)
        assert path.name.startswith("bug_12345_")
        assert "_1.md" in path.name
        assert "load_balancer_fails" in path.name

    def test_sequence_in_name(self, tmp_path):
        path = create_triage_filename(tmp_path, "1", "title", 3)
        assert "_3.md" in path.name

    def test_path_in_output_dir(self, tmp_path):
        path = create_triage_filename(tmp_path, "1", "title", 1)
        assert path.parent == tmp_path


class TestFindPreviousTriages:
    def test_empty_dir(self, tmp_path):
        result = find_previous_triages(tmp_path, "99999")
        assert result == []

    def test_finds_matching_files(self, tmp_path):
        for seq in [1, 2, 3]:
            (tmp_path / f"bug_123_title_20260101_000000_{seq}.md").write_text(f"seq {seq}")
        result = find_previous_triages(tmp_path, "123")
        assert len(result) == 3

    def test_sorted_by_sequence(self, tmp_path):
        (tmp_path / "bug_123_title_20260101_000000_1.md").write_text("seq 1")
        (tmp_path / "bug_123_title_20260101_000000_3.md").write_text("seq 3")
        (tmp_path / "bug_123_title_20260101_000000_2.md").write_text("seq 2")
        result = find_previous_triages(tmp_path, "123")
        seqs = [int(p.stem.split("_")[-1]) for p in result]
        assert seqs == sorted(seqs)

    def test_does_not_match_other_bugs(self, tmp_path):
        (tmp_path / "bug_123_title_20260101_000000_1.md").write_text("")
        (tmp_path / "bug_999_other_20260101_000000_1.md").write_text("")
        result = find_previous_triages(tmp_path, "123")
        assert all("bug_123_" in p.name for p in result)


class TestGetPreviousTriageSummary:
    def test_returns_first_2000_chars(self, tmp_path):
        content = "X" * 5000
        f = tmp_path / "triage.md"
        f.write_text(content)
        result = get_previous_triage_summary(f)
        assert len(result) == 2000

    def test_returns_none_for_missing_file(self, tmp_path):
        result = get_previous_triage_summary(tmp_path / "nope.md")
        assert result is None
