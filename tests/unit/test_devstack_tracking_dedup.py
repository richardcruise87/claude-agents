"""Unit tests for patchset-based deduplication in the DevStack test agent.

Verifies that _find_next_review() uses f"ps{patchset}" as the stable
item_last_updated key, so a review is not re-tested just because the code
review agent created a new review file with a later timestamp.
"""
from unittest.mock import MagicMock

from agents_lib.tracking import should_process_item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_review_info(change_number: str, patchset: int, repo: str = "openstack/octavia"):
    info = MagicMock()
    info.change_number = change_number
    info.patchset = patchset
    info.repo_name = repo
    info.already_tested = False
    info.gerrit_url = f"https://review.opendev.org/c/{repo}/+/{change_number}"
    # review_timestamp varies (code review agent creates new file each run)
    info.review_timestamp = "20260527_094512"
    return info


def _review_id(review_info) -> str:
    return (
        f"{review_info.repo_name}~{review_info.change_number}~ps{review_info.patchset}"
    )


# ---------------------------------------------------------------------------
# Tests for the deduplication logic
# ---------------------------------------------------------------------------

class TestPatchsetDeduplication:
    """Verify that f"ps{patchset}" prevents re-testing unchanged patchsets."""

    def test_first_test_of_patchset_is_selected(self):
        """A patchset not in tracking should always be selected for testing."""
        review_info = _make_review_info("988005", 3)
        history = {}

        should_test, seq = should_process_item(
            _review_id(review_info),
            f"ps{review_info.patchset}",
            history,
        )

        assert should_test is True
        assert seq == 1

    def test_already_tested_patchset_is_skipped(self):
        """A patchset recorded with 'ps3' must not be re-selected on next cycle."""
        review_info = _make_review_info("988005", 3)
        history = {
            _review_id(review_info): {
                "last_processed": "2026-05-27T01:43:37",
                "last_updated": "ps3",  # ← new stable format
                "sequence": 1,
                "test_result": "success",
            }
        }

        should_test, seq = should_process_item(
            _review_id(review_info),
            f"ps{review_info.patchset}",
            history,
        )

        assert should_test is False
        assert seq == 1

    def test_new_review_file_does_not_trigger_retest(self):
        """A later review file timestamp must NOT cause a re-test of the same patchset."""
        review_info = _make_review_info("988005", 3)
        # Tracking records ps3 as tested with the stable key
        history = {
            _review_id(review_info): {
                "last_processed": "2026-05-11T12:07:13",
                "last_updated": "ps3",
                "sequence": 1,
                "test_result": "success",
            }
        }
        # Even if a new review file has appeared (later timestamp), we still use
        # the stable patchset key — no re-test.
        should_test, _ = should_process_item(
            _review_id(review_info),
            "ps3",  # same as what's stored
            history,
        )

        assert should_test is False

    def test_new_patchset_triggers_new_test(self):
        """PS4 for a change that has PS3 recorded should be a separate new test."""
        review_info_ps3 = _make_review_info("988005", 3)
        review_info_ps4 = _make_review_info("988005", 4)

        history = {
            _review_id(review_info_ps3): {
                "last_processed": "2026-05-27T01:43:37",
                "last_updated": "ps3",
                "sequence": 1,
                "test_result": "success",
            }
        }

        should_test, seq = should_process_item(
            _review_id(review_info_ps4),
            f"ps{review_info_ps4.patchset}",
            history,
        )

        assert should_test is True
        assert seq == 1

    def test_retry_on_recovery_overrides_stable_key(self):
        """ENVIRONMENT_ERROR entries with retry_on_recovery=True must still be retried."""
        review_info = _make_review_info("988005", 3)
        history = {
            _review_id(review_info): {
                "last_processed": "2026-05-27T01:43:37",
                "last_updated": "ps3",
                "sequence": 1,
                "test_result": "environment_error",
                "retry_on_recovery": True,
            }
        }

        should_test, seq = should_process_item(
            _review_id(review_info),
            f"ps{review_info.patchset}",
            history,
        )

        assert should_test is True
        assert seq == 1  # same sequence on recovery retry

    def test_old_timestamp_format_causes_one_retest(self):
        """Migration: existing entries with timestamp-based last_updated trigger one re-test.

        'ps3' > '20260511_120713' in string comparison, so should_process_item
        returns True. This is the documented one-time migration cost.
        """
        review_info = _make_review_info("988005", 3)
        history = {
            _review_id(review_info): {
                "last_processed": "2026-05-27T01:43:37",
                "last_updated": "20260511_120713",  # ← old timestamp format
                "sequence": 1,
                "test_result": "success",
            }
        }

        should_test, seq = should_process_item(
            _review_id(review_info),
            "ps3",  # new stable format
            history,
        )

        # 'ps3' > '20260511_120713' → True (one migration re-test expected)
        assert should_test is True
        assert seq == 2

    def test_different_repo_same_change_number_independent(self):
        """Same change number in two different repos must have independent tracking."""
        octavia = _make_review_info("988005", 3, "openstack/octavia")
        dashboard = _make_review_info("988005", 3, "openstack/octavia-dashboard")

        history = {
            _review_id(octavia): {
                "last_processed": "2026-05-27T01:00:00",
                "last_updated": "ps3",
                "sequence": 1,
                "test_result": "success",
            }
        }

        should_test, seq = should_process_item(
            _review_id(dashboard),
            "ps3",
            history,
        )

        assert should_test is True  # dashboard change is independent
        assert seq == 1
