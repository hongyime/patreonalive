"""Synthetic stdlib HTTP responses only; never contact Patreon."""

import contextlib
from email.message import Message
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs
from urllib.response import addinfourl

import get_token
import keep_alive


def response(status: int, body: object = None):
    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    return addinfourl(io.BytesIO(payload), Message(), "https://www.patreon.com/fixture", status)


def http_error(status: int, body: object = None) -> HTTPError:
    payload = b"" if body is None else json.dumps(body).encode("utf-8")
    return HTTPError("https://www.patreon.com/fixture", status, "fixture", Message(), io.BytesIO(payload))


class KeepAliveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token_file = Path(self.temp.name) / "token.txt"
        self.token_file.write_text("fixture-old-refresh", encoding="utf-8")
        self.enterContext(patch.dict(os.environ, {
            "PATREON_CLIENT_ID": "fixture-client",
            "PATREON_CLIENT_SECRET": "fixture-secret",
        }))
        self.enterContext(patch.object(keep_alive, "TOKEN_FILE", str(self.token_file)))
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(patch.object(keep_alive.time, "sleep"))

    def test_import_without_credentials(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIs(importlib.reload(keep_alive), keep_alive)
        importlib.reload(keep_alive)

    def test_refresh_has_timeout_and_refuses_redirects(self) -> None:
        with patch.object(keep_alive.OPENER, "open", return_value=response(200, {
            "refresh_token": "fixture-new-refresh", "access_token": "fixture-access",
        })) as open_request:
            self.assertEqual(keep_alive.get_tokens(), "fixture-access")
        sent = open_request.call_args.args[0]
        self.assertEqual(open_request.call_args.kwargs["timeout"], 20)
        self.assertEqual(sent.get_method(), "POST")
        self.assertEqual(parse_qs(sent.data.decode())["refresh_token"], ["fixture-old-refresh"])
        self.assertEqual(sent.get_header("User-agent"), keep_alive.USER_AGENT)
        self.assertIsNone(keep_alive.NoRedirect().redirect_request(None, None, 302, "", Message(), "https://elsewhere"))
        self.assertEqual(self.token_file.read_text(encoding="utf-8"), "fixture-new-refresh")

    def test_auth_failure_never_logs_provider_body(self) -> None:
        with patch.object(keep_alive.OPENER, "open", side_effect=http_error(401, {"error": "fixture-sensitive-body"})):
            with self.assertRaises(keep_alive.KeepAliveError):
                keep_alive.get_tokens()
        self.assertNotIn("fixture-sensitive-body", self.output.getvalue())
        self.assertEqual(self.token_file.read_text(encoding="utf-8"), "fixture-old-refresh")

    def test_invalid_refresh_payload_preserves_current_token(self) -> None:
        for token in (None, "", " ", 123, {}, []):
            with self.subTest(token=token):
                self.token_file.write_text("fixture-old-refresh", encoding="utf-8")
                with patch.object(keep_alive.OPENER, "open", return_value=response(200, {"refresh_token": token, "access_token": "fixture-access"})):
                    with self.assertRaises(keep_alive.KeepAliveError):
                        keep_alive.get_tokens()
                self.assertEqual(self.token_file.read_text(encoding="utf-8"), "fixture-old-refresh")

    def test_valid_rotation_is_retained_when_access_token_is_invalid(self) -> None:
        with patch.object(keep_alive.OPENER, "open", return_value=response(200, {"refresh_token": "fixture-new-refresh"})):
            with self.assertRaises(keep_alive.KeepAliveError):
                keep_alive.get_tokens()
        self.assertEqual(self.token_file.read_text(encoding="utf-8"), "fixture-new-refresh")

    def test_success_requires_confirmed_delete_and_bounded_calls(self) -> None:
        with patch.object(keep_alive.OPENER, "open", side_effect=[response(201, {"data": {"id": "123456"}}), response(204)]) as open_request:
            keep_alive.trigger_webhook_activity("fixture-access")
        self.assertEqual(open_request.call_count, 2)
        for call in open_request.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 20)
        self.assertTrue(open_request.call_args_list[1].args[0].full_url.endswith("/webhooks/123456"))
        self.assertIn("Activity Registered", self.output.getvalue())

    def test_failed_or_incomplete_deletion_does_not_report_success(self) -> None:
        for status in (202, 301, 401, 429, 500):
            with self.subTest(status=status):
                failure = http_error(status, "fixture-sensitive-delete-body") if status >= 400 else response(status, "fixture-sensitive-delete-body")
                with patch.object(keep_alive.OPENER, "open", side_effect=[response(201, {"data": {"id": "123456"}}), failure]) as open_request:
                    with self.assertRaises(keep_alive.KeepAliveError):
                        keep_alive.trigger_webhook_activity("fixture-access")
                self.assertEqual(open_request.call_count, 2)
        self.assertNotIn("Activity Registered", self.output.getvalue())
        self.assertNotIn("fixture-sensitive-delete-body", self.output.getvalue())

    def test_unexpected_create_status_never_deletes(self) -> None:
        for status in (200, 202, 302, 401, 500):
            with self.subTest(status=status):
                failure = http_error(status, {"data": {"id": "123456"}, "detail": "fixture-private-create"}) if status >= 400 else response(status, {"data": {"id": "123456"}, "detail": "fixture-private-create"})
                open_patch = patch.object(keep_alive.OPENER, "open", side_effect=failure) if status >= 400 else patch.object(keep_alive.OPENER, "open", return_value=failure)
                with open_patch as open_request:
                    with self.assertRaises(keep_alive.KeepAliveError):
                        keep_alive.trigger_webhook_activity("fixture-access")
                self.assertEqual(open_request.call_count, 1)
        self.assertNotIn("fixture-private-create", self.output.getvalue())

    def test_invalid_webhook_identity_never_reaches_delete(self) -> None:
        for identity in (None, "", "../other", "1?scope=other", "1/2", "1#fragment", 123):
            with self.subTest(identity=identity):
                with patch.object(keep_alive.OPENER, "open", return_value=response(201, {"data": {"id": identity}})) as open_request:
                    with self.assertRaises(keep_alive.KeepAliveError):
                        keep_alive.trigger_webhook_activity("fixture-access")
                self.assertEqual(open_request.call_count, 1)

    def test_main_sanitizes_exception_and_exits_nonzero(self) -> None:
        with patch.object(keep_alive, "get_tokens", side_effect=TimeoutError("fixture-secret-in-exception")):
            with self.assertRaises(SystemExit) as caught:
                keep_alive.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertNotIn("fixture-secret-in-exception", self.output.getvalue())

    def test_post_timeout_is_not_automatically_retried(self) -> None:
        with patch.object(keep_alive.OPENER, "open", side_effect=TimeoutError("fixture-timeout")) as open_request:
            with self.assertRaises(keep_alive.KeepAliveError):
                keep_alive.get_tokens()
        self.assertEqual(open_request.call_count, 1)
        self.assertEqual(self.token_file.read_text(encoding="utf-8"), "fixture-old-refresh")

    def test_later_activity_failure_retains_rotated_refresh(self) -> None:
        replies = [response(200, {"refresh_token": "fixture-new-refresh", "access_token": "fixture-access"}), response(503)]
        with patch.object(keep_alive.OPENER, "open", side_effect=replies) as open_request:
            with self.assertRaises(SystemExit) as caught:
                keep_alive.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(self.token_file.read_text(encoding="utf-8"), "fixture-new-refresh")
        self.assertEqual(open_request.call_count, 2)

    def test_missing_configuration_and_bootstrap_token_have_annotated_exits(self) -> None:
        with patch.dict(os.environ, {"PATREON_CLIENT_ID": "", "PATREON_CLIENT_SECRET": ""}):
            with self.assertRaises(keep_alive.KeepAliveError) as missing_config:
                keep_alive.get_tokens()
        self.assertIn("PATREON_CLIENT_ID", str(missing_config.exception))

        self.token_file.unlink()
        with patch.dict(os.environ, {"PATREON_REFRESH_TOKEN": ""}):
            with self.assertRaises(SystemExit) as missing_token:
                keep_alive.main()
        self.assertEqual(missing_token.exception.code, 1)
        self.assertIn("::error::Token refresh: no cached token.txt", self.output.getvalue())

    def test_utf8_cached_token_is_used(self) -> None:
        self.token_file.write_text("刷新-token", encoding="utf-8")
        with patch.object(keep_alive.OPENER, "open", return_value=response(200, {
            "refresh_token": "fixture-new-refresh", "access_token": "fixture-access",
        })) as open_request:
            keep_alive.get_tokens()
        sent = open_request.call_args.args[0]
        self.assertEqual(parse_qs(sent.data.decode("utf-8"))["refresh_token"], ["刷新-token"])

    def test_campaign_id_and_user_agent_are_configured(self) -> None:
        with patch.object(keep_alive, "CAMPAIGN_ID", "fixture-campaign"), \
             patch.object(keep_alive.OPENER, "open", side_effect=[response(201, {"data": {"id": "123456"}}), response(204)]) as open_request:
            keep_alive.trigger_webhook_activity("fixture-access")
        payload = json.loads(open_request.call_args_list[0].args[0].data.decode("utf-8"))
        self.assertEqual(payload["data"]["relationships"]["campaign"]["data"]["id"], "fixture-campaign")
        self.assertEqual(keep_alive.USER_AGENT, get_token.USER_AGENT)

    def test_campaign_id_defaults_when_environment_is_blank(self) -> None:
        with patch.dict(os.environ, {"PATREON_CAMPAIGN_ID": ""}):
            importlib.reload(keep_alive)
            self.assertEqual(keep_alive.CAMPAIGN_ID, "12502474")
        importlib.reload(keep_alive)


if __name__ == "__main__":
    unittest.main()
