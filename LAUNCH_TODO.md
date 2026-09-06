# Launch to-do list

Work top to bottom. First ship an installable WQO package, then portable skills that install the CLI when needed. Complete the remaining launch checks before promotion; MCP remains optional.

Reviewed baseline (2026-09-06): already public; MIT license, contributor/security guides, issue templates, demo, topics, CI, secret scanning and push protection exist. All 80 offline tests passed. No release or version tag exists yet. Posting rules and marketing claims from earlier drafts still need verification.

**1. Priority: publish WQO as an installable package**

- [x] Select `wqo` as the package, import and CLI name; the project is now published on PyPI.
- [x] Add `pyproject.toml`, the `wqo` entry point and `--version`, Python 3.12+ metadata, runtime/development dependency separation and verified runtime assets.
- [x] Move default state to `~/.local/share/wqo` (or `$XDG_DATA_HOME/wqo`); add `wqo state` and safe legacy migration. Existing local ledger migrated with the source preserved; installed commands work outside the repo.
- [x] Document isolated `uv tool install --python 3.12 wqo`, pipx fallback, prerequisites, version checks and upgrades in `docs/installation.md`; verify uv tool installation using the built wheel.
- [x] Build and inspect wheel/sdist; verify each in a clean environment outside the repo. 139 offline tests pass; strict metadata checks and archive-content checks pass. Add Linux/macOS package CI.
- [x] Publish [`wqo==0.1.0`](https://pypi.org/project/wqo/0.1.0/) to PyPI (2026-09-07). Verify both uploaded file hashes and a fresh `uv tool install` from PyPI, including CLI/library checks outside the repo. Remove the README release-pending note.

**2. Priority: portable skills with automatic CLI setup**

- [x] Restructure `.claude/skills/` into a core `wqo-cli` skill plus focused companion skills where useful (auth, data, simulation/mining, analysis, alpha management, submission and account workflows).
- [x] Use `/Users/aaditya/Developer/temp/.agents/skills/playwright-cli/SKILL.md` as the local reference for command-oriented documentation, installation detection and fallback setup; adapt the pattern to WQO's Python package.
- [x] Make the core skill detect a usable `wqo` installation and automatically install the published package when absent, then verify it before running commands. Handle missing prerequisites and incompatible versions clearly.
- [x] Ensure every companion skill works when installed alone: include or reliably invoke the shared CLI setup flow without assuming the core skill is already installed. Preserve credential privacy, Persona handoff, quota limits and explicit per-alpha submission approval.
- [x] Package skills and their references in a standard discoverable layout, with valid `SKILL.md` metadata and no dependencies on repo-root paths or hard-coded agent directories/symlinks.
- [x] Support and document `npx skills add aaditya-v-more/worldquant-orchestrator` and selection of `wqo-cli` or companion skills. Use the installer's agent selection for supported agents; users must not need to manually clone the repo. See [the skills CLI documentation](https://github.com/vercel-labs/skills).
- [x] Test a single companion installed via `npx skills` in an isolated subfolder: automatic project-local CLI installation, help/version commands and reuse all pass without auth or simulation. Nine skills validate; all 143 offline tests pass. Local installs target Codex, Claude Code, Copilot and Qoder; installed copies are gitignored.
- [x] Publish the skill sources to GitHub and verify a repository-source `npx skills` install locally. All nine skills.sh pages return their matching skill titles (2026-09-07); README links to the [core skill](https://skills.sh/aaditya-v-more/worldquant-orchestrator/wqo-cli). CI passes on Linux/macOS; no global skill or CLI installation was performed.


**3. Fix safety and privacy issues**

- [x] Enable and verify GitHub private vulnerability reporting for the channel linked in `SECURITY.md`.
- [x] Finish privacy clearance: all 27 reachable commits scanned with no recognizable secrets; historical personal details and six demo versions remain. The owner confirmed the current demo is entirely synthetic; it is retained and labeled. Older media review and personal-data history cleanup remain; see `PUBLICATION_REVIEW.local.md` (ignored).
- [x] Make raw `api` read-only; dedicated submission retains confirmation, gate and quota checks.
- [x] Redact secret fields recursively; omit unstructured responses/error bodies and sensitive HTTP diagnostics. Restrict requests to the BRAIN API origin and create session files privately.
- [x] Reserve submission quota atomically, retain pending/uncertain outcomes across restarts, block duplicate submissions and disable automatic write retries.
- [x] Use Eastern local days plus a conservative rolling 24-hour submission cap; share simulation slots and atomic budgets across processes. 132 offline tests pass, including 52 new safety regressions. Platform reset timing remains unverified; see `docs/safety.md`.

**4. Correct documentation and onboarding**

- [x] Implement `account snapshot` with dated, minimal account data, private atomic writes and overwrite protection; add four offline regressions. Verify existing shared slot queue/three-process tests. 147 offline tests, a live read-only account snapshot smoke test and package build/metadata checks pass (2026-09-07). Snapshot is published in WQO 0.1.1; see section 5.
- [x] Fix the missing-PDF reference in `docs/alpha-research.md`; check README references too. Add traceable author/date/source links without redistributing restricted material.
- [x] Correct the misidentified *101 Formulaic Alphas* #4 example against [the original paper, Appendix A](https://arxiv.org/pdf/1601.00991). Remove unverified compensation figures, correct fitness arithmetic and local threshold boundaries, and qualify research hypotheses. Unverified private-platform definitions are explicitly labeled.
- [x] Remove any “sanctioned integration” claims; retain the non-affiliation notice.
- [x] Clarify that expressions are transmitted to BRAIN. Date account-specific observations and distinguish backtest results from guaranteed future performance.
- [x] Make the quick start package/skill-first with no manual clone required: installation prerequisites, credential setup that avoids passwords in shell history, Persona handoff and a synthetic example. Keep clone/venv instructions for contributors.

**5. Prepare the first release**

- [x] Protect `main` with all five GitHub Actions checks, strict up-to-date enforcement including administrators, and blocked force pushes/deletion. Enable and verify Dependabot alerts and security updates (2026-09-07).
- [x] Publish [WQO 0.1.1 on PyPI](https://pypi.org/project/wqo/0.1.1/) and the matching [v0.1.1 GitHub release](https://github.com/aaditya-v-more/worldquant-orchestrator/releases/tag/v0.1.1) with [changelog](CHANGELOG.md), supported environments/account limitations, known issues, wheel/sdist and SHA256 checksums (2026-09-07). All 147 offline tests and all five [release CI checks](https://github.com/aaditya-v-more/worldquant-orchestrator/actions/runs/34056604544) pass. Both public archive hashes match; a fresh PyPI install passes outside the repo. Project-local CLI/skills refreshed; no global installation.

**6. Prepare launch material**

- [ ] Check/set the GitHub social preview image and verify the rendered link card. Prepare a shareable demo clip/still with cleared content.
- [ ] Draft LinkedIn and X posts around a concrete research workflow and its constraints; include a clear repository link and demo.
- [ ] Fact-check drafts: development timeline, daily-use claims, API coverage, tier limits, safety guarantees and comparisons with `wqb`. Avoid unverified claims about link suppression, ideal posting hours or having only one launch opportunity.
- [ ] Write an API-mapping article for a personal blog or DEV Community; explain observations, limits and design decisions with sources. Use it where a substantive article fits better than a repository link.
- [ ] Check current rules, self-promotion policies, required flair/templates and account eligibility for every community before posting. Prepare distinct, transparent posts that identify you as the author.

**7. Publicize gradually and follow up**

- [ ] Publish on LinkedIn; post to the BRAIN community forum only after checking its rules and applicable terms.
- [ ] Prioritize Reddit candidates by fit: `r/algotrading` (technical write-up), `r/Python` (current showcase format), and `r/ClaudeAI` / `r/ClaudeCode` (agent skills). Consider `r/quant` only if its rules/moderators permit it.
- [ ] Consider secondary Reddit candidates: `r/opensource`, `r/SideProject`, `r/madeinpython`, `r/coolgithubprojects`; verify each is active and permits the post. Consider `r/programming` for the article. Skip unrelated investing/trading-entertainment communities.
- [ ] Consider Show HN after checking its guidelines; provide a useful demo and explain the design constraints. Publish the X thread with the clip.
- [ ] Check inclusion criteria and propose additions to [awesome-quant](https://github.com/wilsonfreitas/awesome-quant) and a suitable, active awesome-systematic-trading list.
- [ ] Space tailored posts over roughly 1–2 weeks, answer comments, fix onboarding problems and record which channels produce useful feedback. Respect removals and moderator decisions.
- [ ] Later, evaluate an MCP server as a separate feature with authentication, quota and safety tests. Keep live submission unexposed or explicitly gated; approach `r/mcp` and relevant registries only once an actual server ships.
