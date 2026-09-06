# Install and upgrade WQO

WQO requires Python 3.12+ and supports macOS and Linux. The package, import and
command names are all `wqo`. Windows simulation support is not yet available.

## Install the command

[Install uv](https://docs.astral.sh/uv/getting-started/installation/) if `uv --version`
is unavailable, then install WQO in its own isolated tool environment:

```bash
uv tool install --python 3.12 wqo
wqo --version
wqo --help
```

uv can provision the requested Python version. If the installed command is not
on PATH, run `uv tool update-shell` and open a new terminal. Commands work from
any directory; there is no repository checkout or local `.venv` requirement.

If you already have Python 3.12+ and pipx:

```bash
pipx install --python python3.12 wqo
```

For Python-library use, install `wqo` with pip into your project's virtual
environment. `python -m wqo` and the `wqo` command expose the same interface.

## Existing users: preserve your ledger first

Stop other WQO processes before switching installations. The ledger records
quotas, previous submissions and unresolved actions; keep it across upgrades.

The new default is `$XDG_DATA_HOME/wqo` when XDG_DATA_HOME is absolute, otherwise
`~/.local/share/wqo`. It is independent of the checkout and installation path.
`wqo state` shows the selected paths without contacting BRAIN or creating state.

```bash
wqo state --migrate-from /absolute/path/to/old-checkout/data
```

This copies the ledger, catalog, pending Persona state and log to the new default
using SQLite backups and private permissions. It keeps the original files,
refuses an existing destination and refuses recorded simulation permits. Resolve
any remaining permits before migrating. Candidate batches and provenance files
remain wherever you saved them; this migration does not move those directories.

To retain an existing location instead, set `WQO_DATA_DIR` to its absolute path
in your shell and agent environment. Use the same location in every installation;
do not alternate between divergent ledger copies. Credentials and session-cookie
paths remain unchanged at `~/.brain_credentials.json` and `~/.brain_session.json`;
`WQO_CREDENTIALS` and `WQO_SESSION` remain supported.

## Verify and upgrade

```bash
wqo --version
wqo state
wqo auth status
uv tool upgrade wqo
```

For pipx, use `pipx upgrade wqo`. To install a specific supported release, use
`uv tool install --python 3.12 'wqo==0.1.0'`. Package removal does not remove your
ledger or credentials. Keep state backups before changing versions.

A missing CLI can be installed automatically by a future core skill using this
flow: detect `wqo`, check its version, check `uv`, install the published package
if absent, verify `wqo --version`, then perform auth onboarding. Skill distribution
is a separate launch task; it is not bundled into the Python installation.

## Build and publish from source

From the repository root:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
.venv/bin/python -m build
.venv/bin/python -m twine check --strict dist/*
.venv/bin/python scripts/check_dist.py dist
```

After installing and testing both archives in clean environments, publish the
reviewed files using `uv publish` or `python -m twine upload`. Configure your PyPI
API token locally or use PyPI trusted publishing; never place credentials in Git
or paste them into issues/chat. A missing public PyPI project does not reserve
its name; the first successful upload establishes ownership.
