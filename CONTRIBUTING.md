# Contributing

Thanks for taking an interest. This repo drives a live trading-research
platform through its REST API, so a few of the rules below are stricter than
you might expect from a Python CLI. They exist because mistakes here cost real
simulation quota, or publish something irreversible.

## Getting set up

Python 3.12 or newer. System Python on macOS is 3.9 and will not run this code —
it uses `X | None` annotations and modern generics.

```bash
git clone https://github.com/aaditya-v-more/worldquant-orchestrator
cd worldquant-orchestrator
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
```

Run the tests. They are offline — no network, no credentials, no account
needed — so this should pass on a fresh clone before you configure anything:

```bash
.venv/bin/python -m pytest tests -q
```

If you want to run the tool against BRAIN rather than just work on it, you need
your own [WorldQuant BRAIN](https://platform.worldquantbrain.com) account and a
credentials file you write yourself:

```bash
printf '{"email": "you@example.com", "password": "..."}' > ~/.brain_credentials.json
chmod 600 ~/.brain_credentials.json
```

Nothing in this repo writes, reads back, echoes or logs that file.

## What not to commit

Public repo, live accounts. Four things must never land in a branch:

- **Credentials or session cookies.** `~/.brain_credentials.json` lives outside
  the repo. `*credentials*.json` and `*session*.json` are gitignored as a
  backstop, not as permission to move them in-repo.
- **Your alpha expressions and their statistics.** These are your IP and, on a
  crowdsourced platform, your edge. `ideas/` and `provenance/` are gitignored
  for exactly this reason. Do not add expression dumps, PnL series, or
  shortlists to tracked files — including in an issue or a PR description.
- **Your account snapshot.** `ACCOUNT.local.md` holds your account id, level,
  rank and learned concurrency. It is gitignored. Regenerate it with
  `wqo account snapshot` rather than editing or sharing it.
- **Anyone's personal details** — account ids, university, country, rank — in
  docs or example payloads. Use `<your account id>` style placeholders. Real
  values were scrubbed out of the docs once already.

## Changes that need a test

The offline suite is the only thing standing between a refactor and a wasted
day of quota. Several existing tests encode bugs that shipped once already, so
please add a regression test when you touch:

- **gate thresholds** or anything in `wqo/config.py` that decides pass/fail
- **slot and concurrency behaviour** — the shared ledger, the slot queue, the
  learned-concurrency backoff. The three-process contention test is the only
  one that catches the startup race.
- **budget accounting** — local days use US Eastern with DST. Submissions also
  enforce a rolling 24-hour cap until the platform reset convention is verified;
  pending/unknown writes retain quota across day boundaries
- **mining templates and scoring** — a template that emits an expression BRAIN's
  parser rejects burns a slot to discover

## Writing FASTEXPR

If you are adding or changing a mining template, read
[`docs/fastexpr.md`](docs/fastexpr.md) first. The constraints in it each cost a
real simulation to find. The ones that bite most often:

- No scientific notation. `1e-9` fails with `Unexpected character 'e'`. Write
  `0.000000001`.
- Backfill sparse fundamentals with `ts_backfill(field, 60)`, or the field is
  NaN most days and the book silently concentrates into a handful of names.
- Operator availability depends on account level. Check
  `wqo data operators` before assuming one exists.

## The submission rule

**Never submit an alpha without an explicit, specific human yes.**

Submission is irreversible, consumes a daily quota of three, and permanently
affects future self-correlation. `wqo submit <id>` without `--confirm` only
prints the check report and exits 4; `--confirm` is the live action. Approval
for one alpha is never approval for the next.

The same applies to anything automated you build on top of this: a script,
a scheduled job, or a coding agent driving the CLI must stop and ask. If you
are changing `wqo/submit.py` or the gate, assume a reviewer will read that
diff closely.

Related: do not raise `WQO_SIM_BUDGET`, `WQO_SUBMIT_BUDGET` or
`WQO_MAX_CONCURRENCY` to work around a limit, and do not automate around the
Persona biometric check. Hitting a cap is information, not an obstacle.

## Pull requests

- Branch off `main`. One concern per PR.
- Run `.venv/bin/python -m pytest tests -q` before pushing. CI runs the same
  suite on 3.12 and 3.13.
- Write the commit message for someone who will read it in a year without the
  conversation that produced it: what was wrong, what changed, why this way.
  The existing history is the house style — it is verbose on purpose.
- Say in the PR whether you verified anything against a live account, and if
  so, roughly what it cost in quota.

## Agent skills

`.claude/skills/wq-*` are the skill wrappers, symlinked to `.github/skills` and
`.qoder/skills` so Copilot and Qoder read the same files. Edit the copy under
`.claude/skills/` — the other two are symlinks, and editing through them works
but makes the diff confusing.

Every skill should stand alone: someone starting cold from that file should
know which directory to run from, that a venv is required, and where the hard
rules live. If you add a skill, add the bootstrap block the others carry.

## Reporting something sensitive

If you find a way for this tool to leak credentials, submit without
confirmation, or expose another user's data, please follow
[SECURITY.md](SECURITY.md) rather than opening a public issue.
