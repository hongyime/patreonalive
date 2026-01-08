import requests
import os
import time

# --- CONFIGURATION ---
CAMPAIGN_ID = "12502474" 
TOKEN_FILE = "token.txt"

CLIENT_ID = os.environ['PATREON_CLIENT_ID']
CLIENT_SECRET = os.environ['PATREON_CLIENT_SECRET']

def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/vnd.api+json",
        "User-Agent": "PatreonKeepAliveBot/1.2 (Mozilla/5.0)",
        "Accept": "application/vnd.api+json"
    }

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
    
    response = requests.post(url, data=data, headers={"User-Agent": "PatreonBot/1.2"})
    response.raise_for_status()
    tokens = response.json()
    
    with open(TOKEN_FILE, "w") as f:
        f.write(tokens['refresh_token'])
        
    return tokens['access_token']

def update_campaign(token, content):
    url = f"https://www.patreon.com/api/oauth2/v2/campaigns/{CAMPAIGN_ID}"
    payload = {
        "data": {
            "type": "campaign",
            "id": CAMPAIGN_ID,
            "attributes": {
                "about": content
            }
        }
    }
    r = requests.patch(url, json=payload, headers=get_headers(token))
    r.raise_for_status()

def get_campaign_about(token):
    url = f"https://www.patreon.com/api/oauth2/v2/campaigns/{CAMPAIGN_ID}?fields%5Bcampaign%5D=about"
    r = requests.get(url, headers=get_headers(token))
    r.raise_for_status()
    return r.json()['data']['attributes']['about']

def main():
    try:
        print("Rotating refresh tokens...")
        access_token = get_tokens()
        
        print("Fetching current 'About' content...")
        original_about = get_campaign_about(access_token)
        
        # Step 1: Add fullstop
        print("Action 1: Adding fullstop to trigger activity...")
        update_campaign(access_token, original_about + ".")
        
        time.sleep(5)
        
        # Step 2: Remove fullstop
        print("Action 2: Reverting to original content...")
        update_campaign(access_token, original_about)
        
        print("Success! Activity cycle completed.")
    except Exception as e:
        print(f"Failed: {e}")
        exit(1)

if __name__ == "__main__":
    main()
