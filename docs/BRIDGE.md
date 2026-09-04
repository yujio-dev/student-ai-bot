# Student OS bridge: staged integration

The signed client, durable payment outbox and Telegram adapter are implemented.
Do not enable for live use before the manual cutover checks below.

Configuration (default OFF): `STUDENT_OS_BRIDGE_ENABLED=false`,
`STUDENT_OS_API_URL` is the HTTPS Core origin, `STUDENT_OS_BRIDGE_SECRET`
matches Core `BOT_BRIDGE_SECRET`. HTTP is accepted only on loopback for tests.
Never commit actual secrets. Bridge mode does not instantiate the legacy AI client or require its OpenAI key; Core owns that key.

The client signs `v2.POST.<endpoint path>.<timestamp>.<nonce>.<exact UTF-8 JSON>`, has bounded bodies/responses,
rejects redirects and never retries AI automatically. Payments use Core's existing
`charge_id`, `product_id`, `stars_paid`, `telegram` contract.

The outbox is a separate persistence boundary, not the old user/payment ledger. Persist a
successful Telegram payment before network delivery. Retry pending rows at startup
and periodically in bounded batches. Core credits once by charge ID. An ambiguous
timeout stays pending. A late failed retry cannot downgrade an already delivered row.
Conflicting duplicate payment identity/product/amount is rejected; name changes are safe.

With the flag ON, a first-priority dispatcher routes /start, /balance, /buy, text,
pre-checkout and successful payments to Core. Legacy handlers do not receive these
updates. /start buy opens the Core catalog directly. Pre-checkout fails closed if
the five-second catalog request fails. The outbox retries at startup and every
60 seconds in batches of 20. Invalid receipts remain pending. The journal is
`core_payment_outbox.db` beside DATABASE_PATH; back it up along with Core data.

On Heroku, managed `DATABASE_URL` selects PostgreSQL schema `bot_outbox` in the SAME
Essential-0 as Core. Do not create another add-on or sync this URL from Doppler.
Cloud bridge boot without a URL fails closed. SQLite remains the local fallback.
Only outbox records/indexes are written by this adapter; all business mutations use
the signed Core API. Two bounded connections, remote TLS, 10s connection/lock and 15s
statement timeouts; atomic idempotent schema initialization. No DB transaction spans
HTTP delivery. Concurrent delivery is at-least-once; Core charge uniqueness enforces
exactly-once credits. Unknown/wrong receipts remain pending; delivered rows are not
resent from stale snapshots. Never delete the journal on rollback.

Tests include a child process terminated via os._exit after durable enqueue and
restart, malformed receipts, network/500/timeout failures and concurrent retries.
Storage failure BEFORE enqueue is not a durable acceptance: no success is reported,
and an operator must reconcile Telegram payments if Telegram has acknowledged the
update. PostgreSQL durability does not make Telegram polling + database one atomic
transaction. Cutover must include this operational recovery boundary.

Text requests use Telegram user/chat/message IDs as stable request IDs. Answers
are formatted as bounded plain-text messages (no executable markup). The defense
button reads the same result, without a second AI call; five results per user are
retained in process memory for at most one hour. Process restart expires buttons.
Old defense/admin/referral callbacks are blocked in bridge mode; no legacy balance is consulted or mutated.
The legacy reactivation-credit loop is replaced by the outbox worker in bridge mode.

Manual cutover: back up both databases and the outbox; deploy Core on HTTPS with
persistent storage; configure matching secrets; check signed catalog/identity and
owner Web admin; run synthetic text/payment/outage tests; only then enable the flag
and restart the managed bot explicitly. Check /balance, text, /buy and Web refresh.
Rollback: set the flag false and restart. Keep pending outbox rows: disabling the
bridge stops retries and requires delivery/reconciliation before retiring Core.
Never overwrite Core with the old bot database. No live restart, production
deployment, credentials use or payment was performed by these tests.

## Shared photo flow

Bridge-mode Telegram photos now call Core quote → explicit confirmation → recognition
→ task selection. Cost matches the old setup semantics: one shared trial or five paid
credits (the unchanged 100 Stars package); unlimited has no debit. A changed entitlement
requires a fresh quote instead of silently charging another source. Core validates PNG/
JPEG bytes and decoded dimensions before AI; Telegram photos are sent as JPEG.
The two signed photo-upload operations allow bounded 9 MiB JSON envelopes for a maximum
6 MiB image; every other bridge request remains limited to 64 KiB.

Raw pending photo bytes exist only in memory, expire after five minutes, and are removed
on confirmation. Core retains recognized tasks for 24 hours, not raw images. Buttons
select one/all tasks; follow-ups use the same structured engine and defense result without
another setup charge, bounded to 20 requests/hour. Latest Core session can be recovered
after a bot restart. Old session buttons cannot select a different newer photo silently.
Use /newtask to clear the adapter's current selection. Quality of live OCR and real Stars
cutover still require an explicitly authorized staging check; all automated tests use fixtures.
