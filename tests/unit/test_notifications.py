"""Unit tests for agents_lib.notifications."""
import json
from unittest.mock import MagicMock
from agents_lib.notifications import (
    load_notifications_config,
    notify_report,
    _resolve_env,
)


# ---------------------------------------------------------------------------
# load_notifications_config
# ---------------------------------------------------------------------------

class TestLoadNotificationsConfig:
    def test_returns_empty_dict_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_AGENTS_NOTIFICATIONS_CONFIG", raising=False)
        # Point auto-detection away from the real repo
        monkeypatch.chdir(tmp_path)
        result = load_notifications_config(repo_root=tmp_path)
        assert result == {}

    def test_loads_from_env_var_path(self, tmp_path, monkeypatch):
        cfg = {"channels": {"email": {"enabled": True}}}
        cfg_file = tmp_path / "notif.json"
        cfg_file.write_text(json.dumps(cfg))
        monkeypatch.setenv("CLAUDE_AGENTS_NOTIFICATIONS_CONFIG", str(cfg_file))
        result = load_notifications_config()
        assert result["channels"]["email"]["enabled"] is True

    def test_loads_from_repo_root(self, tmp_path):
        cfg = {"channels": {"ntfy": {"enabled": True, "url": "https://ntfy.sh/test"}}}
        (tmp_path / "notifications.json").write_text(json.dumps(cfg))
        result = load_notifications_config(repo_root=tmp_path)
        assert result["channels"]["ntfy"]["enabled"] is True

    def test_returns_empty_on_missing_env_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_AGENTS_NOTIFICATIONS_CONFIG", str(tmp_path / "nope.json"))
        # Pass an explicit repo_root that has no notifications.json to prevent fallback
        result = load_notifications_config(repo_root=tmp_path)
        assert result == {}


# ---------------------------------------------------------------------------
# _resolve_env
# ---------------------------------------------------------------------------

class TestResolveEnv:
    def test_direct_value(self):
        assert _resolve_env({"token": "abc123"}, "token") == "abc123"

    def test_env_var_lookup(self, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "secret_value")
        assert _resolve_env({"token_env": "MY_SECRET"}, "token") == "secret_value"

    def test_direct_value_preferred_over_env(self, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "env_value")
        result = _resolve_env({"token": "direct", "token_env": "MY_SECRET"}, "token")
        assert result == "direct"

    def test_missing_both_returns_none(self, monkeypatch):
        monkeypatch.delenv("ABSENT_VAR", raising=False)
        assert _resolve_env({"token_env": "ABSENT_VAR"}, "token") is None

    def test_neither_key_returns_none(self):
        assert _resolve_env({}, "password") is None


# ---------------------------------------------------------------------------
# notify_report
# ---------------------------------------------------------------------------

class TestNotifyReport:
    def _make_notif_config(self, **channel_overrides):
        channels = {
            "email": {"enabled": False},
            "slack": {"enabled": False},
            "ntfy": {"enabled": False},
            "desktop": {"enabled": False},
        }
        for name, cfg in channel_overrides.items():
            channels[name] = cfg
        return {"channels": channels}

    def test_disabled_agent_no_channels_fired(self, sample_report_file, mocker):
        send = mocker.patch("agents_lib.notifications._send_email")
        notify_report(
            report_path=sample_report_file,
            subject="Test",
            summary="Summary",
            agent_config={"notifications": {"enabled": False}},
            notifications_config=self._make_notif_config(email={"enabled": True}),
        )
        send.assert_not_called()

    def test_empty_notifications_config_no_crash(self, sample_report_file):
        notify_report(
            report_path=sample_report_file,
            subject="Test",
            summary="Summary",
            agent_config={"notifications": {"enabled": True}},
            notifications_config={},
        )  # Should not raise

    def test_email_channel_called(self, sample_report_file, mocker):
        send = mocker.patch("agents_lib.notifications._send_email")
        notify_report(
            report_path=sample_report_file,
            subject="Sub",
            summary="Sum",
            agent_config={"notifications": {"enabled": True}},
            notifications_config=self._make_notif_config(email={"enabled": True}),
        )
        send.assert_called_once()

    def test_slack_channel_called(self, sample_report_file, mocker):
        send = mocker.patch("agents_lib.notifications._send_slack")
        notify_report(
            report_path=sample_report_file,
            subject="Sub",
            summary="Sum",
            agent_config={"notifications": {"enabled": True}},
            notifications_config=self._make_notif_config(slack={"enabled": True}),
        )
        send.assert_called_once()

    def test_ntfy_channel_called(self, sample_report_file, mocker):
        send = mocker.patch("agents_lib.notifications._send_ntfy")
        notify_report(
            report_path=sample_report_file,
            subject="Sub",
            summary="Sum",
            agent_config={"notifications": {"enabled": True}},
            notifications_config=self._make_notif_config(ntfy={"enabled": True}),
        )
        send.assert_called_once()

    def test_channel_failure_does_not_propagate(self, sample_report_file, mocker, capsys):
        mocker.patch("agents_lib.notifications._send_email", side_effect=RuntimeError("SMTP down"))
        mocker.patch("agents_lib.notifications._send_slack")
        notify_report(
            report_path=sample_report_file,
            subject="Sub",
            summary="Sum",
            agent_config={"notifications": {"enabled": True}},
            notifications_config=self._make_notif_config(
                email={"enabled": True},
                slack={"enabled": True},
            ),
        )
        # The important thing: no exception was raised

    def test_per_agent_channel_override_merged(self, sample_report_file, mocker):
        send = mocker.patch("agents_lib.notifications._send_email")
        notify_report(
            report_path=sample_report_file,
            subject="Sub",
            summary="Sum",
            agent_config={
                "notifications": {
                    "enabled": True,
                    "channels": {"email": {"enabled": True, "to": ["agent@example.com"]}},
                }
            },
            notifications_config={"channels": {"email": {"enabled": False, "to": ["global@example.com"]}}},
        )
        # Per-agent override enables email even though global has it disabled
        send.assert_called_once()
        called_cfg = send.call_args[0][0]
        assert called_cfg["to"] == ["agent@example.com"]

    def test_desktop_skipped_without_display(self, sample_report_file, mocker, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        run = mocker.patch("subprocess.run")
        notify_report(
            report_path=sample_report_file,
            subject="Sub",
            summary="Sum",
            agent_config={"notifications": {"enabled": True}},
            notifications_config=self._make_notif_config(desktop={"enabled": True}),
        )
        run.assert_not_called()

    def test_desktop_called_with_display(self, sample_report_file, mocker, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        run = mocker.patch("subprocess.run", return_value=MagicMock(returncode=0))
        notify_report(
            report_path=sample_report_file,
            subject="Alert",
            summary="Done",
            agent_config={"notifications": {"enabled": True}},
            notifications_config=self._make_notif_config(desktop={"enabled": True}),
        )
        run.assert_called_once()
        args = run.call_args[0][0]
        assert "notify-send" in args
        assert "Alert" in args
