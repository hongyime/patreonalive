import requests
import os
import time

# Hardcoded Post ID from your URL
POST_ID = "127069411"
TOKEN_FILE = "token.txt"

# Environment Variables from GitHub Secrets
CLIENT_ID = os.environ['PATREON_CLIENT_ID']
CLIENT_SECRET = os.environ['PATREON_CLIENT_SECRET']

def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/vnd.api+json",
        "User-Agent": "PatreonKeepAliveBot/1.0 (Contact: your_email@example.com)"
    }

def get_tokens():
    """Reads refresh_token from file, gets a new pair, and updates the file."""
    with open(TOKEN_FILE, "r") as f:
        refresh_token = f.read().strip()
    
    url = "https://www.patreon.com/api/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    
    response = requests.post(url, data=data, headers={"User-Agent": "PatreonKeepAliveBot/1.0"})
    response.raise_for_status()
    tokens = response.json()
    
    # Update token.txt with the brand new refresh token for the next run
    with open(TOKEN_FILE, "w") as f:
        f.write(tokens['refresh_token'])
        
    return tokens['access_token']

def get_current_content(token):
    url = f"https://www.patreon.com/api/oauth2/v2/posts/{POST_ID}?fields%5Bpost%5D=content"
    response = requests.get(url, headers=get_headers(token))
    response.raise_for_status()
    return response.json()['data']['attributes']['content']

def update_post(token, content):
    url = f"https://www.patreon.com/api/oauth2/v2/posts/{POST_ID}"
    payload = {
        "data": {
            "type": "post",
            "id": POST_ID,
            "attributes": {"content": content}
        }
    }
    response = requests.patch(url, json=payload, headers=get_headers(token))
    response.raise_for_status()

def main():
    try:
        print("Refreshing tokens and rotating secrets...")
        access_token = get_tokens()
        
        print(f"Fetching content for post {POST_ID}...")
        original_content = get_current_content(access_token)
        
        print("Action 1: Triggering activity (adding dot)...")
        # Appends a dot to the end of the HTML string
        update_post(access_token, original_content + ".")
        
        time.sleep(5) 
        
        print("Action 2: Reverting change...")
        update_post(access_token, original_content)
        
        print("Success! Patreon page marked as active.")
    except Exception as e:
        print(f"Failed: {e}")
        exit(1)

if __name__ == "__main__":
    main()
