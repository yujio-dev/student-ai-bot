# Bot cutover runbook

The cloud worker must stay at zero until the real production Telegram OIDC login,
owner identity `8247777174`, admin access, logout/relogin, and replay/state checks are
green. Never paste credentials into a command or log.

## Before cutover

1. Confirm the Core health endpoint and HTTPS certificate are healthy.
2. Confirm Doppler/Heroku configuration is in sync and `DATABASE_URL` remains
   Heroku-managed.
3. Create and verify a legacy backup:

   ```powershell
   .\.venv\Scripts\python.exe .\scripts\backup_legacy.py
   .\.venv\Scripts\python.exe .\scripts\backup_legacy.py --verify backups\<timestamp>
   ```

4. Capture a Heroku Postgres backup and verify its status. Record the backup ID;
   do not download it into the repository.
5. Inspect the current local bot without changing it:

   ```powershell
   .\scripts\cutover_local_bot.ps1 -Action Status
   ```

   Exactly one local lock listener proves the legacy polling instance is active.
   The script also reports the scheduled task that can restart it.

## Cut over

1. Stop the legacy bot and disable its scheduled-task autorestart:

   ```powershell
   .\scripts\cutover_local_bot.ps1 -Action Stop
   .\scripts\cutover_local_bot.ps1 -Action Status
   ```

   Continue only when supervisors, bot processes, and lock listeners are all zero
   and remain zero after a second status check.
2. Set `CLOUD_POLLING_ENABLED=true` in the existing Bot Doppler production config
   and wait for the existing Heroku sync. Do not alter `DATABASE_URL`.
3. Start exactly one Eco worker:

   ```powershell
   heroku ps:scale worker=1:Eco --app student-ai-bot-ernar-beta
   heroku ps --app student-ai-bot-ernar-beta
   heroku logs --tail --app student-ai-bot-ernar-beta
   ```

   Require one worker formation and one `CLOUD_POLLING_LEASE_ACQUIRED` marker. A
   second worker fails closed on the PostgreSQL advisory lease.
4. Smoke-test `/start`, `/balance`, text analysis, `Как защитить`, and `/buy`.
   Do not complete a real Stars payment without separate owner approval. Check Core
   balance/entitlement/admin and watch Sentry plus the aggregate outbox backlog.

## Rollback

Stop cloud polling before restarting local polling:

```powershell
heroku ps:scale worker=0 --app student-ai-bot-ernar-beta
heroku ps --app student-ai-bot-ernar-beta
.\scripts\cutover_local_bot.ps1 -Action Start
.\scripts\cutover_local_bot.ps1 -Action Status
```

Set the Bot Doppler latch back to `CLOUD_POLLING_ENABLED=false`. Require Heroku to
show no worker dynos, then require exactly one local lock listener. Preserve the
cloud PostgreSQL outbox and backups for investigation; do not delete or replay rows
manually.
