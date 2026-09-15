"""One-use, state-bound OAuth callback on the IPv4 loopback interface."""

import html
import math
import secrets
import socket
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit


class OAuthAuthorizationError(Exception):
    """The matching authorization request was denied by the provider."""


def redirect_address(uri: str) -> tuple[tuple[str, int], str]:
    """Accept only a registered HTTP callback this local listener can serve."""
    parsed = urlsplit(uri)
    port = parsed.port if parsed.port is not None else 80
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or not 1 <= port <= 65535):
        raise ValueError("PATREON_REDIRECT_URI must be an HTTP localhost/127.0.0.1 URL with a valid port and no credentials, query or fragment.")
    return ("127.0.0.1", port), parsed.path or "/"


class CallbackServer(HTTPServer):
    """A deadline also interrupts incomplete or trickling HTTP requests."""

    def __init__(self, address: tuple[str, int], path: str, *, timeout: float = 300) -> None:
        if not math.isfinite(timeout) or not 0 < timeout <= 900:
            raise ValueError("PATREON_AUTH_TIMEOUT must be greater than 0 and at most 900 seconds.")
        self.state = secrets.token_urlsafe(32)
        self.callback_path = path
        self.code: str | None = None
        self.error: str | None = None
        self._lock = threading.Lock()
        self._active: socket.socket | None = None
        self._expired = False
        self.deadline_timer: threading.Timer | None = None
        super().__init__(address, CallbackHandler)
        self.timeout = min(timeout, 0.2)
        self._deadline = time.monotonic() + timeout
        self.deadline_timer = threading.Timer(timeout, self._expire)
        self.deadline_timer.daemon = True
        self.deadline_timer.start()

    @staticmethod
    def _interrupt(connection: socket.socket | None) -> None:
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                # A peer may have closed the socket before the deadline fired.
                return

    def _expire(self) -> None:
        with self._lock:
            self._expired = True
            self._interrupt(self._active)

    def get_request(self) -> tuple[socket.socket, tuple]:
        connection, address = super().get_request()
        # Windows shutdown alone may not immediately interrupt a buffered read.
        # Bound socket operations too; the timer still stops continuously active peers.
        connection.settimeout(min(1.0, max(0.001, self._deadline - time.monotonic())))
        with self._lock:
            if self._expired:
                connection.close()
                raise TimeoutError("Authorization callback timed out.")
            self._active = connection
        return connection, address

    def shutdown_request(self, request: socket.socket) -> None:
        with self._lock:
            if self._active is request:
                self._active = None
        super().shutdown_request(request)

    def accept_result(self, *, code: str | None, error: str | None) -> bool:
        with self._lock:
            if self.code is not None or self.error is not None or self._expired or time.monotonic() >= self._deadline:
                return False
            self.code, self.error = code, error
            return True

    def wait_for_code(self) -> str:
        while self.code is None and self.error is None:
            if self._expired or time.monotonic() >= self._deadline:
                raise TimeoutError("Authorization callback timed out. Run get_token.py again for a fresh authorization URL.")
            self.handle_request()
        if self.error is not None:
            raise OAuthAuthorizationError(self.error)
        return self.code

    def server_close(self) -> None:
        if self.deadline_timer is not None:
            self.deadline_timer.cancel()
            self.deadline_timer.join()
        self._expire()
        super().server_close()


class CallbackHandler(BaseHTTPRequestHandler):
    server: CallbackServer

    def handle(self) -> None:
        try:
            super().handle()
        except OSError:
            # A timeout, peer disconnect or deadline shutdown is ordinary here.
            return

    def do_GET(self) -> None:
        try:
            target = urlsplit(self.path)
        except ValueError:
            self.respond(400, "Invalid callback.")
            return
        if target.scheme or target.netloc or target.path != self.server.callback_path:
            self.respond(404, "Nothing here. Return to the Patreon authorization page.")
            return
        hosts = self.headers.get_all("Host", [])
        allowed_hosts = {f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"}
        if self.server.server_port == 80:
            allowed_hosts.update({"localhost", "127.0.0.1"})
        if len(hosts) != 1 or hosts[0].lower() not in allowed_hosts:
            self.respond(400, "Invalid callback host.")
            return
        try:
            params = parse_qs(target.query, keep_blank_values=True, max_num_fields=10, errors="strict")
        except (ValueError, UnicodeError):
            self.respond(400, "Invalid callback parameters.")
            return
        state = params.get("state", [])
        if (len(state) != 1 or len(state[0]) > 128
                or not secrets.compare_digest(state[0].encode("utf-8"), self.server.state.encode("utf-8"))):
            self.respond(400, "Callback state did not match. Return to the original authorization page.")
            return
        codes, errors = params.get("code", []), params.get("error", [])
        descriptions = params.get("error_description", [""])
        code_valid = len(codes) == 1 and 0 < len(codes[0]) <= 8192 and not errors
        error_valid = (len(errors) == 1 and 0 < len(errors[0]) <= 256 and not codes
                       and len(descriptions) == 1 and len(descriptions[0]) <= 2000)
        if not (code_valid or error_valid):
            self.respond(400, "Expected one authorization code or one provider error.")
            return
        code = codes[0] if code_valid else None
        error = f"{errors[0]}: {descriptions[0]}" if error_valid else None
        if not self.server.accept_result(code=code, error=error):
            self.respond(410, "This authorization attempt has already ended.")
            return
        self.respond(400 if error else 200, error or "Code received. Close this tab and return to the terminal.")

    def respond(self, status: int, message: str) -> None:
        body = ("<!doctype html><html><head><title>Patreon authorization</title></head>"
                "<body><p>" + html.escape(message) + "</p></body></html>").encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            # Disconnected clients and the absolute deadline can interrupt writes.
            return

    def log_message(self, format: str, *args: object) -> None:
        # Request URLs contain authorization material; never log them.
        return


def capture_authorization_code(client_id: str, redirect_uri: str, scopes: str, *, timeout: float = 300) -> str:
    address, path = redirect_address(redirect_uri)
    with CallbackServer(address, path, timeout=timeout) as server:
        auth_url = "https://www.patreon.com/oauth2/authorize?" + urlencode({
            "response_type": "code", "client_id": client_id,
            "redirect_uri": redirect_uri, "scope": scopes, "state": server.state,
        })
        print(f"Register this exact redirect URI on your Patreon app: {redirect_uri}")
        print("At: https://www.patreon.com/portal/registration/register-clients")
        print(f"Opening authorization URL (copy into your browser if needed):\n    {auth_url}")
        print(f"Waiting up to {timeout:g} seconds for authorization; Ctrl+C cancels.")
        try:
            webbrowser.open(auth_url)
        except (webbrowser.Error, OSError):
            print("The browser could not open. Use the printed URL manually.")
        return server.wait_for_code()
