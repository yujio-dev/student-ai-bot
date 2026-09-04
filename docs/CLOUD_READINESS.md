# Cloud worker readiness — owner away

Procfile is worker-only: python -m app.cloud_worker. Python 3.12. No release command.
Keep formation worker=0; CLOUD_POLLING_ENABLED defaults false and stops startup before
credentials are loaded. NO cloud/local cutover or local ScheduledTask restart now.
The entry point installs bridge handlers only, not legacy SQLite ledger/AI services.
Requires bridge enabled, HTTPS Core, strong shared secret, Heroku PostgreSQL outbox.

`python -m app.cloud_preflight` reads only environment, never .env/storage/network.
It prints names, not secret values. Core credentials come through existing Doppler
sync after owner CLI login; DATABASE_URL remains Heroku-managed. Bot needs no OpenAI
key in bridge mode. No credentials or new paid resources created in this checkpoint.

Background outbox retries persist 1/2/4/8/16/32/60-minute backoff, capped at 60 minutes.
No keepalive for empty queues; no paid record discarded on timeout. Existing manual
retry default remains immediate. Receipt validation and Core exactly-once charge
deduplication unchanged. Real cold-start latency/production runtime still need QA.

Optional SENTRY_DSN enables allowlisted category-only errors; no automatic integrations,
trace/session/PII/stack/local data. Real SDK tested with memory transport; no actual
Sentry account or DSN configured. Unset DSN makes no telemetry connection.

Deployment: push tested commit, verify successful Python build and worker formation 0.
No worker process auto-starts by default; independent latch also blocks accidental
polling. Never use a one-off app.cloud_worker command as a smoke test.
Use preflight only after configuration. Core signed health and disposable synthetic
bridge/outbox tests must pass before any later owner-approved cutover.

Rollback stops cloud polling first and preserves PostgreSQL outbox. Do not reset/drop
storage or switch paid flows until pending charges are reconciled. Original local
branding/assets are owner changes and deliberately excluded from migration commits.

Full domain/DNS/ACM, HTTPS/BrowserStack matrix, secret boundaries and exact next owner
login command: Core docs/CLOUD_READINESS_CHECKPOINT.md in yujio2x/student-os.
