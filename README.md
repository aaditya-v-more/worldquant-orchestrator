<div align="center">

<img src="docs/media/logo.svg" width="132" alt="worldquant-orchestrator logo">

<h1>worldquant-orchestrator</h1>

<p>
  <b>End-to-end control of <a href="https://platform.worldquantbrain.com">WorldQuant BRAIN</a> from any coding agent.</b><br>
  Data discovery → alpha generation → backtesting → analysis → submission,<br>
  driven through BRAIN's official REST API rather than the web UI.
</p>

<p>
  <a href="https://skills.sh/aaditya-v-more/worldquant-orchestrator/wqo-cli"><img alt="Agent skills on skills.sh" src="https://img.shields.io/badge/skills.sh-9%20skills-5B8DEF?style=for-the-badge"></a>
  <a href="https://github.com/aaditya-v-more/worldquant-orchestrator/actions/workflows/tests.yml"><img alt="Tests" src="https://img.shields.io/github/actions/workflow/status/aaditya-v-more/worldquant-orchestrator/tests.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=tests"></a>
  <a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/Licence-MIT-22D3EE?style=for-the-badge"></a>
  <a href="https://github.com/aaditya-v-more/worldquant-orchestrator/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/aaditya-v-more/worldquant-orchestrator?style=for-the-badge&color=A78BFA&logo=github&logoColor=white"></a>
</p>

<p>
  <a href="https://platform.worldquantbrain.com"><img alt="WorldQuant BRAIN" src="https://img.shields.io/badge/WorldQuant-BRAIN-0A2540?style=for-the-badge"></a>
  <img alt="Claude Code skills" src="https://img.shields.io/badge/Claude%20Code-9%20skills-D97757?style=for-the-badge&logo=anthropic&logoColor=white">
  <img alt="GitHub Copilot skills" src="https://img.shields.io/badge/Copilot-9%20skills-24292E?style=for-the-badge&logo=githubcopilot&logoColor=white">
  <img alt="Qoder skills" src="https://img.shields.io/badge/Qoder-9%20skills-5B8DEF?style=for-the-badge">
</p>

<p>
  <a href="#-quick-start"><b>Quick start</b></a> ·
  <a href="https://skills.sh/aaditya-v-more/worldquant-orchestrator/wqo-cli"><b>Install skills on skills.sh</b></a> ·
  <a href="#-the-loop"><b>The loop</b></a> ·
  <a href="#-safety-model"><b>Safety</b></a> ·
  <a href="#-reference"><b>Docs</b></a>
</p>

<br>

<a href="docs/media/demo.mp4"><img src="docs/media/demo.gif" width="760" alt="25-second synthetic preview of WQO skills in a VS Code-style agent chat: user prompt, research results and explicit approval; click for the full video"></a>

<p><sub><b>Synthetic agent-chat demonstration · 25-second preview.</b> All expressions, identifiers and results shown are illustrative;<br>this is not a live account recording or evidence of investment performance.<br>
<a href="docs/media/demo.mp4">Watch the full 58-second skills demo →</a> · <a href="docs/demo.md">Synthetic walkthrough →</a></sub></p>

</div>

---

## ✦ WQO skills

Give your coding agent the skills to research on WorldQuant BRAIN. Describe an
idea in chat, and the agent can find data, build expressions, run backtests,
compare candidates and explain the submission checks.

The core **`wqo-cli` skill** handles setup and the full research workflow. Eight
companion skills add guidance for specific tasks. The skills install the WQO
CLI automatically when it is missing; you do not need to install WQO separately
or clone this repository.

---

## ⚡ Quick start

From the project where you want to use WQO, install the core skill:

```bash
npx skills add aaditya-v-more/worldquant-orchestrator --skill wqo-cli
```

Choose your coding agent in the installer. Keep installation project-local by
omitting `--global`. To install the core and all eight companions together:

```bash
npx skills add aaditya-v-more/worldquant-orchestrator --skill '*'
```

