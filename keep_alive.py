import requests
import os
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
    response = requests.post(url, data=data, headers={"User-Agent": "PatreonBot/5.0"})

    if response.status_code != 200:
        print(f"Auth Failed: {response.text}")
        response.raise_for_status()

    tokens = response.json()

    # Persist to disk so actions/cache/save picks it up post-run.
    # NEVER committed to git — .gitignore excludes token.txt.
    print("Saving rotated refresh token to token.txt (cache-persisted, not tracked)...")
    with open(TOKEN_FILE, "w") as f:
        f.write(tokens['refresh_token'])

    return tokens['access_token']


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
    r = requests.post(url, json=payload, headers=get_headers(token))

    if r.status_code != 201:
        print(f"Webhook Creation Failed: {r.status_code} - {r.text}")
        r.raise_for_status()

    webhook_id = r.json()['data']['id']
    print(f"Webhook created: {webhook_id}")

    time.sleep(2)

    # Delete it immediately
    delete_url = f"https://www.patreon.com/api/oauth2/v2/webhooks/{webhook_id}"
    print(f"Deleting webhook {webhook_id}...")
    requests.delete(delete_url, headers=get_headers(token))
    print("Done. Activity Registered.")


def main():
    try:
        access_token = get_tokens()
        trigger_webhook_activity(access_token)
        print("Cycle Complete.")
    except Exception as e:
        # Surface real failure so the workflow reports it.
        # Rotated token (if any) is already saved to token.txt by get_tokens();
        # the workflow's cache-save step runs even on failure via `if: always()`.
        print(f"::error::Script Error: {e}")
        exit(1)


if __name__ == "__main__":
    main()
