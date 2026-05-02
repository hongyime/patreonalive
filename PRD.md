# PRD: patreonalive

## Overview
A Python script that keeps a Patreon creator campaign active by periodically making API calls (create + delete a dummy webhook). Designed to run on a schedule (e.g., GitHub Actions cron) to prevent Patreon from deactivating dormant campaigns due to inactivity. Targets creators who post infrequently but want their page to stay live.

## Goals
- Authenticate with Patreon OAuth2 using a refresh token
- Exchange refresh token for a new access token (and rotate the refresh token)
- Create a dummy webhook on the campaign, then immediately delete it
- Keep the refresh token persisted in `token.txt` for next run

## Non-Goals
- Posting content to Patreon
- Reading patron data or membership info
- Email notifications on failure
- Web dashboard or UI

## User Stories
- As a Patreon creator who posts rarely, I want an automated keep-alive so my page stays published.
- As a developer, I want a lightweight script I can run via GitHub Actions cron to avoid manual intervention.

## Tech Stack
- **Language**: Python 3.x
- **Libraries**: `requests` (pip)
- **Auth**: Patreon OAuth2 (refresh_token grant)
- **Environment vars**: `PATREON_CLIENT_ID`, `PATREON_CLIENT_SECRET`
- **Runtime**: any Python 3 environment; designed for GitHub Actions

## Architecture
```
patreonalive/
├── keep_alive.py    # main script
├── token.txt        # persisted refresh token (gitignored)
└── requirements.txt
```

**Flow:**
1. Read refresh token from `token.txt`
2. POST to Patreon token endpoint → get new access token + new refresh token
3. Write new refresh token back to `token.txt`
4. POST to Patreon webhooks API → create dummy `posts:publish` webhook
5. DELETE the webhook immediately
6. Exit with code 0 (even on soft errors, so GitHub Actions commits the token)

## Features (detailed)

### Token Refresh
- Endpoint: `POST https://www.patreon.com/api/oauth2/token`
- Grant type: `refresh_token`
- Reads current refresh token from `token.txt`
- Writes new refresh token back to `token.txt` on success
- Raises exception on HTTP error

### Webhook Activity Trigger
- Creates webhook with trigger `posts:publish` and dummy URI
- Endpoint: `POST https://www.patreon.com/api/oauth2/v2/webhooks`
- Immediately deletes created webhook via `DELETE .../webhooks/{id}`
- 2-second sleep between create and delete

### Error Handling
- Script exits with code 0 even on failure (to allow GitHub Actions to commit the rotated token)

## Data / Config
| Item | Description |
|------|-------------|
| `token.txt` | Single-line refresh token; updated each run |
| `PATREON_CLIENT_ID` | Environment variable — Patreon app client ID |
| `PATREON_CLIENT_SECRET` | Environment variable — Patreon app client secret |
| `CAMPAIGN_ID` | Hardcoded in script — your Patreon campaign ID |

## Deployment / Run
```bash
pip install requests
export PATREON_CLIENT_ID=xxx
export PATREON_CLIENT_SECRET=xxx
# Place initial refresh token in token.txt
python keep_alive.py
```

**GitHub Actions cron example:**
```yaml
on:
  schedule:
    - cron: '0 0 * * 0'  # weekly
```

## Constraints & Notes
- **Token security**: `token.txt` contains a live OAuth refresh token — never commit it publicly
- **Patreon API**: uses native V2 API endpoints, not legacy V1 hacks
- **Dummy webhook URI**: points to a dead URL — Patreon may eventually reject invalid URIs
- **Rate limits**: one run per week is well within Patreon API limits
- **Campaign ID**: must be updated if script is reused for a different creator account
