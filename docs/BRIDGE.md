# Student OS bridge: staged integration

The signed client and separate durable payment outbox are implemented and tested.
Handlers are not connected yet; do not enable the flag for live use.

Configuration (default OFF): `STUDENT_OS_BRIDGE_ENABLED=false`,
`STUDENT_OS_API_URL` is the HTTPS Core origin, `STUDENT_OS_BRIDGE_SECRET`
matches Core `BOT_BRIDGE_SECRET`. HTTP is accepted only on loopback for tests.
Never commit actual secrets. The current runtime still requires its legacy OpenAI key.

The client signs timestamp + nonce + exact UTF-8 JSON, has bounded bodies/responses,
rejects redirects and never retries AI automatically. Payments use Core's existing
`charge_id`, `product_id`, `stars_paid`, `telegram` contract.

The outbox is a separate SQLite journal, not the old user/payment ledger. Persist a
successful Telegram payment before network delivery. Retry pending rows at startup
and periodically in bounded batches. Core credits once by charge ID. An ambiguous
timeout stays pending. A late failed retry cannot downgrade an already delivered row.
Conflicting duplicate payment identity/product/amount is rejected; name changes are safe.

Next: connect balance/catalog/text/payment handlers behind the default-off flag,
add startup/periodic retries and cross-project contract tests. No live restart,
database migration or production enablement is part of this checkpoint.
