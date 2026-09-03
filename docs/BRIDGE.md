# Student OS bridge: staged integration

The signed client, durable payment outbox and Telegram adapter are implemented.
Do not enable for live use before the manual cutover checks below.

Configuration (default OFF): `STUDENT_OS_BRIDGE_ENABLED=false`,
`STUDENT_OS_API_URL` is the HTTPS Core origin, `STUDENT_OS_BRIDGE_SECRET`
matches Core `BOT_BRIDGE_SECRET`. HTTP is accepted only on loopback for tests.
Never commit actual secrets. The current runtime still requires its legacy OpenAI key.

The client signs `v2.POST.<endpoint path>.<timestamp>.<nonce>.<exact UTF-8 JSON>`, has bounded bodies/responses,
rejects redirects and never retries AI automatically. Payments use Core's existing
`charge_id`, `product_id`, `stars_paid`, `telegram` contract.

The outbox is a separate SQLite journal, not the old user/payment ledger. Persist a
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

Text requests use Telegram user/chat/message IDs as stable request IDs. Answers
are formatted as bounded plain-text messages (no executable markup). The defense
button reads the same result, without a second AI call; five results per user are
retained in process memory for at most one hour. Process restart expires buttons.
Photo and old defense/admin/referral callbacks are blocked in bridge mode until
their shared-domain equivalents exist; no legacy balance is consulted or mutated.
The legacy reactivation-credit loop is replaced by the outbox worker in bridge mode.

Manual cutover: back up both databases and the outbox; deploy Core on HTTPS with
persistent storage; configure matching secrets; check signed catalog/identity and
owner Web admin; run synthetic text/payment/outage tests; only then enable the flag
and restart the managed bot explicitly. Check /balance, text, /buy and Web refresh.
Rollback: set the flag false and restart. Keep pending outbox rows: disabling the
bridge stops retries and requires delivery/reconciliation before retiring Core.
Never overwrite Core with the old bot database. No live restart, production
deployment, credentials use or payment was performed by these tests.
