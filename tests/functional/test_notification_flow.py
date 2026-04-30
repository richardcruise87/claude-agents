"""
Functional tests for the full notification dispatch flow.

Uses mocked channel backends to verify routing, isolation, and config merging.
"""
import json
from agents_lib.notifications import notify_report, load_notifications_config


def _all_channels_config(**overrides):
    channels = {
        "email": {"enabled": False},
        "slack": {"enabled": False},
        "ntfy": {"enabled": False},
        "desktop": {"enabled": False},
    }
    channels.update(overrides)
    return {"channels": channels}


class TestAllChannelsFire:
    def test_all_enabled_channels_called(self, sample_report_file, mocker):
        email = mocker.patch("agents_lib.notifications._send_email")
        slack = mocker.patch("agents_lib.notifications._send_slack")
        ntfy = mocker.patch("agents_lib.notifications._send_ntfy")
        desktop = mocker.patch("agents_lib.notifications._send_desktop")

        notify_report(
            report_path=sample_report_file,
            subject="Test",
            summary="All channels",
            agent_config={"notifications": {"enabled": True}},
            notifications_config=_all_channels_config(
                email={"enabled": True},
                slack={"enabled": True},
                ntfy={"enabled": True},
                desktop={"enabled": True},
            ),
        )

        email.assert_called_once()
        slack.assert_called_once()
        ntfy.assert_called_once()
        desktop.assert_called_once()

    def test_only_enabled_channels_called(self, sample_report_file, mocker):
        email = mocker.patch("agents_lib.notifications._send_email")
        slack = mocker.patch("agents_lib.notifications._send_slack")

        notify_report(
            report_path=sample_report_file,
            subject="Test",
            summary="Summary",
            agent_config={"notifications": {"enabled": True}},
            notifications_config=_all_channels_config(
                email={"enabled": True},
                slack={"enabled": False},
            ),
        )

        email.assert_called_once()
        slack.assert_not_called()


class TestFailureIsolation:
    def test_one_channel_failure_does_not_stop_others(self, sample_report_file, mocker, capsys):
        mocker.patch("agents_lib.notifications._send_email", side_effect=ConnectionError("SMTP down"))
        slack = mocker.patch("agents_lib.notifications._send_slack")
        ntfy = mocker.patch("agents_lib.notifications._send_ntfy")

        # Should not raise
        notify_report(
            report_path=sample_report_file,
            subject="Test",
            summary="Failure isolation",
            agent_config={"notifications": {"enabled": True}},
            notifications_config=_all_channels_config(
                email={"enabled": True},
                slack={"enabled": True},
                ntfy={"enabled": True},
            ),
        )

        slack.assert_called_once()
        ntfy.assert_called_once()

        captured = capsys.readouterr()
        assert "email failed" in captured.err

    def test_all_channels_fail_no_exception(self, sample_report_file, mocker):
        mocker.patch("agents_lib.notifications._send_email", side_effect=RuntimeError("boom"))
        mocker.patch("agents_lib.notifications._send_slack", side_effect=RuntimeError("boom"))
        mocker.patch("agents_lib.notifications._send_ntfy", side_effect=RuntimeError("boom"))

        # Must not raise
        notify_report(
            report_path=sample_report_file,
            subject="Test",
            summary="All fail",
            agent_config={"notifications": {"enabled": True}},
            notifications_config=_all_channels_config(
                email={"enabled": True},
                slack={"enabled": True},
                ntfy={"enabled": True},
            ),
        )


class TestConfigLoading:
    def test_load_from_file_and_dispatch(self, tmp_path, sample_report_file, mocker):
        cfg = {"channels": {"ntfy": {"enabled": True, "url": "https://ntfy.sh/test"}}}
        (tmp_path / "notifications.json").write_text(json.dumps(cfg))

        ntfy = mocker.patch("agents_lib.notifications._send_ntfy")

        notif_config = load_notifications_config(repo_root=tmp_path)
        notify_report(
            report_path=sample_report_file,
            subject="Test",
            summary="From file",
            agent_config={"notifications": {"enabled": True}},
            notifications_config=notif_config,
        )
        ntfy.assert_called_once()


class TestAgentDisabled:
    def test_disabled_agent_suppresses_all_channels(self, sample_report_file, mocker):
        email = mocker.patch("agents_lib.notifications._send_email")
        slack = mocker.patch("agents_lib.notifications._send_slack")

        notify_report(
            report_path=sample_report_file,
            subject="Test",
            summary="Disabled",
            agent_config={"notifications": {"enabled": False}},
            notifications_config=_all_channels_config(
                email={"enabled": True},
                slack={"enabled": True},
            ),
        )

        email.assert_not_called()
        slack.assert_not_called()

    def test_missing_notifications_key_treated_as_disabled(self, sample_report_file, mocker):
        email = mocker.patch("agents_lib.notifications._send_email")
        notify_report(
            report_path=sample_report_file,
            subject="Test",
            summary="No key",
            agent_config={},
            notifications_config=_all_channels_config(email={"enabled": True}),
        )
        email.assert_not_called()
