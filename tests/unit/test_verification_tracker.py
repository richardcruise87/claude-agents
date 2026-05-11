"""Unit tests for fix-verification-agent/verification_tracker.py."""
from verification_tracker import (
    create_verification_filename,
    load_verification_history,
    record_verification,
    should_verify_proposal,
)

_TS_OLD = "2026-05-01T10:00:00"
_TS_NEW = "2026-05-11T10:00:00"


class TestShouldVerifyProposal:
    def test_new_bug_should_verify(self):
        should, seq = should_verify_proposal("12345", _TS_NEW, {})
        assert should is True
        assert seq == 1

    def test_same_proposal_timestamp_should_not_reverify(self, tmp_path):
        tracking = tmp_path / "track.json"
        record_verification(tracking, "12345", _TS_NEW, 1,
                            tmp_path / "v.md", "RESOLVED")
        history = load_verification_history(tracking)
        should, seq = should_verify_proposal("12345", _TS_NEW, history)
        assert should is False

    def test_newer_proposal_triggers_reverification(self, tmp_path):
        tracking = tmp_path / "track.json"
        record_verification(tracking, "12345", _TS_OLD, 1,
                            tmp_path / "v.md", "NOT_RESOLVED")
        history = load_verification_history(tracking)
        should, seq = should_verify_proposal("12345", _TS_NEW, history)
        assert should is True
        assert seq == 2

    def test_different_bugs_are_independent(self, tmp_path):
        tracking = tmp_path / "track.json"
        record_verification(tracking, "11111", _TS_NEW, 1,
                            tmp_path / "v.md", "RESOLVED")
        history = load_verification_history(tracking)
        should, seq = should_verify_proposal("22222", _TS_NEW, history)
        assert should is True
        assert seq == 1


class TestRecordVerification:
    def test_creates_entry(self, tmp_path):
        tracking = tmp_path / "track.json"
        vfile = tmp_path / "verification_12345_title_20260511_1.md"
        record_verification(tracking, "12345", _TS_NEW, 1, vfile, "RESOLVED",
                            patch_source="local patch", attempts=1)
        history = load_verification_history(tracking)
        assert "verify_12345" in history
        entry = history["verify_12345"]
        assert entry["sequence"] == 1
        assert entry["status"] == "RESOLVED"
        assert str(vfile) in entry["verification_file"]
        assert entry["patch_source"] == "local patch"

    def test_status_values_stored(self, tmp_path):
        tracking = tmp_path / "track.json"
        for status in ("RESOLVED", "NOT_RESOLVED", "ENVIRONMENTAL_ERROR"):
            record_verification(tracking, "99999", _TS_NEW, 1,
                                tmp_path / "v.md", status)
            history = load_verification_history(tracking)
            assert history["verify_99999"]["status"] == status


class TestCreateVerificationFilename:
    def test_format(self, tmp_path):
        path = create_verification_filename(tmp_path, "2150752", "KeyError on member add", 1)
        assert path.name.startswith("verification_2150752_")
        assert path.name.endswith("_1.md")
        assert path.parent == tmp_path

    def test_sequence_in_name(self, tmp_path):
        path = create_verification_filename(tmp_path, "99", "Some bug", 3)
        assert path.name.endswith("_3.md")
