# Contributing

Thanks for taking an interest. This repo drives a live trading-research
platform through its REST API, so a few of the rules below are stricter than
you might expect from a Python CLI. They exist because mistakes here cost real
simulation quota, or publish something irreversible.

## Getting set up

Use Python 3.12+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)
on macOS or Linux. The system interpreter may not meet the package requirement.

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

Create `~/.brain_credentials.json` privately in a text editor, using this format:

```json
{"email": "you@example.com", "password": "..."}
```

```bash
chmod 600 ~/.brain_credentials.json
.venv/bin/python -m wqo auth status
```

Keep the password out of shell history, chat and logs. WQO's authentication flow
reads the file internally; agents must not inspect or print its contents. If auth
returns a Persona inquiry URL, complete it yourself in a browser, then run
`.venv/bin/python -m wqo auth persona`. See [onboarding](docs/installation.md#authenticate).

## What not to commit

Public repo, live accounts. Four things must never land in a branch:

- **Credentials or session cookies.** `~/.brain_credentials.json` lives outside
  the repo. `*credentials*.json` and `*session*.json` are gitignored as a
  backstop, not as permission to move them in-repo.
- **Your alpha expressions and their statistics.** These are your IP and, on a
  crowdsourced platform, your edge. `ideas/` and `provenance/` are gitignored
  for exactly this reason. Do not add expression dumps, PnL series, or
  shortlists to tracked files — including in an issue or a PR description.
- **Your account details.** `auth status` and `account status` return private
  account information. `.venv/bin/python -m wqo account snapshot` writes a
  private, gitignored `ACCOUNT.local.md` in the current directory. It preserves
  existing notes unless `--overwrite` is supplied. Available in WQO 0.1.1+;
  it makes account reads, with no simulation/submission.
- **Anyone's personal details** — account ids, university, country, rank — in
  docs or example payloads. Use `<your account id>` style placeholders. Real
  values were scrubbed out of the docs once already.

## Changes that need a test

The offline suite is the only thing standing between a refactor and a wasted
day of quota. Several existing tests encode bugs that shipped once already, so
please add a regression test when you touch:

- **gate thresholds** or anything in `wqo/config.py` that decides pass/fail
- **slot and concurrency behaviour** — the shared ledger, the slot queue, the
  learned-concurrency backoff. `tests/test_safety.py` includes
  `test_three_processes_share_one_simulation_slot` and atomic reservation tests
  that exercise contention between independent processes.
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
- Inspect sparse fundamentals before testing `ts_backfill(field, 60)`;
  missing values can concentrate weights and backfill can carry stale values.
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

Edit tracked `skills/<name>/SKILL.md` files. Shared setup lives in
`skill-support/`; run `.venv/bin/python scripts/sync_skills.py` after editing it.
Every skill must work on its own without a clone, install missing WQO locally,
and carry the credential, Persona, quota and submission boundaries.

Installed agent folders are gitignored. Refresh them from local sources using
the project-local command in [docs/skills.md](docs/skills.md#install-in-your-project);
never edit an installed copy as the source or use `--global` for this workflow.

## Reporting something sensitive

If you find a way for this tool to leak credentials, submit without
confirmation, or expose another user's data, please follow
[SECURITY.md](SECURITY.md) rather than opening a public issue.
