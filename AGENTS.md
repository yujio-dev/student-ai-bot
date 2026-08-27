# Project workflow

- After completing a substantial change, run the relevant tests and checks, scan the staged files for secrets, create a clear Git commit, and push it to `origin/main`.
- Do not publish unfinished experiments, unrelated worktree changes, `.env`, database files, API keys, bot tokens, credentials, or other private data.
- If tests fail or the change is unsafe to publish, do not push it. Explain the blocker instead.
- Respect an explicit user request not to commit or push a particular change.
- Report the pushed commit link and the checks that passed.
