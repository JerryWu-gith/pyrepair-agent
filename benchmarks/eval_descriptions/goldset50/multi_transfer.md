# multi_transfer

Repair the in-memory `Ledger` (`src/ledger.py`) and `TransferService`
(`src/service.py`) without changing their existing public APIs. Construct a
ledger with `Ledger({account_name: integer_cents, ...})`, pass it to
`TransferService(ledger)`, and call
`transfer(request_id, source, destination, amount)`. Account names and request
IDs are strings. `ledger.balances` exposes the current balances and may be used
to add/fund accounts between calls. Initial balances are nonnegative integers.

A valid transfer uses a positive integer-cent amount (booleans are not amounts),
distinct existing accounts, and sufficient source funds. Return the receipt
tuple `(request_id, source, destination, amount)` and debit/credit exactly that
amount. Missing accounts raise KeyError; invalid amounts, same-account transfers,
insufficient funds, and conflicting request-ID reuse raise ValueError. All
validation must precede balance changes. Any failed request leaves all balances
unchanged and must not reserve its ID or payload: that ID can be retried after
correcting the problem, including with a different valid payload.

Within a service instance, successful requests are idempotent. Replaying the
same request ID with identical source, destination, and amount returns the same
receipt value without moving funds or requiring the source still to be funded.
Reusing a successful ID with any different payload fails without changing
balances or the original success. Different request IDs transfer independently;
different service instances do not share request history. Preserve ordinary
transfer results and validation errors. Concurrency and persistence are outside
this task's contract. Edit production Python only; public examples are incomplete.
