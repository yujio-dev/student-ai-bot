# Development checkpoints

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
