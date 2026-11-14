# STATE

## OAuth hardening and stdlib migration - 2026-11-14

- Complete: removed `requests`/`requirements.txt`; migrated OAuth bootstrap and keep-alive transport to stdlib; added `PATREON_CAMPAIGN_ID` and `.env.example`.
- CI consolidated in `Build Check`: Ubuntu 3.11 (`Build`) and Windows 3.12 run the test suite. Old `oauth-tests.yml` deleted.
- Verified: `python3 -S -B -m unittest discover -s tests -v` (39 passed), all workflow YAML files parse, and `git diff --check` passes. Landed on `main`.