Use macOS or Linux with [Node.js/npm](https://nodejs.org/en/download) and either
[uv](https://docs.astral.sh/uv/getting-started/installation/) or Python 3.12+
available. The skill handles WQO installation in your project automatically.

Open your agent chat in that project and ask:

> Use the wqo-cli skill to set up WQO and help me connect my BRAIN account.

You need your own [BRAIN account](https://platform.worldquantbrain.com). The
skill guides you through private credential setup and pauses for you to complete
Persona verification if required. Keep your password out of chat.

Then describe your research:

> Build an alpha from analyst EPS estimates. Backtest it on USA TOP3000,
> compare up to five variants, and tell me whether any clear the submission
> checks. Do not submit anything.

The agent uses the available skills to carry out the request and report the
results, including failed candidates and unavailable checks. Live backtests use
your BRAIN simulation quota. Submission requires your explicit approval for the
specific alpha.

Browse [the core skill on skills.sh](https://skills.sh/aaditya-v-more/worldquant-orchestrator/wqo-cli)
or see [skill setup and troubleshooting](docs/skills.md).

---

## 🔄 The loop

```mermaid
flowchart LR
    A(["🔑 auth"]) --> B(["🗂️ data"])
    B --> C(["⛏️ mine"])
    C --> D(["📊 analyze"])
    D --> E{"🚦 gate"}
    E -->|blocked| C
    E -->|clean| F(["🧑 your call"])
    F --> G(["🚀 submit"])

    classDef step fill:#0D1425,stroke:#5B8DEF,stroke-width:2px,color:#E6EDF3
    classDef check fill:#0D1425,stroke:#A78BFA,stroke-width:2px,color:#E6EDF3
    classDef human fill:#0D1425,stroke:#34D399,stroke-width:2px,color:#E6EDF3
    class A,B,C,D,G step
    class E check
    class F human
```

| Stage | Skill | What it does |
|---|---|---|
| 🧭 | [`wqo-cli`](skills/wqo-cli) | Automatic setup and the full research workflow |
| 🔑 | [`wqo-auth`](skills/wqo-auth) | Session, quotas, level, biometric handoff |
| 🗂️ | [`wqo-data`](skills/wqo-data) | Datasets, datafields, operators — cached 7 days |
| ⛏️ | [`wqo-mine`](skills/wqo-mine) | Generate candidates, backtest in batch, rank survivors |
| 🔬 | [`wqo-simulate`](skills/wqo-simulate) | One expression, or a sweep over settings and fields |
| 📊 | [`wqo-analyze`](skills/wqo-analyze) | IS stats, PnL, yearly breakdown, correlations, checks |
| 🏷️ | [`wqo-alphas`](skills/wqo-alphas) | Filter and organize the library — names, tags, colours |
| 🚀 | [`wqo-submit`](skills/wqo-submit) | Full check report, then waits for your explicit yes |
| 🏆 | [`wqo-account`](skills/wqo-account) | Rank, competitions, teams, events, standing |

---

## 🔒 Safety model

- **You approve submission for each alpha.** A research request or passing check
  report is not permission to submit. The submission skill pauses for your
  explicit yes.
- **You handle credentials and identity verification.** The agent guides setup
  and waits for you to complete any Persona check.
- **Research stays within your budget.** The skills respect account limits and
  stop when quota is exhausted.
- **Results include the failures.** The agent reports rejected candidates and
  unavailable checks alongside promising results. Backtests do not guarantee
  future performance.

Submission consumes quota and permanently affects future self-correlation.
See [safety controls and limits](docs/safety.md) for the underlying safeguards
and how to handle uncertain outcomes.

---

## 📚 Reference

Installed skills include their own setup and workflow instructions. For work
on this repository, see [`AGENTS.md`](AGENTS.md) and [Contributing](CONTRIBUTING.md).

| Document | Contents |
|---|---|
| [Portable skills](docs/skills.md) | Installation, automatic CLI setup and troubleshooting |
| [CLI reference](docs/cli-reference.md) | Commands, simulation settings, grades and rate limiting for direct CLI use |
| [Manual CLI installation](docs/installation.md) | Optional standalone CLI setup, upgrades and ledger migration |
| [`docs/fastexpr.md`](docs/fastexpr.md) | FASTEXPR syntax constraints, the operator set actually available at this account level, and the `pv1` field list |
| [`docs/alpha-research.md`](docs/alpha-research.md) | Local gate rules, fitness arithmetic, sourced examples and research limitations |
| [`docs/api-map.md`](docs/api-map.md) | Every website tab mapped to its endpoint, plus what is *not* available |

The [research reference](docs/alpha-research.md) distinguishes local defaults
from platform checks, links the original publications and labels unverified
assumptions. No source PDF is bundled with this repository.

> [!CAUTION]
> There is **no leaderboard endpoint**. `GET /alphas` is `405` and
> `/leaderboards` is `404`: you can read your own rank, never other people's
> alphas. This is deliberate — alphas are contributor IP.

<details>
<summary><b>📁 Repository layout</b></summary>

<br>

```
docs/
  alpha-research.md   distilled research reference
  api-map.md          tab -> endpoint map, and what is unavailable
  fastexpr.md         expression syntax and operator availability
wqo/
  endpoints.py    API URLs
  config.py       paths, pacing, budgets, gate thresholds
  session.py      authenticated session, cookie persistence, Persona handoff
  pacing.py       interval throttle, Retry-After, backoff
  store.py        SQLite ledger (audit trail + budget accounting)
  catalog.py      datasets / datafields / operators, cached
  simulate.py     submit, poll, normalize; adaptive slot manager
  alphas.py       records, PnL, yearly stats, correlations, properties
  gate.py         local thresholds + BRAIN checks -> PASS/FAIL report
  submit.py       confirmation-gated submission
  mining/         templates, candidate generation, ranking
  account.py      competitions, standing, team, learn, notifications
  __main__.py     CLI
```

</details>

---

<div align="center">

**[Contributing](CONTRIBUTING.md)** · **[Code of conduct](CODE_OF_CONDUCT.md)** · **[Security](SECURITY.md)** · **[Licence](LICENSE)**

<sub>MIT licensed. Not affiliated with or endorsed by WorldQuant.<br>
Alpha expressions are sent to BRAIN for simulation; local ledgers and account statistics should stay out of Git — see <a href="CONTRIBUTING.md">CONTRIBUTING.md</a>.</sub>

<br>

<a href="#top">↑ Back to top</a>

</div>
