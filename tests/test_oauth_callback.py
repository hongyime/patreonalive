"""Exercise real loopback HTTP; never contact Patreon or load saved tokens."""

import contextlib
import http.client
import io
import socket
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

import get_token
from oauth_callback import (
    CallbackServer,
    OAuthAuthorizationError,
    capture_authorization_code,
    redirect_address,
)


class CallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = CallbackServer(("127.0.0.1", 0), "/callback", timeout=5)
        self.addCleanup(self.server.server_close)

    def request(self, target: str, headers: dict | None = None) -> tuple:
        worker = threading.Thread(target=self.server.handle_request)
        worker.start()
        client = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            client.request("GET", target, headers=headers or {})
            response = client.getresponse()
            result = response.status, dict(response.getheaders()), response.read().decode()
        finally:
            client.close()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        return result

    def callback(self, **params: str) -> str:
        return "/callback?" + urlencode({"state": self.server.state, **params})

    def test_valid_code_and_private_response(self) -> None:
        status, headers, body = self.request(self.callback(code="fixture-code"))
        self.assertEqual(status, 200)
        self.assertEqual(self.server.wait_for_code(), "fixture-code")
        self.assertNotIn("fixture-code", body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")

    def test_invalid_state_is_not_terminal(self) -> None:
        for state in ("wrong", "", "非ASCII"):
            with self.subTest(state=state):
                self.assertEqual(self.request(self.callback(state=state, code="bad"))[0], 400)
                self.assertIsNone(self.server.code)
                self.assertIsNone(self.server.error)
        self.assertEqual(self.request(self.callback(code="good"))[0], 200)
        self.assertEqual(self.server.wait_for_code(), "good")

    def test_noise_and_wrong_paths_are_not_terminal(self) -> None:
        for path in ("/favicon.ico", "/", "/elsewhere?code=bad", "http://elsewhere/callback"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)
                self.assertIsNone(self.server.error)
        self.assertEqual(self.request(self.callback(code="good"))[0], 200)

    def test_malformed_queries_are_not_terminal(self) -> None:
        state = urlencode({"state": self.server.state})
        for query in (
            "code=bad", f"{state}&{state}&code=bad", f"{state}&code=",
            f"{state}&code=a&code=b", f"{state}&code=a&error=b",
            f"{state}&error=", f"{state}&error=a&error=b", state,
            f"{state}&code={'x' * 8193}", f"{state}&error=a&error_description=a&error_description=b",
            f"{state}&code=a&" + "&".join(f"x{i}=a" for i in range(12)),
        ):
            with self.subTest(query=query[:80]):
                self.assertEqual(self.request("/callback?" + query)[0], 400)
                self.assertIsNone(self.server.code)
                self.assertIsNone(self.server.error)
        self.assertEqual(self.request(self.callback(code="good"))[0], 200)

    def test_wrong_host_is_rejected(self) -> None:
        self.assertEqual(self.request(self.callback(code="bad"), {"Host": "elsewhere"})[0], 400)
        self.assertIsNone(self.server.code)

    def test_matching_error_is_terminal_and_escaped(self) -> None:
        status, _, body = self.request(self.callback(error="denied", error_description="<script>fixture</script>"))
        self.assertEqual(status, 400)
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)
        with self.assertRaises(OAuthAuthorizationError):
            self.server.wait_for_code()

    def test_replay_does_not_replace_result(self) -> None:
        self.request(self.callback(code="first"))
        self.assertEqual(self.request(self.callback(code="second"))[0], 410)
        self.assertEqual(self.server.code, "first")

    def test_session_state_is_fresh(self) -> None:
        with CallbackServer(("127.0.0.1", 0), "/callback", timeout=5) as other:
            self.assertNotEqual(self.server.state, other.state)
            self.assertGreaterEqual(len(other.state), 40)
            self.assertIsNone(other.code)


class DeadlineTests(unittest.TestCase):
    def test_idle_timeout_closes_listener_and_timer(self) -> None:
        started = time.monotonic()
        with CallbackServer(("127.0.0.1", 0), "/callback", timeout=0.25) as server:
            port = server.server_port
            with self.assertRaises(TimeoutError):
                server.wait_for_code()
        self.assertLess(time.monotonic() - started, 3)
        self.assertFalse(server.deadline_timer.is_alive())
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))

    def test_partial_request_cannot_extend_deadline(self) -> None:
        self.check_stalled_request(trickle=False)

    def test_trickling_headers_cannot_extend_deadline(self) -> None:
        self.check_stalled_request(trickle=True)

    def check_stalled_request(self, *, trickle: bool) -> None:
        with CallbackServer(("127.0.0.1", 0), "/callback", timeout=0.5) as server:
            client = socket.create_connection(server.server_address, timeout=2)
            self.addCleanup(client.close)
            client.sendall(b"GET /callback HTTP/1.1\r\nHost: localhost\r\nX-Fixture: ")
            stop = threading.Event()

            def send_bytes() -> None:
                while not stop.wait(0.04):
                    try:
                        client.sendall(b"a")
                    except OSError:
                        return

            worker = threading.Thread(target=send_bytes)
            if trickle:
                worker.start()
            started = time.monotonic()
            try:
                with self.assertRaises(TimeoutError):
                    server.wait_for_code()
            finally:
                stop.set()
                if trickle:
                    worker.join(2)
                    self.assertFalse(worker.is_alive())
            self.assertLess(time.monotonic() - started, 3)
            self.assertIsNone(server.code)
        self.assertFalse(server.deadline_timer.is_alive())

    def test_exception_cleans_up(self) -> None:
        with self.assertRaises(KeyboardInterrupt):
            with CallbackServer(("127.0.0.1", 0), "/callback", timeout=5) as server:
                raise KeyboardInterrupt
        self.assertEqual(server.socket.fileno(), -1)
        self.assertFalse(server.deadline_timer.is_alive())


