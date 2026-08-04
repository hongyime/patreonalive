"""
One-shot bootstrap for the Patreon OAuth refresh_token.

This uses a local HTTP server on 127.0.0.1:8080 to capture the OAuth
redirect. Add `http://localhost:8080/callback` to your Patreon app's
Redirect URIs list first (Patreon requires http/https URLs — the
older `urn:ietf:wg:oauth:2.0:oob` doesn't work in their dashboard).

Usage (PowerShell):
    cd 'X:\01 REPOSITORIES\patreonalive'
    $env:PATREON_CLIENT_ID = '<your-client-id>'
    $env:PATREON_CLIENT_SECRET = '<your-new-client-secret>'
    python get_token.py

The script:
  1. Starts a local HTTP server on 127.0.0.1:8080/callback.
  2. Prints the Patreon authorization URL and opens it in your browser.
  3. You approve on Patreon. Browser redirects back to localhost:8080/callback.
  4. Server captures the ?code=XXX param and does the token exchange.
  5. Prints the fresh refresh_token + the gh secret set command.

Redirect URI to register on Patreon:
    http://localhost:8080/callback

Requirements:
    pip install requests
"""

import os
import sys
import json
import subprocess
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests

CLIENT_ID = os.environ.get('PATREON_CLIENT_ID')
CLIENT_SECRET = os.environ.get('PATREON_CLIENT_SECRET')
REDIRECT_URI = os.environ.get('PATREON_REDIRECT_URI', 'http://localhost:8080/callback')
SCOPES = "w:campaigns.webhook"

# Shared state so the request handler can hand results back to main().
_result = {'code': None, 'error': None}


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handles the single redirect Patreon sends after user approval."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if 'code' in params:
            _result['code'] = params['code'][0]
            body = (
                b"<html><body style='font-family:sans-serif;padding:2em'>"
                b"<h2>Success</h2>"
                b"<p>Code received. You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
            self.send_response(200)
        elif 'error' in params:
            _result['error'] = f"{params.get('error', ['unknown'])[0]}: {params.get('error_description', [''])[0]}"
            body = (
                b"<html><body style='font-family:sans-serif;padding:2em'>"
                b"<h2>OAuth error</h2>"
                b"<pre>" + _result['error'].encode('utf-8') + b"</pre>"
                b"</body></html>"
            )
            self.send_response(400)
        else:
            _result['error'] = f"unexpected callback path: {self.path}"
            body = b"<html><body>Nothing here.</body></html>"
            self.send_response(404)

        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # Silence the default access-log spam.
    def log_message(self, format, *args):
        return


def main():
    missing = []
    if not CLIENT_ID:
        missing.append('PATREON_CLIENT_ID')
    if not CLIENT_SECRET:
        missing.append('PATREON_CLIENT_SECRET')
    if missing:
        print(f"ERROR: env vars not set: {', '.join(missing)}")
        print("Set them (PowerShell):")
        print("  $env:PATREON_CLIENT_ID='<your-client-id>'")
        print("  $env:PATREON_CLIENT_SECRET='<your-new-client-secret>'")
        sys.exit(1)

    auth_url = (
        "https://www.patreon.com/oauth2/authorize?"
        + urllib.parse.urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
        })
    )

    print("=" * 70)
    print("PREREQUISITE — register this redirect URI on your Patreon app:")
    print()
    print(f"    {REDIRECT_URI}")
    print()
    print("At: https://www.patreon.com/portal/registration/register-clients")
    print("Add it in the 'Redirect URIs' field, save, then re-run this script.")
    print("=" * 70)
    print()
    print("Starting local HTTP server on 127.0.0.1:8080 ...")

    server = HTTPServer(('127.0.0.1', 8080), OAuthCallbackHandler)
    server.timeout = None  # per-request timeout; handle_request blocks until 1 request

    print(f"Opening authorization URL in your default browser:")
    print(f"    {auth_url}")
    print()
    print("If it doesn't open, copy that URL into a browser manually.")
    print("Waiting for redirect from Patreon...")
    print()

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass  # not fatal — user can open manually

    try:
        server.handle_request()  # blocks until Patreon redirects to localhost
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        sys.exit(1)
    finally:
        server.server_close()

    if _result['error']:
        print(f"ERROR from Patreon: {_result['error']}")
        sys.exit(1)

    code = _result['code']
    if not code:
        print("ERROR: server exited without a code — did Patreon reject the request?")
        sys.exit(1)

    print(f"Got code: {code[:12]}... (length {len(code)})")
    print("Exchanging code for tokens...")

    # Use curl.exe first — it uses Windows' native SChannel TLS which sidesteps
    # SSL-inspection middleboxes (antivirus, corporate proxies) that break
    # Python's OpenSSL-based requests. Fall back to requests if curl not found.
    tokens = _exchange_via_curl(code) or _exchange_via_requests(code)

    if not tokens:
        sys.exit(1)

    refresh_token = tokens.get('refresh_token')
    if not refresh_token:
        print("ERROR: response missing refresh_token")
        print(tokens)
        sys.exit(1)

    print()
    print("=" * 70)
    print("SUCCESS — copy the value below into the PATREON_REFRESH_TOKEN secret:")
    print()
    print(refresh_token)
    print()
    print("Or run this directly (one-shot):")
    print()
    print(f'    gh secret set PATREON_REFRESH_TOKEN --repo bryanseah234/patreonalive --body "{refresh_token}"')
    print("=" * 70)


