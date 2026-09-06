# Safety and privacy controls

Raw `api` supports GET, HEAD and OPTIONS only. Use dedicated commands for writes;
`submit` still requires explicit confirmation for the specific alpha and a clean
quality gate (unless the user explicitly chooses the existing force option).
The HTTP client accepts only the HTTPS BRAIN API origin and refuses redirects.

Writes are sent once. Timeouts, connection failures, 401s, 429s and server errors
do not automatically replay them. Reads retain bounded retry behavior. A write
that fails may need human investigation before another attempt.

Submission uses a persistent SQLite reservation created atomically before POST.
Concurrent processes sharing that ledger cannot claim the same remaining quota
or submit the same alpha twice. Successful submissions retain a permanent
per-alpha duplicate guard. Pending and uncertain submissions consume quota even
after midnight or a process restart. Definitive initial rejections release the
reservation; errors during polling retain it. No automatic expiry assumes that
an uncertain submission failed.

Local calendar-day accounting uses `America/New_York`, including daylight-saving
time. Submission accounting additionally covers the preceding 24 hours; this is
a conservative local limit, not a verified statement about BRAIN's reset time.
It can make you wait longer than the platform. Actions performed in a browser,
on another machine, or using a different ledger are not included in local counts.
The platform's own quota remains authoritative.

Simulation permits and learned concurrency are shared by processes using the
same ledger. Permits belonging to exited processes are reclaimed on the next
acquisition; any remote simulation may still be running, so a server 429 stops
that write and reduces learned concurrency. This is a local process limit, not
a distributed lock across machines. Simulation budget reservations are atomic.

For an unresolved submission, inspect the alpha on BRAIN and the local ledger
before doing anything further. Preserve a backup and reconcile the existing row
only when its outcome is established; do not delete the ledger or increase the
budget to clear a block. There is deliberately no automatic retry or automatic
release of unresolved quota.

CLI JSON redacts credential, token, authorization and cookie fields recursively.
Non-JSON raw responses and server error bodies are omitted; HTTP diagnostics
exclude query strings and transport exception text. This protects known secret
fields, not arbitrary private alpha data. Do not publish raw output without
review. Session files are created with private permissions and replaced atomically.

The owner has confirmed that the current demo is entirely synthetic; the README
labels its expressions, identifiers and results as illustrative. The text
walkthrough is synthetic too. Historical documentation still contains personal
details. Editing the current tree does not remove older content from Git history,
forks, clones or caches; historical copies need separate review and cleanup.
