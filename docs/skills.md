# Portable WQO skills

The distributable sources are in `skills/`: `wqo-cli` plus `wqo-auth`, `wqo-data`,
`wqo-simulate`, `wqo-mine`, `wqo-analyze`, `wqo-alphas`, `wqo-submit` and
`wqo-account`. Each skill is self-contained, including its CLI setup runner and
operational boundaries. They are skill packages for the open skills ecosystem;
an npm package for WQO is not required.

## Install in your project

Run from the project where you want to use WQO, with Node.js/npm available:

```bash
npx skills add aaditya-v-more/worldquant-orchestrator --skill wqo-cli
```

Choose your supported agents in the installer. Add companions by name, or use
`--skill '*'` to install all nine. Installation is project-local by default;
do not add `--global` for this workflow. No manual clone is required.

For an existing source checkout, install the local sources instead:

```bash
npx skills add ./skills --skill '*' --agent codex claude-code github-copilot qoder --yes
```

The installer handles supported agent locations. It currently uses a canonical
`.agents/skills/` copy for Codex/Copilot and project-local links for Claude/Qoder.
Other supported agents can be selected through the installer without changing
the skill packages. Ignore your local installed skill directories and generated
`skills-lock.json`; keep the distributable `skills/` sources tracked.

## Automatic CLI setup

Invoke the skill in your agent. Its bundled `scripts/wqo.sh` resolves a compatible
`wqo` on PATH or under the current project's `.wqo/venv`. If absent, it installs
`wqo==0.1.1` from PyPI into that local environment using uv or Python 3.12+.
It does not perform a global tool install or edit shell configuration. When both
prerequisites are absent, it explains the required setup rather than running an
unreviewed installer. Supported runtime platforms are macOS and Linux.

For a manual smoke check, resolve the installed runner's actual location:

```bash
bash /absolute/path/to/installed/wqo-cli/scripts/wqo.sh --version
```

Companions work when installed alone and carry the same runner. CLI environment
location and ledger location are separate: skills retain the existing per-user
WQO state and authentication. Never switch ledgers to clear a quota or unresolved
submission. CLI setup does not authenticate or spend research quota by itself.

## Maintaining the packages

Edit workflow instructions in `skills/<name>/SKILL.md`. Edit shared setup in
`skill-support/`, then vendor it into the standalone packages:

```bash
.venv/bin/python scripts/sync_skills.py
.venv/bin/python scripts/sync_skills.py --check
.venv/bin/python -m pytest tests -q
```

Re-run the local `npx skills add ./skills ...` command to refresh installed copies.
Do not edit those copies as source. Shared resources are copied deliberately so
installing a single skill does not depend on another skill or repository files.

## Discovery

The standard repository layout supports discovery by `npx skills add ... --list`.
All nine public skill pages were verified on skills.sh on 2026-09-07, and the
GitHub-source install command was tested locally. Start with
[the core skill](https://skills.sh/aaditya-v-more/worldquant-orchestrator/wqo-cli).
Listing and ranking are managed by skills.sh; a local-path test alone does not
prove a public listing.
See the [skills CLI documentation](https://github.com/vercel-labs/skills) and
[skills.sh listing FAQ](https://skills.sh/docs/faq).