def _exchange_via_curl(code):
    """Do the token exchange using curl.exe (Windows SChannel TLS). Returns dict or None."""
    curl_path = None
    for cand in ('curl.exe', 'curl'):
        try:
            r = subprocess.run([cand, '--version'], capture_output=True, timeout=5)
            if r.returncode == 0:
                curl_path = cand
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    if not curl_path:
        print("curl not available on PATH; falling back to Python requests...")
        return None

    print(f"Trying token exchange via {curl_path} (native TLS)...")
    result = subprocess.run(
        [
            curl_path, '-sS', '-X', 'POST',
            'https://www.patreon.com/api/oauth2/token',
            '-H', 'User-Agent: PatreonBootstrap/2.0',
            '-H', 'Accept: application/json',
            '--data-urlencode', 'grant_type=authorization_code',
            '--data-urlencode', f'code={code}',
            '--data-urlencode', f'client_id={CLIENT_ID}',
            '--data-urlencode', f'client_secret={CLIENT_SECRET}',
            '--data-urlencode', f'redirect_uri={REDIRECT_URI}',
            '-w', '\n---HTTP_STATUS:%{http_code}',
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"curl failed (exit {result.returncode}): {result.stderr.strip()}")
        return None

    # Parse the trailing status
    body, _, status_line = result.stdout.rpartition('---HTTP_STATUS:')
    status = status_line.strip() or '?'
    body = body.rstrip()
    if status != '200':
        print(f"curl exchange failed (HTTP {status}): {body}")
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        print(f"curl response was not JSON: {body[:200]}")
        return None


def _exchange_via_requests(code):
    """Python-requests fallback (used if curl unavailable)."""
    print("Trying token exchange via Python requests (OpenSSL)...")
    try:
        r = requests.post(
            "https://www.patreon.com/api/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
            },
            headers={"User-Agent": "PatreonBootstrap/2.0"},
            timeout=30,
        )
    except requests.exceptions.SSLError as e:
        print(f"SSL error from Python requests: {e}")
        print("This is likely a Windows SSL-inspection middlebox breaking OpenSSL.")
        print("Retry the whole script — the curl.exe fallback should catch this next time.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Network error: {e}")
        return None

    if r.status_code != 200:
        print(f"ERROR: token exchange failed ({r.status_code})")
        print(r.text)
        return None
    return r.json()


if __name__ == '__main__':
    main()
