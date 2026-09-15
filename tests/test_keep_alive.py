"""Synthetic responses only; never rotate tokens or create real webhooks."""

import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

with patch.dict(os.environ, {"PATREON_CLIENT_ID": "fixture-client", "PATREON_CLIENT_SECRET": "fixture-secret"}):
    keep_alive = importlib.import_module("keep_alive")


def response(status: int, body: object = None) -> requests.Response:
    value = requests.Response()
    value.status_code = status
    value._content = json.dumps(body).encode()
    value._content_consumed = True
    value.url = "https://www.patreon.com/fixture"
    return value


class KeepAliveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token_file = Path(self.temp.name) / "token.txt"
        self.token_file.write_text("fixture-old-refresh", encoding="utf-8")
        self.enterContext(patch.object(keep_alive, "TOKEN_FILE", str(self.token_file)))
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(patch.object(keep_alive.time, "sleep"))

    def test_refresh_has_deadlines_and_refuses_redirects(self) -> None:
        with patch.object(keep_alive.requests, "post", return_value=response(200, {
            "refresh_token": "fixture-new-refresh", "access_token": "fixture-access"
        })) as post:
            self.assertEqual(keep_alive.get_tokens(), "fixture-access")
        self.assertEqual(post.call_args.kwargs["timeout"], (5, 20))
        self.assertIs(post.call_args.kwargs["allow_redirects"], False)
        self.assertEqual(self.token_file.read_text(), "fixture-new-refresh")

    def test_auth_failure_never_logs_provider_body(self) -> None:
        with patch.object(keep_alive.requests, "post", return_value=response(401, {"error": "fixture-sensitive-body"})):
            with self.assertRaises(keep_alive.KeepAliveError):
                keep_alive.get_tokens()
        self.assertNotIn("fixture-sensitive-body", self.output.getvalue())
        self.assertEqual(self.token_file.read_text(), "fixture-old-refresh")

    def test_invalid_refresh_payload_preserves_current_token(self) -> None:
        for token in (None, "", " ", 123, {}, []):
            with self.subTest(token=token):
                self.token_file.write_text("fixture-old-refresh")
                with patch.object(keep_alive.requests, "post", return_value=response(200, {"refresh_token": token, "access_token": "fixture-access"})):
                    with self.assertRaises(keep_alive.KeepAliveError):
                        keep_alive.get_tokens()
                self.assertEqual(self.token_file.read_text(), "fixture-old-refresh")

    def test_valid_rotation_is_retained_when_access_token_is_invalid(self) -> None:
        with patch.object(keep_alive.requests, "post", return_value=response(200, {"refresh_token": "fixture-new-refresh"})):
            with self.assertRaises(keep_alive.KeepAliveError):
                keep_alive.get_tokens()
        self.assertEqual(self.token_file.read_text(), "fixture-new-refresh")

    def test_success_requires_confirmed_delete_and_bounded_calls(self) -> None:
        with patch.object(keep_alive.requests, "post", return_value=response(201, {"data": {"id": "123456"}})) as post, \
             patch.object(keep_alive.requests, "delete", return_value=response(204)) as delete:
            keep_alive.trigger_webhook_activity("fixture-access")
        for call in (post.call_args, delete.call_args):
            self.assertEqual(call.kwargs["timeout"], (5, 20))
            self.assertIs(call.kwargs["allow_redirects"], False)
        self.assertTrue(delete.call_args.args[0].endswith("/webhooks/123456"))
        self.assertIn("Activity Registered", self.output.getvalue())

    def test_failed_or_incomplete_deletion_does_not_report_success(self) -> None:
        for status in (202, 301, 401, 429, 500):
            with self.subTest(status=status):
                with patch.object(keep_alive.requests, "post", return_value=response(201, {"data": {"id": "123456"}})), \
                     patch.object(keep_alive.requests, "delete", return_value=response(status, "fixture-sensitive-delete-body")) as delete:
                    with self.assertRaises(keep_alive.KeepAliveError):
                        keep_alive.trigger_webhook_activity("fixture-access")
                self.assertEqual(delete.call_count, 1)
        self.assertNotIn("Activity Registered", self.output.getvalue())
        self.assertNotIn("fixture-sensitive-delete-body", self.output.getvalue())

    def test_unexpected_create_status_never_deletes(self) -> None:
        for status in (200, 202, 302, 401, 500):
            with self.subTest(status=status):
                with patch.object(keep_alive.requests, "post", return_value=response(status, {"data": {"id": "123456"}, "detail": "fixture-private-create"})), \
                     patch.object(keep_alive.requests, "delete") as delete:
                    with self.assertRaises(keep_alive.KeepAliveError):
                        keep_alive.trigger_webhook_activity("fixture-access")
                delete.assert_not_called()
        self.assertNotIn("fixture-private-create", self.output.getvalue())

    def test_invalid_webhook_identity_never_reaches_delete(self) -> None:
        for identity in (None, "", "../other", "1?scope=other", "1/2", "1#fragment", 123):
            with self.subTest(identity=identity):
                with patch.object(keep_alive.requests, "post", return_value=response(201, {"data": {"id": identity}})), \
                     patch.object(keep_alive.requests, "delete") as delete:
                    with self.assertRaises(keep_alive.KeepAliveError):
                        keep_alive.trigger_webhook_activity("fixture-access")
                delete.assert_not_called()

    def test_main_sanitizes_exception_and_exits_nonzero(self) -> None:
        with patch.object(keep_alive, "get_tokens", side_effect=requests.Timeout("fixture-secret-in-exception")):
            with self.assertRaises(SystemExit) as caught:
                keep_alive.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertNotIn("fixture-secret-in-exception", self.output.getvalue())

    def test_post_timeout_is_not_automatically_retried(self) -> None:
        with patch.object(keep_alive.requests, "post", side_effect=requests.Timeout("fixture-timeout")) as post:
            with self.assertRaises(keep_alive.KeepAliveError):
                keep_alive.get_tokens()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(self.token_file.read_text(), "fixture-old-refresh")

    def test_later_activity_failure_retains_rotated_refresh(self) -> None:
        replies = [response(200, {"refresh_token": "fixture-new-refresh", "access_token": "fixture-access"}), response(503)]
        with patch.object(keep_alive.requests, "post", side_effect=replies), \
             patch.object(keep_alive.requests, "delete") as delete:
            with self.assertRaises(SystemExit) as caught:
                keep_alive.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(self.token_file.read_text(), "fixture-new-refresh")
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
