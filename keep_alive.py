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
        "User-Agent": "PatreonKeepAliveBot/5.0"
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
    response = requests.post(url, data=data, headers={"User-Agent": "PatreonBot/5.0"})
    
    if response.status_code != 200:
        print(f"Auth Failed: {response.text}")
        response.raise_for_status()
        
    tokens = response.json()
    
    print("Saving new refresh token...")
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
        print(f"Script Error: {e}")
        # Exit with Success code so GitHub commits the token
        exit(0) 

if __name__ == "__main__":
    main()
