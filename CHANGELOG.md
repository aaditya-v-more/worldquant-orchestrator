# Changelog

## 0.1.1 — 2026-09-07

First GitHub release, following the initial 0.1.0 package on PyPI.

### Added

- `wqo account snapshot` writes dated `ACCOUNT.local.md` notes with account ID,
  level, competition progress, learned concurrency and local quota usage.
  It makes account reads only, omits unnecessary profile fields, writes
  atomically with private permissions, and preserves existing notes unless
  `--overwrite` is supplied. Symlink destinations are refused.
- Four offline regressions cover snapshot privacy, overwrite protection,
  atomic refresh and failure handling. Installed-package checks now exercise
  snapshot command discovery and missing authentication.

### Corrected

- Package/skill-first onboarding, credential setup outside shell history,
  Persona handoff, contributor instructions and a synthetic backtest example.
- Alpha #4 attribution, fitness arithmetic and local threshold boundaries.
  Research suggestions and account observations now state their limits;
  unverified compensation and endorsement claims were removed.
- Portable skills carry the corrected documentation and install 0.1.1 when
  WQO is missing. An existing compatible 0.1.0 CLI is reused; upgrade it to use
  `account snapshot`.

### Supported environments and account limitations

- Python 3.12+ on macOS and Linux. CI tests Python 3.12/3.13 on Linux and builds
  and installs both distribution formats on Linux/macOS. Windows simulation
  support is unavailable.
- Live commands require the user's BRAIN account. Persona verification, when
  requested, must be completed by the user. Operator access, concurrency and
  endpoint permissions vary by account and time.
- The default ledger remains `~/.local/share/wqo` (or `$XDG_DATA_HOME/wqo`).
  Preserve it when upgrading; use `wqo state` to inspect the selected paths.

### Known limitations

- Local quotas do not include actions from the browser, another machine or a
  different ledger. The conservative submission window can outlast BRAIN's
  own reset; unresolved writes retain quota until investigated.
- Shared simulation slots coordinate processes using one ledger, not machines.
  An exited worker's remote simulation may still be running.
- Some account tiers cannot read production-correlation detail. Missing checks
  do not prove eligibility, and research backtests do not guarantee returns.
- Snapshot notes are private data even though secret fields and unnecessary
  profile details are omitted. Other projects must ignore `ACCOUNT.local.md`.
- The current demo is owner-confirmed synthetic. Historical commits retain
  personal details/media; this release does not rewrite repository history.

### Validation

- 147 offline tests pass locally, including snapshot and process-contention tests.
- Read-only snapshot smoke test succeeded using the configured account, with
  temporary output removed and existing notes preserved. No simulation or
  submission quota was used for that check.
- Release CI verifies tests, tracked-file checks, distribution metadata/content,
  and clean installation outside the checkout.

## 0.1.0 — 2026-09-07

- Initial PyPI package with the `wqo` CLI, portable project-local agent skills,
  persistent state and migration, read-only raw API, and guarded submission.
