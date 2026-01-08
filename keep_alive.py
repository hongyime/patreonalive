import requests
import os
import time
import json

# --- CONFIGURATION ---
# We need your Campaign ID to know WHERE to create the post
CAMPAIGN_ID = "12502474" 
TOKEN_FILE = "token.txt"

CLIENT_ID = os.environ['PATREON_CLIENT_ID']
CLIENT_SECRET = os.environ['PATREON_CLIENT_SECRET']

def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json", # V1 prefers simple JSON
        "User-Agent": "PatreonKeepAliveBot/3.0"
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
    
    response = requests.post(url, data=data, headers={"User-Agent": "PatreonBot/3.0"})
    response.raise_for_status()
    tokens = response.json()
    
    with open(TOKEN_FILE, "w") as f:
        f.write(tokens['refresh_token'])
        
    return tokens['access_token']

def create_dummy_post(token):
    # We use the V1 Endpoint for creation (V2 does not support POST)
    url = "https://www.patreon.com/api/oauth2/api/posts"
    
    payload = {
        "data": {
            "type": "post",
            "attributes": {
                "title": "Keep Alive Signal",
                "content": "<p>Automated activity check.</p>",
                "post_type": "text_only",
                "is_paid": False,        # Do not charge patrons
                "is_public": False,      # Keep it private
                "post_status": "draft"   # IMPORTANT: Create as Draft so no emails are sent
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
    
    r = requests.post(url, json=payload, headers=get_headers(token))
    r.raise_for_status()
    # Return the ID of the new post so we can delete it
    return r.json()['data']['id']

def delete_post(token, post_id):
    url = f"https://www.patreon.com/api/oauth2/api/posts/{post_id}"
    r = requests.delete(url, headers=get_headers(token))
    r.raise_for_status()

def main():
    try:
        print("Refreshing tokens...")
        access_token = get_tokens()
        
        print("Action 1: Creating a dummy Draft Post...")
        new_post_id = create_dummy_post(access_token)
        print(f"Draft created with ID: {new_post_id}")
        
        # Wait a moment to ensure system registers the creation
        time.sleep(5)
        
        print(f"Action 2: Deleting post {new_post_id}...")
        delete_post(access_token, new_post_id)
        
        print("Success! Draft created and deleted. Activity registered.")
        
    except Exception as e:
        print(f"Error: {e}")
        # If it fails, check the logs. If 'create' worked but 'delete' failed,
        # you might have a draft left over in your dashboard.
        exit(1)

if __name__ == "__main__":
    main()