class BootstrapTests(unittest.TestCase):
    def test_redirect_configuration(self) -> None:
        self.assertEqual(redirect_address("http://localhost:8123/custom"), (("127.0.0.1", 8123), "/custom"))
        self.assertEqual(redirect_address("http://127.0.0.1/callback"), (("127.0.0.1", 80), "/callback"))
        for uri in ("https://localhost:8080/callback", "http://example.com/callback",
                    "http://user@localhost/callback", "http://localhost:0/callback",
                    "http://localhost:bad/callback", "http://localhost:70000/callback",
                    "http://localhost/callback?x=y", "http://localhost/callback#part"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                redirect_address(uri)

    def test_invalid_configuration_does_not_open_browser(self) -> None:
        for timeout in (0, -1, float("inf"), float("nan"), 901):
            with self.subTest(timeout=timeout), patch("oauth_callback.webbrowser.open") as opener:
                with self.assertRaises(ValueError):
                    capture_authorization_code("fixture", "http://localhost:8080/callback", "scope", timeout=timeout)
                opener.assert_not_called()

    def test_authorization_url_and_real_callback(self) -> None:
        clients = []
        servers = []

        def factory(address, path, **kwargs):
            server = CallbackServer(("127.0.0.1", 0), path, **kwargs)
            servers.append(server)
            return server

        def open_fixture(url: str) -> bool:
            parsed = urlsplit(url)
            params = parse_qs(parsed.query)
            self.assertEqual(parsed.netloc, "www.patreon.com")
            self.assertEqual(params["scope"], ["w:campaigns.webhook"])
            self.assertEqual(params["redirect_uri"], ["http://localhost:8123/custom"])
            self.assertEqual(params["state"], [servers[0].state])

            def respond() -> None:
                with contextlib.closing(http.client.HTTPConnection(*servers[0].server_address, timeout=3)) as client:
                    client.request("GET", "/custom?" + urlencode({"state": params["state"][0], "code": "fixture-code"}))
                    client.getresponse().read()

            worker = threading.Thread(target=respond)
            clients.append(worker)
            worker.start()
            return True

        with patch("oauth_callback.CallbackServer", side_effect=factory), patch("oauth_callback.webbrowser.open", side_effect=open_fixture), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(capture_authorization_code("fixture", "http://localhost:8123/custom", "w:campaigns.webhook", timeout=5), "fixture-code")
        for worker in clients:
            worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertFalse(servers[0].deadline_timer.is_alive())

    def test_callback_failures_never_exchange_tokens(self) -> None:
        for error, exit_code in ((TimeoutError(), 1), (OAuthAuthorizationError("denied"), 1), (ValueError(), 1), (OSError(), 1), (KeyboardInterrupt(), 130)):
            with self.subTest(error=type(error).__name__), patch.multiple(get_token, CLIENT_ID="fixture", CLIENT_SECRET="fixture"), patch.object(get_token, "capture_authorization_code", side_effect=error), patch.object(get_token, "_exchange_via_curl") as curl, patch.object(get_token, "_exchange_via_requests") as requests, contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    get_token.main()
                self.assertEqual(result.exception.code, exit_code)
                curl.assert_not_called()
                requests.assert_not_called()

    def test_browser_failure_preserves_manual_callback(self) -> None:
        with patch("oauth_callback.webbrowser.open", side_effect=OSError("fixture browser unavailable")), patch.object(CallbackServer, "wait_for_code", return_value="fixture-code"), contextlib.redirect_stdout(io.StringIO()) as output:
            with patch("oauth_callback.redirect_address", return_value=(("127.0.0.1", 0), "/callback")):
                self.assertEqual(capture_authorization_code("fixture", "http://localhost:8080/callback", "scope"), "fixture-code")
        self.assertIn("Use the printed URL manually", output.getvalue())

    def test_success_exchanges_only_validated_code(self) -> None:
        with patch.multiple(get_token, CLIENT_ID="fixture", CLIENT_SECRET="fixture"), patch.object(get_token, "capture_authorization_code", return_value="fixture-code"), patch.object(get_token, "_exchange_via_curl", return_value={"refresh_token": "fixture-refresh"}) as curl, patch.object(get_token, "_exchange_via_requests") as requests, contextlib.redirect_stdout(io.StringIO()) as output:
            get_token.main()
        curl.assert_called_once_with("fixture-code")
        requests.assert_not_called()
        self.assertNotIn("fixture-code", output.getvalue())


if __name__ == "__main__":
    unittest.main()
