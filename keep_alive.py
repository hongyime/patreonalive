import requests
import os
import re
import time

# --- CONFIGURATION ---
CAMPAIGN_ID = "12502474"
# Token persistence path. Populated by the workflow's actions/cache/restore step
# between runs. If cache is empty (first run, >7 day gap, or manual purge),
# read_refresh_token() falls back to the PATREON_REFRESH_TOKEN env secret.
# NOT tracked in git — see .gitignore.
TOKEN_FILE = "token.txt"

CLIENT_ID = os.environ['PATREON_CLIENT_ID']
CLIENT_SECRET = os.environ['PATREON_CLIENT_SECRET']
REQUEST_TIMEOUT = (5, 20)


class KeepAliveError(RuntimeError):
    """An operational error whose message is safe for the workflow log."""


def request(operation: str, method: str, url: str, expected: tuple[int, ...], **kwargs) -> requests.Response:
    """Perform one request; POSTs with uncertain outcomes are never retried."""
    send = requests.post if method == "POST" else requests.delete
    try:
        result = send(url, timeout=REQUEST_TIMEOUT, allow_redirects=False, **kwargs)
    except requests.RequestException:
        raise KeepAliveError(f"{operation}: network request failed; no automatic retry.") from None
    if result.status_code not in expected:
        status = result.status_code
        result.close()
        raise KeepAliveError(f"{operation}: unexpected HTTP status {status}.")
    return result


def response_object(result: requests.Response, operation: str) -> dict:
    try:
        value = result.json()
    except ValueError:
        raise KeepAliveError(f"{operation}: invalid JSON response.") from None
    finally:
        result.close()
    if not isinstance(value, dict):
        raise KeepAliveError(f"{operation}: invalid response object.")
    return value


def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "PatreonKeepAliveBot/5.0"
    }


def read_refresh_token():
    """Load refresh token: cache-restored file first, then env secret."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token = f.read().strip()
            if token:
                return token
    bootstrap = os.environ.get("PATREON_REFRESH_TOKEN", "").strip()
    if not bootstrap:
        print("Error: no cached token.txt and PATREON_REFRESH_TOKEN secret is empty.")
        exit(1)
    print("Bootstrapped refresh_token from PATREON_REFRESH_TOKEN secret (cache empty).")
    return bootstrap


def get_tokens():
    refresh_token = read_refresh_token()

    url = "https://www.patreon.com/api/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }

    print("Exchanging tokens...")
    response = request("Token refresh", "POST", url, (200,), data=data,
                       headers={"User-Agent": "PatreonBot/5.0"})
    tokens = response_object(response, "Token refresh")
    rotated_token = tokens.get('refresh_token')
    if not isinstance(rotated_token, str) or not rotated_token.strip():
        raise KeepAliveError("Token refresh: missing valid refresh token; saved token unchanged.")

    # Persist to disk so actions/cache/save picks it up post-run.
    # NEVER committed to git — .gitignore excludes token.txt.
    print("Saving rotated refresh token to token.txt (cache-persisted, not tracked)...")
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(rotated_token.strip())

    access_token = tokens.get('access_token')
    if not isinstance(access_token, str) or not access_token.strip():
        raise KeepAliveError("Token refresh: invalid access token; rotated refresh token retained.")
    return access_token


def trigger_webhook_activity(token):
    # This is a NATIVE V2 Endpoint. No legacy hacks.
    url = "https://www.patreon.com/api/oauth2/v2/webhooks"

    # payload to create a dummy webhook
    payload = {
        "data": {
            "type": "webhook",
            "attributes": {
                "triggers": ["posts:publish"],
                "uri": "https://hong-yi.me/keep-alive-dummy"
            },
            "relationships": {
                "campaign": {
                    "data": {
                        "type": "campaign",
                        "id": CAMPAIGN_ID
                    }
                }
            }
        }
    }

    print("Creating dummy webhook...")
    r = request("Webhook creation", "POST", url, (201,), json=payload, headers=get_headers(token))
    created = response_object(r, "Webhook creation").get('data')
    webhook_id = created.get('id') if isinstance(created, dict) else None
    if not isinstance(webhook_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', webhook_id):
        raise KeepAliveError("Webhook creation: invalid webhook identity; cleanup needs review.")
    print(f"Webhook created: {webhook_id}")

    time.sleep(2)

    # Delete it immediately
    delete_url = f"https://www.patreon.com/api/oauth2/v2/webhooks/{webhook_id}"
    print(f"Deleting webhook {webhook_id}...")
    deleted = request("Webhook deletion", "DELETE", delete_url, (200, 204), headers=get_headers(token))
    deleted.close()
    print("Done. Activity Registered.")


def main():
    try:
        access_token = get_tokens()
        trigger_webhook_activity(access_token)
        print("Cycle Complete.")
    except KeepAliveError as e:
        print(f"::error::{e}")
        raise SystemExit(1) from None
    except Exception:
        # Surface real failure so the workflow reports it.
        # Rotated token (if any) is already saved to token.txt by get_tokens();
        # the workflow's cache-save step runs even on failure via `if: always()`.
        print("::error::Cycle failed. Check configuration and token storage; private error details omitted.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
