"""Tests for the startup banner logging."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestLogStartupBanner:
    def _make_publisher(
        self,
        is_connected: bool = True,
        stream_names: list[str] | None = None,
    ) -> MagicMock:
        from hermes.publisher import Publisher

        mock = MagicMock(spec=Publisher)
        mock.is_connected = is_connected
        mock.stream_names = (
            stream_names if stream_names is not None else ["homeric-agents", "homeric-tasks"]
        )
        return mock

    def test_banner_logs_version(self) -> None:
        from hermes import __version__
        from hermes.server import _log_startup_banner

        publisher = self._make_publisher()
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher)

        all_calls = mock_logger.info.call_args_list
        first_call = all_calls[0]
        assert "version=%s" in first_call.args[0]
        assert __version__ in first_call.args[1:]

    def test_banner_logs_nats_url(self) -> None:
        from hermes.config import get_settings
        from hermes.server import _log_startup_banner

        settings = get_settings()
        publisher = self._make_publisher()
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher, settings)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert any(settings.nats_url in a for a in all_info_args)

    def test_banner_logs_port(self) -> None:
        from hermes.config import get_settings
        from hermes.server import _log_startup_banner

        settings = get_settings()
        publisher = self._make_publisher()
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher, settings)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert any(str(settings.hermes_port) in a for a in all_info_args)

    def test_banner_never_logs_webhook_secret(self) -> None:
        from hermes.config import Settings
        from hermes.server import _log_startup_banner

        secret = "abcdefgh" + "x" * 24  # pad to 32 chars to pass validation
        settings = Settings(webhook_secret=secret)
        publisher = self._make_publisher()
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher, settings)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert not any(secret in a for a in all_info_args)
        assert not any(secret[:4] in a for a in all_info_args)
        assert any("hmac_validation" in a and "enabled" in a for a in all_info_args)

    def test_banner_reports_hmac_disabled_when_secret_unset(self) -> None:
        from hermes.config import Settings
        from hermes.server import _log_startup_banner

        settings = Settings(webhook_secret="")
        publisher = self._make_publisher()
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher, settings)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert any("hmac_validation" in a and "disabled" in a for a in all_info_args)

    def test_banner_shows_hmac_enabled(self) -> None:
        from hermes.config import Settings
        from hermes.server import _log_startup_banner

        settings = Settings(webhook_secret="mysecret" + "x" * 24)  # pad to 32 chars
        publisher = self._make_publisher()
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher, settings)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert any("enabled" in a for a in all_info_args)

    def test_banner_shows_hmac_disabled(self) -> None:
        from hermes.config import Settings
        from hermes.server import _log_startup_banner

        settings = Settings(webhook_secret="")
        publisher = self._make_publisher()
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher, settings)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert any("disabled" in a for a in all_info_args)

    def test_banner_never_logs_dead_letter_api_key(self) -> None:
        from hermes.config import Settings
        from hermes.server import _log_startup_banner

        key = "wxyz1234" + "k" * 24  # >= 32 chars to pass validation
        settings = Settings(dead_letter_api_key=key)
        publisher = self._make_publisher()
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher, settings)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert not any(key in a for a in all_info_args)
        assert not any(key[:4] in a for a in all_info_args)
        assert any("dead_letter_auth" in a and "enabled" in a for a in all_info_args)

    def test_banner_reports_dead_letter_auth_disabled_when_key_unset(self) -> None:
        from hermes.config import Settings
        from hermes.server import _log_startup_banner

        settings = Settings(dead_letter_api_key="")
        publisher = self._make_publisher()
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher, settings)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert any("dead_letter_auth" in a and "disabled" in a for a in all_info_args)

    def test_banner_shows_dead_letter_auth_enabled(self) -> None:
        from hermes.config import Settings
        from hermes.server import _log_startup_banner

        settings = Settings(dead_letter_api_key="k" * 32)
        publisher = self._make_publisher()
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher, settings)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert any("dead_letter_auth" in a and "enabled" in a for a in all_info_args)

    def test_banner_shows_dead_letter_auth_disabled(self) -> None:
        from hermes.config import Settings
        from hermes.server import _log_startup_banner

        settings = Settings(dead_letter_api_key="")
        publisher = self._make_publisher()
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher, settings)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert any("dead_letter_auth" in a and "disabled" in a for a in all_info_args)

    def test_banner_logs_nats_connected_true(self) -> None:
        from hermes.server import _log_startup_banner

        publisher = self._make_publisher(is_connected=True)
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert any("True" in a for a in all_info_args)

    def test_banner_logs_nats_connected_false(self) -> None:
        from hermes.server import _log_startup_banner

        publisher = self._make_publisher(is_connected=False)
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert any("False" in a for a in all_info_args)

    def test_banner_logs_stream_names(self) -> None:
        from hermes.server import _log_startup_banner

        streams = ["homeric-agents", "homeric-tasks"]
        publisher = self._make_publisher(stream_names=streams)
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher)

        all_info_args = [str(c) for c in mock_logger.info.call_args_list]
        assert any("homeric-agents" in a for a in all_info_args)
        assert any("homeric-tasks" in a for a in all_info_args)

    def test_banner_logs_empty_streams_when_not_connected(self) -> None:
        from hermes.server import _log_startup_banner

        publisher = self._make_publisher(is_connected=False, stream_names=[])
        with patch("hermes.server.logger") as mock_logger:
            _log_startup_banner(publisher)

        # Should still log the nats line — just with empty list
        assert mock_logger.info.call_count >= 4
