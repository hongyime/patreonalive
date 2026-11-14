import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

# --- CONFIGURATION ---
CAMPAIGN_ID = os.environ.get("PATREON_CAMPAIGN_ID", "12502474").strip() or "12502474"
USER_AGENT = "PatreonKeepAlive/5.0"
REQUEST_TIMEOUT = 20
# Token persistence path. Populated by the workflow's actions/cache/restore step
# between runs. If cache is empty (first run, >7 day gap, or manual purge),
# read_refresh_token() falls back to the PATREON_REFRESH_TOKEN env secret.
# NOT tracked in git — see .gitignore.
TOKEN_FILE = "token.txt"


class KeepAliveError(RuntimeError):
    """An operational error whose message is safe for the workflow log."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, status, message, headers, new_url):
        return None


OPENER = build_opener(NoRedirect)


def request(operation: str, method: str, url: str, expected: tuple[int, ...], *, data: dict | None = None,
            json_body: dict | None = None, headers: dict[str, str] | None = None):
    """Perform one request; POSTs with uncertain outcomes are never retried."""
    body = None
    request_headers = dict(headers or {})
    if data is not None:
        body = urlencode(data).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    try:
        result = OPENER.open(Request(url, data=body, headers=request_headers, method=method), timeout=REQUEST_TIMEOUT)
    except HTTPError as error:
        result = error
    except (OSError, TimeoutError, URLError):
        raise KeepAliveError(f"{operation}: network request failed; no automatic retry.") from None

    if result.getcode() not in expected:
        status = result.getcode()
        result.close()
        raise KeepAliveError(f"{operation}: unexpected HTTP status {status}.")
    return result


def response_object(result, operation: str) -> dict:
    try:
        value = json.loads(result.read().decode("utf-8"))
    except (AttributeError, OSError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise KeepAliveError(f"{operation}: invalid JSON response.") from None
    finally:
        result.close()
    if not isinstance(value, dict):
        raise KeepAliveError(f"{operation}: invalid response object.")
    return value


def get_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }


def credentials() -> tuple[str, str]:
    client_id = os.environ.get("PATREON_CLIENT_ID", "").strip()
    client_secret = os.environ.get("PATREON_CLIENT_SECRET", "").strip()
    missing = [name for name, value in (("PATREON_CLIENT_ID", client_id), ("PATREON_CLIENT_SECRET", client_secret)) if not value]
    if missing:
        raise KeepAliveError(f"Token refresh: missing required configuration: {', '.join(missing)}.")
    return client_id, client_secret


def read_refresh_token() -> str:
    """Load refresh token: cache-restored file first, then env secret."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as token_file:
            token = token_file.read().strip()
            if token:
                return token
    bootstrap = os.environ.get("PATREON_REFRESH_TOKEN", "").strip()
    if not bootstrap:
        raise KeepAliveError("Token refresh: no cached token.txt and PATREON_REFRESH_TOKEN is empty.")
    print("Bootstrapped refresh_token from PATREON_REFRESH_TOKEN secret (cache empty).")
    return bootstrap


def get_tokens() -> str:
    client_id, client_secret = credentials()
    refresh_token = read_refresh_token()

    print("Exchanging tokens...")
    response = request(
        "Token refresh",
        "POST",
        "https://www.patreon.com/api/oauth2/token",
        (200,),
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"User-Agent": USER_AGENT},
    )
    tokens = response_object(response, "Token refresh")
    rotated_token = tokens.get("refresh_token")
    if not isinstance(rotated_token, str) or not rotated_token.strip():
        raise KeepAliveError("Token refresh: missing valid refresh token; saved token unchanged.")

    # Persist to disk so actions/cache/save picks it up post-run.
    # NEVER committed to git — .gitignore excludes token.txt.
    print("Saving rotated refresh token to token.txt (cache-persisted, not tracked)...")
    with open(TOKEN_FILE, "w", encoding="utf-8") as token_file:
        token_file.write(rotated_token.strip())

    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token.strip():
        raise KeepAliveError("Token refresh: invalid access token; rotated refresh token retained.")
    return access_token


def trigger_webhook_activity(token: str) -> None:
    # This is a NATIVE V2 Endpoint. No legacy hacks.
    url = "https://www.patreon.com/api/oauth2/v2/webhooks"
    payload = {
        "data": {
            "type": "webhook",
            "attributes": {
                "triggers": ["posts:publish"],
                "uri": "https://hong-yi.me/keep-alive-dummy",
            },
            "relationships": {
                "campaign": {
                    "data": {
                        "type": "campaign",
                        "id": CAMPAIGN_ID,
                    },
                },
            },
        },
    }

    print("Creating dummy webhook...")
    created_response = request("Webhook creation", "POST", url, (201,), json_body=payload, headers=get_headers(token))
    created = response_object(created_response, "Webhook creation").get("data")
    webhook_id = created.get("id") if isinstance(created, dict) else None
    if not isinstance(webhook_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", webhook_id):
        raise KeepAliveError("Webhook creation: invalid webhook identity; cleanup needs review.")
    print(f"Webhook created: {webhook_id}")

    time.sleep(2)

    delete_url = f"https://www.patreon.com/api/oauth2/v2/webhooks/{webhook_id}"
    print(f"Deleting webhook {webhook_id}...")
    deleted = request("Webhook deletion", "DELETE", delete_url, (200, 204), headers=get_headers(token))
    deleted.close()
    print("Done. Activity Registered.")


def main() -> None:
    try:
        access_token = get_tokens()
        trigger_webhook_activity(access_token)
        print("Cycle Complete.")
    except KeepAliveError as error:
        print(f"::error::{error}")
        raise SystemExit(1) from None
    except Exception:
        # Surface real failure so the workflow reports it.
        # Rotated token (if any) is already saved to token.txt by get_tokens();
        # the workflow's cache-save step runs even on failure via `if: always()`.
        print("::error::Cycle failed. Check configuration and token storage; private error details omitted.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
