# Running several agents against one account

Multiple people and multiple agent sessions share this repo, and BRAIN counts
simulation slots, daily budgets, and submissions **per account** — not per
process. Two agents that each assume they own the account will collide. This
document is what makes that safe.

## The shared ledger is the coordination point

Everything cross-process lives in one SQLite file, `data/wqo.sqlite`:

| Table | Shared fact |
|---|---|
| `slot_queue` | who holds a simulation slot right now, and who is waiting |
| `kv` (`learned_concurrency`) | how many slots BRAIN actually allows |
| `simulations` | today's simulation count, for the daily budget |
| `submissions` | today's submission count, for the daily budget |

The connection runs in WAL mode with a 10 s busy timeout, so concurrent readers
and one writer proceed without `database is locked`.

## The simulation slot queue

Before this existed, each process built its own in-memory `SlotManager`, each
believed it held the account's only slot, and the second `POST /simulations`
came back 429 — the symptom being a batch that stalls and retries for no
visible reason.

Now `SlotManager.acquire()` takes a ticket in `slot_queue` and blocks until it
is granted. The rules:

- **At most `learned_concurrency` holders account-wide**, across every process.
- **Grants go in ticket order.** A waiter is only granted when the number of
  current holders plus the number of waiters ahead of it is below the limit, so
  a long mining batch cannot starve a single interactive simulation.
- **Holders heartbeat on every simulation poll.** A row untouched for
  `STALE_SLOT_AFTER` (180 s) is assumed dead — killed agent, crashed process —
  and reaped so the slot returns to the pool.
- **The limit is re-read from the ledger on every attempt**, so when one agent
  hits a 429 and shrinks the learned concurrency, every other agent respects
  the new number immediately.

Inspect the queue at any time:

```bash
.venv/bin/python -m wqo auth slots
```

```json
{"limit": 1,
 "holding": [{"ticket": 41, "owner": "host:8123:Thread-2", "label": "eps_to_price:eps_mean", "held_for": 12.4}],
 "waiting": [{"ticket": 42, "owner": "host:8207:MainThread", "label": null, "waiting_for": 9.1}]}
```

A stuck batch usually means someone else holds the slot, not a bug. Check here
before diagnosing anything else.

## One process never takes more than its share of tickets

`SlotManager` gates in-process first: a thread waits on a local condition until
fewer than `limit` of its own siblings are active, and only then joins the
shared queue. So a mining batch with a large thread pool still holds at most
`limit` tickets, and cannot bury another agent's single simulation under ten of
its own. `simulate_many` sizes its pool to `learned_concurrency + 1` anyway —
one spare to keep the pipeline warm if the limit grows mid-run.

## What is still not coordinated

- **Budgets are advisory across agents.** They count correctly — the ledger is
  shared — but two agents can pass the check at the same instant and both
  proceed. The server's own limits are the real backstop.
- **The local ledger only sees work done through this tool.** Anything
  submitted from the website is invisible to it. When the number matters, read
  `/users/self/activities/submissions` instead.
- **Submission is never automatic.** Two agents must not both be submitting;
  every submission needs the user's explicit yes for that specific alpha, which
  serialises it by construction.

## Per-user facts stay out of tracked files

Level, score, slot count, operator count, and which endpoints 403 differ per
account. They live in a gitignored `ACCOUNT.local.md`:

```bash
.venv/bin/python -m wqo account snapshot
```

Never copy those numbers into a tracked doc — the next person to read it has a
different account.
