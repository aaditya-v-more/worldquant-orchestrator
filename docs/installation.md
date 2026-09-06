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

## Authenticate

You need your own [WorldQuant BRAIN account](https://platform.worldquantbrain.com).
Create `~/.brain_credentials.json` yourself in a text editor, using:

```json
{"email": "you@example.com", "password": "..."}
```

Never place your actual password in a shell command, chat, issue or repository.
For a new file, you can create it privately before opening it in your editor:

```bash
(umask 077; set -C; : > ~/.brain_credentials.json)
```

This command refuses an existing file; it does not replace your credentials.
After saving valid JSON in your editor, run:

```bash
chmod 600 ~/.brain_credentials.json
wqo auth status
```

`auth status` uses a cached session or authenticates as needed. Exit `2` means
authentication is required or incomplete. If the error provides a Persona
inquiry URL, open it yourself in a browser, complete verification, then run
`wqo auth persona`. An agent must wait for your confirmation. For a missing or
invalid credentials file, correct it privately; do not paste its contents into
chat. `wqo auth login` explicitly requests a fresh login.

## First example

Check installation without credentials, network access to BRAIN or research quota:

```bash
wqo --version
wqo state
wqo sim run --help
```

After authentication, this illustrative expression runs one live backtest:

```bash
wqo sim run --code "rank(close)" --neutralization NONE --test-period 1y
```

The expression is synthetic; BRAIN evaluates it against its historical data.
Running it sends the expression and settings to BRAIN and uses simulation quota.
It does not submit an alpha. Results are account/settings dependent and do not
guarantee future performance; no expected metrics are claimed for this example.

For agents, install [portable skills](skills.md) from your working project using
Node.js/npm and uv (or Python 3.12+):

```bash
npx skills add aaditya-v-more/worldquant-orchestrator --skill wqo-cli
```

Choose your agent and omit `--global`. Invoke the skill and ask for a version
check first; it uses its bundled runner for the commands above. A skill-local
CLI install does not add `wqo` to your shell PATH. Resolve the runner location
as described in [automatic CLI setup](skills.md#automatic-cli-setup).

## Private account notes (0.1.1+)

`wqo account snapshot` writes a dated `ACCOUNT.local.md` in your working directory
with minimal account identifiers, competition progress, learned concurrency and
local quota usage. The file is created atomically with permissions `0600`; the
command prints only its path. Existing files are preserved unless you pass
`--overwrite`. Keep the snapshot out of Git, including in projects other than
this repository. It makes account reads but no simulations or submissions.

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
`uv tool install --python 3.12 'wqo==0.1.1'`. Package removal does not remove your
ledger or credentials. Keep state backups before changing versions.

The [portable skills](skills.md) automatically install missing WQO into the
working project's `.wqo/venv`, using uv or Python 3.12+. They verify the CLI before
running commands. Skills install separately through `npx skills`; they are not
bundled into the Python installation.

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
