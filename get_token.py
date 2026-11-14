"""
One-shot bootstrap for the Patreon OAuth refresh_token.

This uses a local HTTP server on 127.0.0.1:8080 to capture the OAuth
redirect. Add `http://localhost:8080/callback` to your Patreon app's
Redirect URIs list first (Patreon requires http/https URLs — the
older `urn:ietf:wg:oauth:2.0:oob` doesn't work in their dashboard).

Usage (PowerShell):
    # Run from the repository directory.
    $env:PATREON_CLIENT_ID = '<your-client-id>'
    $env:PATREON_CLIENT_SECRET = '<your-new-client-secret>'
    python get_token.py

The script uses only the Python standard library. It starts a local callback
server, opens the Patreon authorization URL, exchanges the validated code, and
prints the refresh token for manual secret setup.
"""

import json
import os
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from oauth_callback import OAuthAuthorizationError, capture_authorization_code

CLIENT_ID = os.environ.get("PATREON_CLIENT_ID")
CLIENT_SECRET = os.environ.get("PATREON_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("PATREON_REDIRECT_URI", "http://localhost:8080/callback")
SCOPES = "w:campaigns.webhook"
TOKEN_URL = "https://www.patreon.com/api/oauth2/token"
USER_AGENT = "PatreonKeepAlive/5.0"
CURL_UNAVAILABLE = object()


def main() -> None:
    missing = []
    if not CLIENT_ID:
        missing.append("PATREON_CLIENT_ID")
    if not CLIENT_SECRET:
        missing.append("PATREON_CLIENT_SECRET")
    if missing:
        print(f"ERROR: env vars not set: {', '.join(missing)}")
        print("Set them (PowerShell):")
        print("  $env:PATREON_CLIENT_ID='<your-client-id>'")
        print("  $env:PATREON_CLIENT_SECRET='<your-new-client-secret>'")
        sys.exit(1)

    try:
        timeout = float(os.environ.get("PATREON_AUTH_TIMEOUT", "300"))
        code = capture_authorization_code(CLIENT_ID, REDIRECT_URI, SCOPES, timeout=timeout)
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        sys.exit(130)
    except (OAuthAuthorizationError, ValueError, OSError) as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    print("Authorization code received.")
    print("Exchanging code for tokens...")
    tokens = _exchange_via_curl(code)
    if tokens is CURL_UNAVAILABLE:
        tokens = _exchange_via_urllib(code)
    if not tokens:
        sys.exit(1)

    refresh_token = tokens.get("refresh_token") if isinstance(tokens, dict) else None
    if not isinstance(refresh_token, str) or not refresh_token:
        print("ERROR: response missing refresh_token")
        sys.exit(1)

    print()
    print("=" * 70)
    print("SUCCESS — copy the value below into the PATREON_REFRESH_TOKEN secret:")
    print()
    print(refresh_token)
    print()
    print("Or run this directly (one-shot):")
    print()
    print(f'    gh secret set PATREON_REFRESH_TOKEN --repo hongyime/patreonalive --body "{refresh_token}"')
    print("=" * 70)


def _form_body(code: str) -> bytes:
    return urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
    }).encode("utf-8")


def _safe_status(status: object) -> str:
    value = str(status)
    return value if re.fullmatch(r"[0-9]{3}", value) else "?"


def _oauth_error(body: bytes | str) -> str | None:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    error = value.get("error") if isinstance(value, dict) else None
    return error if isinstance(error, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", error) else None


def _report_exchange_failure(transport: str, status: object, body: bytes | str = b"") -> None:
    message = f"{transport} exchange failed (HTTP {_safe_status(status)})"
    if error := _oauth_error(body):
        message += f": {error}"
    print(message)


def _parse_exchange_response(transport: str, status: object, body: bytes) -> dict | None:
    if _safe_status(status) != "200":
        _report_exchange_failure(transport, status, body)
        return None
    try:
        tokens = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        _report_exchange_failure(transport, status)
        return None
    if not isinstance(tokens, dict):
        _report_exchange_failure(transport, status)
        return None
    return tokens


def _curl_output(output: bytes) -> tuple[str, bytes]:
    body, marker, status = output.rpartition(b"\n---HTTP_STATUS:")
    if not marker:
        return "?", output
    return _safe_status(status.strip().decode("ascii", "ignore")), body


def _exchange_via_curl(code: str) -> dict | object | None:
    """Use curl when available; an attempted exchange is never retried."""
    form_body = _form_body(code)
    for curl in ("curl.exe", "curl"):
        try:
            result = subprocess.run(
                [
                    curl,
                    "-q",
                    "-sS",
                    "-X", "POST",
                    TOKEN_URL,
                    "-H", f"User-Agent: {USER_AGENT}",
                    "-H", "Accept: application/json",
                    "-H", "Content-Type: application/x-www-form-urlencoded",
                    "--data-binary", "@-",
                    "-w", "\n---HTTP_STATUS:%{http_code}",
                ],
                input=form_body,
                capture_output=True,
                timeout=30,
            )
        except FileNotFoundError:
            continue
        except (OSError, subprocess.TimeoutExpired):
            _report_exchange_failure("curl", "?")
            return None

        status, body = _curl_output(result.stdout)
        if result.returncode != 0:
            _report_exchange_failure("curl", status, body)
            return None
        return _parse_exchange_response("curl", status, body)

    print("curl not available on PATH; using Python urllib.")
    return CURL_UNAVAILABLE


def _exchange_via_urllib(code: str) -> dict | None:
    """Use the standard-library fallback only when curl is unavailable."""
    print("Trying token exchange via Python urllib...")
    request = Request(
        TOKEN_URL,
        data=_form_body(code),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return _parse_exchange_response("urllib", response.getcode(), response.read())
    except HTTPError as error:
        try:
            body = error.read()
        finally:
            error.close()
        _report_exchange_failure("urllib", error.code, body)
    except (OSError, TimeoutError, URLError):
        _report_exchange_failure("urllib", "?")
    return None


if __name__ == "__main__":
    main()
