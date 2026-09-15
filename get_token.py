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
from oauth_callback import OAuthAuthorizationError, capture_authorization_code

import requests

CLIENT_ID = os.environ.get('PATREON_CLIENT_ID')
CLIENT_SECRET = os.environ.get('PATREON_CLIENT_SECRET')
REDIRECT_URI = os.environ.get('PATREON_REDIRECT_URI', 'http://localhost:8080/callback')
SCOPES = "w:campaigns.webhook"

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

    try:
        timeout = float(os.environ.get('PATREON_AUTH_TIMEOUT', '300'))
        code = capture_authorization_code(CLIENT_ID, REDIRECT_URI, SCOPES, timeout=timeout)
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        sys.exit(130)
    except (OAuthAuthorizationError, ValueError, OSError) as error:
        print(f"ERROR: {error}")
        sys.exit(1)

    print("Authorization code received.")
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
    print(f'    gh secret set PATREON_REFRESH_TOKEN --repo hongyime/patreonalive --body "{refresh_token}"')
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
