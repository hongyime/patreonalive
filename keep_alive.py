import requests
import os
import time

POST_ID = "127069411"
TOKEN_FILE = "token.txt"

# Client credentials remain in GitHub Secrets for security
CLIENT_ID = os.environ['PATREON_CLIENT_ID']
CLIENT_SECRET = os.environ['PATREON_CLIENT_SECRET']

def get_tokens():
    with open(TOKEN_FILE, "r") as f:
        refresh_token = f.read().strip()
    
    url = "https://www.patreon.com/api/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    tokens = response.json()
    
    # Save the NEW refresh token for tomorrow
    with open(TOKEN_FILE, "w") as f:
        f.write(tokens['refresh_token'])
        
    return tokens['access_token']

def update_patreon(token, content):
    url = f"https://www.patreon.com/api/oauth2/v2/posts/{POST_ID}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/vnd.api+json",
    }
    payload = {
        "data": {
            "type": "post",
            "id": POST_ID,
            "attributes": {"content": content}
        }
    }
    r = requests.patch(url, json=payload, headers=headers)
    r.raise_for_status()

def get_content(token):
    url = f"https://www.patreon.com/api/oauth2/v2/posts/{POST_ID}?fields%5Bpost%5D=content"
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()['data']['attributes']['content']

def main():
    print("Refreshing tokens...")
    access_token = get_tokens()
    
    print("Fetching content...")
    original = get_content(access_token)
    
    print("Step 1: Adding fullstop...")
    update_patreon(access_token, original + ".")
    
    time.sleep(5)
    
    print("Step 2: Removing fullstop...")
    update_patreon(access_token, original)
    
    print("Patreon updated and new token saved locally.")

if __name__ == "__main__":
    main()
