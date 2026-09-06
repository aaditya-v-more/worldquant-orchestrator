# Setup and operational boundaries

Use macOS or Linux. Run from the user's working project, not the skill source
repository. Resolve `scripts/wqo.sh` relative to the installed SKILL.md and invoke
it by absolute path with Bash. Commands written as `wqo ...` in the skill mean
`bash /absolute/path/to/this-skill/scripts/wqo.sh ...`.

The runner reuses a compatible WQO CLI on PATH or in the project's `.wqo/venv`.
When missing, it installs `wqo==0.1.0` from PyPI into that project environment,
using uv or Python 3.12+. It never installs skills or the CLI globally, edits
shell profiles, or changes credentials. If both prerequisites are missing, show
the prerequisite error; do not invent an installer. `WQO_PROJECT_DIR` can select
an existing project explicitly. Keep `.wqo/` and installed agent skill folders
out of Git. The runner preserves CLI arguments, JSON output and exit codes.

Before the first live operation, run `wqo state` and `wqo auth status`. These
skills do not assume a particular account, level, operator count or concurrency.
Use the installed CLI's `--help` for flags. Do not call `account snapshot`: it is
not in WQO 0.1.0. Raw `api` accepts only reads.

- Never submit without an explicit yes in this conversation for that specific
  alpha. Installation, mining and a passing report do not authorize submission.
- Never read back, write, echo or log `~/.brain_credentials.json`. If absent,
  give the user the JSON format `{"email":"...","password":"..."}` and have
  them create it privately in a text editor, then `chmod 600` it. Only WQO's
  normal authentication flow uses the credentials.
- On Persona verification, give the inquiry URL to the user and wait until they
  confirm completion before `wqo auth persona`. Never automate or bypass it.
- Exit 3 means stop at the quota. Never raise budgets/concurrency or weaken gate
  thresholds to work around a failure. Unknown submissions retain quota across
  days; inspect the outcome instead of retrying or deleting the ledger.
- Reuse the existing per-user ledger (`wqo state`). When upgrading a checkout,
  stop other WQO processes and use `wqo state --migrate-from /old/checkout/data`
  or keep `WQO_DATA_DIR` pointed at that ledger. Never start a new ledger to evade
  quota, and do not change its location just because skills were installed.
- Before a BRAIN metadata write, check names/tags/descriptions for tool labels,
  mining template IDs or test names. Keep provenance local, not in BRAIN fields.
- Keep real alpha expressions, results and account details out of tracked files
  and public posts. Report failed candidates and unavailable checks honestly.

Exit codes: 0 success; 1 error/gate blocked; 2 auth/Persona; 3 budget exhausted;
4 submission refused. Inspect these statuses rather than assuming any JSON means
success. CLI setup alone does not spend simulation or submission quota.
