# Development checkpoints

## 2026-09-04 — Monitoring labels and non-polling runtime preflight

Sentry scrubber now preserves only allowlisted environment and service labels, while
continuing to discard payloads, requests, credentials, user data and arbitrary host
names. Invalid/unhashable categories drop safely. SENTRY_ENVIRONMENT is restricted to
development/test/staging/production; explicitly set intended cloud label before enabling
DSN. Privacy tests run against the real SDK with memory transport, no sensitive events.

Added optional `python -m app.cloud_preflight --storage`: imports cloud entrypoint without
calling it, verifies latch false, initializes/reads only bot-owned PostgreSQL outbox,
discards rows and reports generic success/failure. No polling or Core payment mutation.
Existing config-only command passed inside an actual one-off Eco dyno, exit 0. An
inline extended probe failed at local Windows quoting before remote execution; replaced
with the testable module option. Extended deployed probe still pending a tested release.
Owner OIDC setup now confirmed by Core read-only preflight. Core remains staging until
explicit production-mode permission is accepted by action review. No live restart.

## 2026-09-04 — Independent cloud readiness while Doppler login blocked

Owner explicitly blocks Doppler CLI login until home. No attempts to log in, no secret
migration, no config-var changes, no live restart/cutover or additional paid resources.
Added Python 3.12/worker-only Procfile and slug exclusions. Cloud entry point does not
initialize legacy SQLite/AI and checks an independent false-by-default polling latch
before loading credentials. Preflight reads environment only and reports key names.
Eco background retry uses persisted capped exponential backoff; empty queues do not
wake Core. Pending paid records remain durable, with unchanged charge idempotency.
Optional content-free Sentry uses a real SDK with memory-transport privacy regression.
Deployment/rollback and config boundaries documented in CLOUD_READINESS.md.

ATTACK: tested accidental polling without credentials, invalid cloud configs/HTTPS,
secret-bearing URL shapes, hostile telemetry content, duplicate/replayed payment,
persisted retry delay and high attempt-count cap. No real Telegram/OpenAI calls.
Local full suite: 89 tests, 4 expected PostgreSQL skips. Existing real-Heroku persistence
suite: 6 passed (132s), including abrupt process crash. Added PostgreSQL backoff contract
is also in the dedicated CI job; compile/diff/PWA checks pass. CI status recorded after push.
Original app/bot.py branding and untracked assets/outputs preserved, not staged.
Deployment remains worker=0; no runtime acceptance or live cutover claimed.

Final external verification: code 57c205a pushed; GitHub run 33870851244 GREEN,
including tests and PostgreSQL-outbox jobs (new persisted backoff contract included).
Same tested commit deployed to existing student-ai-bot-ernar-beta, Heroku release v5:
Python 3.12.14, successful dependency/buildpack build, Procfile worker only. Explicitly
set worker=0:Eco; subsequent ps returned No dynos. No polling/one-off runtime started.
Core 29393cf CI run 33870953687 GREEN, both normal and PostgreSQL jobs. No credentials,
Doppler syncs or managed DATABASE_URL changed. No additional paid resource.
Only owner branding/assets/outputs remain dirty; migration changes committed/pushed.
STOP gate: owner scoped Doppler login, then allowlisted migration and Core preflight;
bot stays worker=0/latch=false. Full cloud behavior still unverified, not live cutover.

## 2026-09-04 — PostgreSQL durable payment outbox

Started from f6e4552, preserving pre-existing app/bot.py branding edits and assets/outputs.
No bot restart, Telegram polling, secret migration, paid resources or real payment.
PostgreSQL outbox owns only bot_outbox schema; it never writes the Core ledger/users.
Existing Heroku-managed DATABASE_URL selects it; local SQLite and bridge-OFF preserved.
Atomic initialization/enqueue/update, bounded connections and short advisory-locked
transactions. HTTP calls run outside storage transactions. Core charge uniqueness,
not a local delivery flag, is the exactly-once business boundary.

ATTACK: malformed nested receipts previously raised an unclassified AttributeError;
stale delivered snapshots could resend; truncated HTTP response was not normalized.
All three closed. Invalid charge/product/amount/identity never marks delivered.
Concurrent success/failure cannot downgrade delivered; ambiguous commit retries with
the same charge. Schema-isolated tests cover duplicate/concurrent retry and real child
process crash/restart. Core cross-project regression covers lost response AFTER actual
ledger commit and exactly one credit/payment after concurrent retries.

Validation: bot suite 79 tests (3 PostgreSQL cases skipped without URL); dedicated
real-Heroku/SQLite persistence run 6 passed. Core full suite 103 passed; real outbox
to PostgreSQL Core lost-commit/concurrent retry test passed. Compile/diff checks pass.
One sandbox-only rerun failed to access temporary SQLite files; repeat with normal
test temp access passed (79 tests, 3 expected skips), not a product regression.
No private data in fixtures.
Remaining: attachment/config/deploy with worker=0, Doppler, Core restart persistence,
domain/OIDC/Sentry/device QA/cold-start and final cutover. Storage unavailable before
enqueue requires Telegram reconciliation; see BRIDGE.md. No live cutover claimed.
## 2026-09-04 — Authorized production deployment and isolated monitoring smoke

Owner explicitly authorized Core production mode/deployment and Sentry DSN storage
in both existing Doppler stg configs. Latest restrictions: no DNS changes, no live
Telegram cutover, cloud worker stays zero. No new resources/plans were provisioned.
Production config preflight passed (secure cookies, dev login/admin off, Core ledger,
OIDC fields present and matching expected callback). DATABASE_URL is unchanged and
Heroku-managed only. Core 233513e built/released as v9: Eco web up, health HTTP 200.
Bot fb64c2e built/released as v8; subsequent config releases may advance release IDs.
Bot one-off --storage preflight passed CLOUD_IMPORTS_AND_POSTGRES_OUTBOX_OK_NO_POLLING.
Both existing Sentry error-only projects now have DSNs saved directly to Doppler,
with production environment and no replay/tracing/default integrations or PII enabled.

Added explicit python -m app.monitoring_smoke core|bot for one constant synthetic
event with bounded flush and generic failure output. Event ID is correlation only,
not delivery evidence; Sentry UI verification is required. No app/polling import.
Regression: Core 112 passed / 25 expected PG skips; Bot 93 tests / 4 PG skips.
New smoke tests cover constant payload, bounded flush, missing config, private errors.
Cloud acceptance runner in Bot confines writes to unique synthetic identity/payment,
targets only the two approved apps, reads credentials in memory, and restarts Core
only with explicit --exercise. It never retries unrelated pending outbox records.
Actual signed health/catalog and six auth-negative checks passed. Synthetic lost
response after committed payment, durable outbox reopen/retry and exactly-once credit
passed. Evidence run: 57dffbbafb414bfc84c5b86ba9daff40. Core restart then passed:
same user ID, payment row count one, balance one, unchanged migration version/checksum/
applied_at. Catalog, entitlement and duplicate-payment delivery work after restart.
This is an actual process-cold/restart test, NOT proof of a 30-minute Eco sleep wake.
Custom-domain OIDC/browser/admin proof remains blocked by owner's explicit DNS hold.
No local bot restart and no cloud polling were performed; owner edits stay untouched.
