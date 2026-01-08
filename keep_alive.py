import requests
import os
import time

# Hardcoded Post ID from your URL
POST_ID = "127069411"

# Environment Variables (Keep these in GitHub Secrets for security)
CLIENT_ID = os.environ['PATREON_CLIENT_ID']
CLIENT_SECRET = os.environ['PATREON_CLIENT_SECRET']
REFRESH_TOKEN = os.environ['PATREON_REFRESH_TOKEN']

def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/vnd.api+json",
    }

def refresh_access_token():
    url = "https://www.patreon.com/api/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    tokens = response.json()
    # Note: If Patreon rotates refresh tokens, you may need to update your secret manually
    return tokens['access_token']

def get_current_content(token):
    url = f"https://www.patreon.com/api/oauth2/v2/posts/{POST_ID}?fields%5Bpost%5D=content"
    response = requests.get(url, headers=get_headers(token))
    response.raise_for_status()
    return response.json()['data']['attributes']['content']

def update_post(token, new_content):
    url = f"https://www.patreon.com/api/oauth2/v2/posts/{POST_ID}"
    payload = {
        "data": {
            "type": "post",
            "id": POST_ID,
            "attributes": {
                "content": new_content
            }
        }
    }
    response = requests.patch(url, json=payload, headers=get_headers(token))
    if response.status_code == 200:
        print("Update successful.")
    else:
        print(f"Error {response.status_code}: {response.text}")
    response.raise_for_status()

def main():
    try:
        print("Refreshing token...")
        token = refresh_access_token()

        print("Fetching current post content...")
        original_content = get_current_content(token)

        # Step 1: Add a full stop
        print("Step 1: Adding a full stop to trigger activity...")
        temp_content = original_content + "."
        update_post(token, temp_content)

        # Brief pause to ensure the system registers the change
        time.sleep(5)

        # Step 2: Remove the full stop
        print("Step 2: Reverting to original content...")
        update_post(token, original_content)

        print("Keep-alive cycle complete.")
        
    except Exception as e:
        print(f"Automation failed: {e}")
        exit(1)

if __name__ == "__main__":
    main()
