# patreonalive

Python utility that refreshes a Patreon token and creates then deletes a dummy
campaign webhook. This activity is not a guarantee that Patreon keeps a page published.

## Bootstrap authorization

Use Python 3.11 or newer. From the repository directory:

```powershell
python -m pip install -r requirements.txt
$env:PATREON_CLIENT_ID = '<your-client-id>'
$env:PATREON_CLIENT_SECRET = '<your-client-secret>'
python get_token.py
```

Register `http://localhost:8080/callback` in your Patreon client's Redirect URIs
before running the script. It opens an authorization page and prints the same
URL for manual opening. After approval it exchanges the validated code and
prints the refresh token and a command for setting `PATREON_REFRESH_TOKEN`.
The bootstrap does not write `token.txt`, change GitHub secrets or modify the
daily job automatically. Treat the printed token as a secret.

Each attempt has a fresh OAuth state. Wrong states, unrelated paths and malformed
callbacks are rejected while the listener keeps waiting. A matching provider
denial ends the attempt. Provider text is escaped in the browser response, and
callback URLs and authorization codes are not logged.

The default wait is 300 seconds, including incomplete callback requests. Set
`PATREON_AUTH_TIMEOUT` to a positive number up to 900 seconds if needed. Timeout
or cancellation closes the listener; run the script again for a fresh URL.
Ctrl+C exits with status 130; configuration, callback and exchange failures
exit with status 1.

For a custom registered callback, set `PATREON_REDIRECT_URI` to an HTTP URL on
`localhost` or `127.0.0.1`, such as `http://localhost:8123/custom`. The listener
uses that port and path on IPv4 loopback. Remote hosts, HTTPS, embedded credentials,
query strings and fragments are rejected. The value must exactly match the
redirect URI registered with Patreon.

## Scheduled activity and token storage

`.github/workflows/daily.yml` runs at 00:00 UTC daily (08:00 SGT) and supports
manual dispatch. It runs `keep_alive.py` with the client ID and client secret
from GitHub Actions secrets. The latest refresh token is restored into ignored
`token.txt` from the Actions cache; `PATREON_REFRESH_TOKEN` is the fallback on
a cache miss. A rotated token is saved to the cache even if a later activity
step fails. The job reports failures with a nonzero exit status.

This persistence currently uses GitHub Actions cache, outside Supabase. Moving
it requires preserving the latest rotated token and coordinating the writer;
the OAuth callback repair does not migrate or retire it. Do not purge the cache
or assume the original bootstrap secret is still the latest token.

## Validation

```powershell
python -B -m unittest discover -s tests -v
```

Tests use synthetic authorization values, mocked token exchanges and real local
HTTP connections. They do not open a real browser, contact Patreon, load saved
tokens, rotate credentials or dispatch the scheduled workflow. Hosted validation
covers Linux with Python 3.11 and Windows with Python 3.12.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
