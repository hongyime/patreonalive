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
        "Content-Type": "application/json",
        "User-Agent": "PatreonKeepAliveBot/3.1"
    }

def get_tokens():
    # Load current token
    if not os.path.exists(TOKEN_FILE):
        print("Error: token.txt not found!")
        exit(1)
        
    with open(TOKEN_FILE, "r") as f:
        refresh_token = f.read().strip()
    
    url = "https://www.patreon.com/api/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }
    
    print("Exchanging tokens...")
    response = requests.post(url, data=data, headers={"User-Agent": "PatreonBot/3.1"})
    
    if response.status_code != 200:
        print(f"Auth Failed: {response.text}")
        response.raise_for_status()
        
    tokens = response.json()
    
    # SAVE IMMEDIATELY
    print("Saving new refresh token...")
    with open(TOKEN_FILE, "w") as f:
        f.write(tokens['refresh_token'])
        
    return tokens['access_token']

def create_and_delete_draft(token):
    # Use the CAMPAIGN-SPECIFIC endpoint to avoid 405 errors
    url = f"https://www.patreon.com/api/oauth2/api/campaigns/{CAMPAIGN_ID}/posts"
    
    payload = {
        "data": {
            "type": "post",
            "attributes": {
                "title": "Keep Alive",
                "content": "<p>Automated check.</p>",
                "post_type": "text_only",
                "post_status": "draft",
                "is_paid": False,
                "is_public": False
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
    
    print("Creating draft...")
    r = requests.post(url, json=payload, headers=get_headers(token))
    
    if r.status_code != 201:
        print(f"Creation Failed: {r.status_code} - {r.text}")
        r.raise_for_status()
        
    post_id = r.json()['data']['id']
    print(f"Draft created: {post_id}")
    
    time.sleep(3)
    
    # Delete it
    delete_url = f"https://www.patreon.com/api/oauth2/api/posts/{post_id}"
    print(f"Deleting {post_id}...")
    requests.delete(delete_url, headers=get_headers(token))
    print("Done.")

def main():
    try:
        access_token = get_tokens()
        create_and_delete_draft(access_token)
        print("Cycle Complete.")
    except Exception as e:
        print(f"Script Error: {e}")
        # We exit with 0 (Success) so that GitHub Actions will still run the "Commit" step
        # This prevents the 'Dead Token' trap.
        exit(0) 

if __name__ == "__main__":
    main()
