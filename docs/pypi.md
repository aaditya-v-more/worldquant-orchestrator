# WQO — WorldQuant Orchestrator

A Python client and CLI for WorldQuant BRAIN research: discover data, generate
expressions, run simulations, analyze results, and review alphas for submission.

## Install

Python 3.12 or newer; macOS and Linux. With [uv](https://docs.astral.sh/uv/getting-started/installation/):

```bash
uv tool install --python 3.12 wqo
wqo --version
wqo --help
```

Alternatively, install in a Python virtual environment with `pip install wqo`,
or use `pipx install --python python3.12 wqo`. No repository clone is required.

## Authentication and use

Use your own WorldQuant BRAIN account. Create `~/.brain_credentials.json` in a
text editor with `email` and `password` fields; keep its permissions private
(`chmod 600 ~/.brain_credentials.json`). Do not put the password in shell history.

```bash
wqo auth status
wqo data operators
wqo sim run --help
wqo state
```

Authentication may require you to complete Persona verification in your browser.
No tool bypasses that step. Submission requires explicit confirmation for the
specific alpha, enforces a local quota and refuses duplicate or unresolved writes.
Most research candidates fail the quality gate; backtests do not guarantee returns.

State defaults to `~/.local/share/wqo` (or `$XDG_DATA_HOME/wqo`), outside the
installed package. `WQO_DATA_DIR` overrides it. Upgrading from a source checkout:
stop other WQO processes and migrate the existing ledger before any research:

```bash
wqo state --migrate-from /absolute/path/to/worldquant-orchestrator/data
```

Migration preserves the source and refuses an existing destination. To keep the
old location instead, set `WQO_DATA_DIR` to that absolute directory for every run.
Do not start with an empty ledger to avoid a quota or unresolved submission.

[Installation and upgrades](https://github.com/aaditya-v-more/worldquant-orchestrator/blob/main/docs/installation.md)
· [CLI documentation](https://github.com/aaditya-v-more/worldquant-orchestrator#readme)
· [Safety controls](https://github.com/aaditya-v-more/worldquant-orchestrator/blob/main/docs/safety.md)

MIT licensed. Not affiliated with or endorsed by WorldQuant. Agent skills are
maintained separately in the repository; installing this Python package installs
the CLI and library.
