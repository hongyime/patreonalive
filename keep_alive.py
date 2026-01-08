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
        "User-Agent": "PatreonKeepAliveBot/4.0"
    }

def get_tokens():
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
    response = requests.post(url, data=data, headers={"User-Agent": "PatreonBot/4.0"})
    
    if response.status_code != 200:
        print(f"Auth Failed: {response.text}")
        response.raise_for_status()
        
    tokens = response.json()
    
    print("Saving new refresh token...")
    with open(TOKEN_FILE, "w") as f:
        f.write(tokens['refresh_token'])
        
    return tokens['access_token']

def create_and_delete_draft(token):
    # CORRECTED URL: Standard V1 endpoint
    url = "https://www.patreon.com/api/posts"
    
    payload = {
        "data": {
            "type": "post",
            "attributes": {
                "title": "Keep Alive Signal",
                "content": "<p>Automated activity check.</p>",
                "post_type": "text_only",
                "post_status": "draft", # Silent draft
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
    
    print("Creating draft via Standard V1 URL...")
    r = requests.post(url, json=payload, headers=get_headers(token))
    
    # If this still fails, we print the full error to debug
    if r.status_code != 201:
        print(f"Creation Failed: {r.status_code} - {r.text}")
        r.raise_for_status()
        
    post_id = r.json()['data']['id']
    print(f"Draft created: {post_id}")
    
    time.sleep(3)
    
    # Delete it
    delete_url = f"https://www.patreon.com/api/posts/{post_id}"
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
        # Exit success (0) so GitHub still saves the token!
        exit(0) 

if __name__ == "__main__":
    main()
