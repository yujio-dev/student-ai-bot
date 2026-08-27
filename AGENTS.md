# Student AI Bot runtime

The live local bot is owned by the Windows Scheduled Task `StudentAIBot`.

- Never keep `python -m app.bot` running from a Codex-managed terminal.
- Never start a second bot instance for testing. Port `127.0.0.1:38473` is an intentional single-instance lock.
- A duplicate-start error means the managed background bot is already healthy.
- After verified code changes, apply them by running `scripts\restart_bot.ps1` with PowerShell.
- Read runtime output from `logs\bot.log`; do not print `.env` or Telegram/OpenAI secrets.
- Unit tests can import `app.bot` normally and do not need the live process to be stopped.

# Project workflow

- After completing a substantial change, run the relevant tests and checks, scan the staged files for secrets, create a clear Git commit, and push it to `origin/main`.
- Do not publish unfinished experiments, unrelated worktree changes, `.env`, database files, API keys, bot tokens, credentials, or other private data.
- If tests fail or the change is unsafe to publish, do not push it. Explain the blocker instead.
- Respect an explicit user request not to commit or push a particular change.
- Report the pushed commit link and the checks that passed.
