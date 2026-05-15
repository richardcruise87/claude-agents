"""Unit tests for ci-failure-agent/zuul_client.py."""
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from zuul_client import (
    normalize_build,
    group_failures_by_change,
    get_latest_patchset_failures,
    get_build_log_url,
    format_duration,
    fetch_recent_failures,
)


def _make_build(**kwargs):
    defaults = {
        "uuid": "abc123",
        "job_name": "octavia-v2-dsvm-scenario",
        "project": "openstack/octavia",
        "pipeline": "check",
        "change": "982567",
        "patchset": "1",
        "result": "FAILURE",
        "log_url": "https://logs.opendev.org/abc123",
        "duration": 330.0,
        "voting": True,
        "end_time": "2026-03-30T10:00:00Z",
        "nodeset": "ubuntu-focal",
    }
    defaults.update(kwargs)
    return defaults


class TestFormatDuration:
    def test_minutes_and_seconds(self):
        assert format_duration(330) == "5m 30s"

    def test_only_seconds(self):
        assert format_duration(45) == "45s"

    def test_zero(self):
        assert format_duration(0) == "unknown"

    def test_none(self):
        assert format_duration(None) == "unknown"

    def test_exact_minutes(self):
        assert format_duration(120) == "2m 0s"

    def test_large_duration(self):
        assert format_duration(5400) == "90m 0s"


class TestNormalizeBuild:
    def test_flattens_ref(self):
        build = {
            "uuid": "x",
            "ref": {
                "project": "openstack/octavia",
                "change": "982567",
                "patchset": "1",
                "ref_url": "https://review.opendev.org/c/openstack/octavia/+/982567",
            }
        }
        result = normalize_build(build)
        assert result["project"] == "openstack/octavia"
        assert result["change"] == "982567"
        assert result["patchset"] == "1"

    def test_no_ref_no_crash(self):
        build = {"uuid": "x"}
        result = normalize_build(build)
        assert result.get("project") is None

    def test_existing_flat_fields_not_overwritten(self):
        build = {"uuid": "x", "project": "existing", "ref": {"project": "from-ref"}}
        result = normalize_build(build)
        assert result["project"] == "existing"


class TestGroupFailuresByChange:
    def test_basic_grouping(self):
        builds = [
            _make_build(change="100", patchset="1", pipeline="check"),
            _make_build(change="100", patchset="1", pipeline="check", uuid="def456"),
            _make_build(change="200", patchset="2", pipeline="gate"),
        ]
        grouped = group_failures_by_change(builds)
        assert ("100", "1", "openstack/octavia", "check") in grouped
        assert len(grouped[("100", "1", "openstack/octavia", "check")]) == 2
        assert ("200", "2", "openstack/octavia", "gate") in grouped

    def test_skip_non_voting(self):
        builds = [
            _make_build(voting=True),
            _make_build(voting=False, uuid="nonvoting"),
        ]
        grouped = group_failures_by_change(builds, skip_non_voting=True)
        all_uuids = [b["uuid"] for jobs in grouped.values() for b in jobs]
        assert "nonvoting" not in all_uuids

    def test_include_non_voting_by_default(self):
        builds = [_make_build(voting=False)]
        grouped = group_failures_by_change(builds, skip_non_voting=False)
        assert len(grouped) == 1

    def test_missing_fields_skipped(self):
        builds = [{"uuid": "x", "result": "FAILURE"}]  # No change/patchset/project/pipeline
        grouped = group_failures_by_change(builds)
        assert len(grouped) == 0


class TestGetLatestPatchsetFailures:
    def test_empty_builds(self):
        latest, grouped = get_latest_patchset_failures([])
        assert latest is None
        assert grouped == {}

    def test_picks_highest_patchset(self):
        builds = [
            _make_build(patchset="1"),
            _make_build(patchset="3"),
            _make_build(patchset="2"),
        ]
        latest, _ = get_latest_patchset_failures(builds)
        assert latest == "3"

    def test_only_latest_patchset_in_grouped(self):
        builds = [
            _make_build(patchset="1", uuid="old"),
            _make_build(patchset="2", uuid="new"),
        ]
        latest, grouped = get_latest_patchset_failures(builds)
        all_uuids = [b["uuid"] for jobs in grouped.values() for b in jobs]
        assert "new" in all_uuids
        assert "old" not in all_uuids


class TestGetBuildLogUrl:
    def test_adds_trailing_slash(self):
        build = {"log_url": "https://logs.example.com/abc"}
        result = get_build_log_url(build)
        assert result.endswith("/")

    def test_no_double_slash(self):
        build = {"log_url": "https://logs.example.com/abc/"}
        result = get_build_log_url(build)
        assert result.endswith("/")
        assert not result.endswith("//")

    def test_no_log_url_returns_none(self):
        build = {}
        assert get_build_log_url(build) is None


class TestFetchRecentFailures:
    def test_successful_fetch(self, mocker):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(hours=1)).isoformat()
        builds = [
            {"uuid": "1", "project": "openstack/octavia", "pipeline": "check",
             "change": "100", "patchset": "1", "result": "FAILURE",
             "log_url": "https://logs.example.com/1/", "duration": 60.0,
             "voting": True, "end_time": recent, "nodeset": "ubuntu-focal",
             "job_name": "test-job"},
        ]

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(builds).encode()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("zuul_client.urlopen", return_value=mock_resp):
            result = fetch_recent_failures(
                "openstack/octavia", "check",
                "https://zuul.opendev.org", "openstack", hours_back=24
            )
        assert len(result) == 1

    def test_old_builds_filtered_out(self, mocker):
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=48)).isoformat()
        builds = [
            {"uuid": "1", "project": "openstack/octavia", "pipeline": "check",
             "change": "100", "patchset": "1", "result": "FAILURE",
             "log_url": None, "duration": 60.0, "voting": True,
             "end_time": old_time, "nodeset": "ubuntu-focal", "job_name": "job"},
        ]

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(builds).encode()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("zuul_client.urlopen", return_value=mock_resp):
            result = fetch_recent_failures(
                "openstack/octavia", "check",
                "https://zuul.opendev.org", "openstack", hours_back=24
            )
        assert len(result) == 0

    def test_http_error_returns_none(self, mocker):
        with patch("zuul_client.urlopen", side_effect=HTTPError(None, 500, "err", {}, None)):
            result = fetch_recent_failures(
                "openstack/octavia", "check",
                "https://zuul.opendev.org", "openstack"
            )
        assert result is None
