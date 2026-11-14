2026-09-16: Baseline review batch-a. Created STATE.md and JOURNAL.md (were missing; only handoffs/ existed). No open issues. Dependabot PR #20 pending. Recent hardening PRs #21/#22 already merged. token.txt confirmed gitignored + not tracked. No fixes required.

- 2026-09-27: Remove the optional personal security contact and preserve private reporting guidance through a reviewed maintenance pull request.
- 2026-11-12: OAuth hardening will use stdlib `urllib` with a single 20-second timeout; bootstrap only falls back to urllib when neither curl executable can be launched, so a consumed authorization code is never retried after a curl attempt.
- 2026-11-12: Curl runs with `-q` as its first option so a user `.curlrc` cannot add retries to the one-use authorization-code exchange; an independent diff review prompted this safeguard.
