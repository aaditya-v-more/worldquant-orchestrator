---
name: wqo-analyze
description: Inspect WorldQuant BRAIN alpha metrics, correlations and gate reports with WQO. Use to diagnose failed checks or assess submission eligibility without submitting.
---

# WorldQuant BRAIN — alpha analysis

## Setup

Read [setup and operational boundaries](references/runtime.md) before running
commands. Use the bundled `scripts/wqo.sh` runner for every `wqo` command below;
it installs the CLI locally when missing. This skill works without other skills
or a source checkout.

## Full pre-submission report

```bash
wqo gate <alpha_id>
```

This is the one command that answers "is this submittable?". It is **read-only** —
it never submits. It runs BRAIN's own `/check` endpoint plus local thresholds and
prints a per-criterion PASS/FAIL table. Exit code 0 means clean, 1 means blocked.

Add `--json` for structured output, `--no-correlations` to skip the (slow)
correlation calls.

The header carries BRAIN's own grade when the record has one:

```
Alpha DEMO_ALPHA  [grade EXCELLENT]
```

Grade never affects the verdict. It runs `INFERIOR` → `AVERAGE` → `GOOD` →
`EXCELLENT` → `SPECTACULAR`, and a `SPECTACULAR` alpha still gets blocked by a
failing check. Report it alongside the outcome; do not present it as one.

## Individual pieces

```bash
wqo alpha get <alpha_id>            # full record
wqo alpha pnl <alpha_id>            # PnL series
wqo alpha yearly <alpha_id>         # per-year stats
wqo alpha corr <alpha_id>           # vs. your own alphas
wqo alpha corr <alpha_id> --prod    # vs. production alphas
```

Correlation output includes a `max` field — that's the number the gate compares
against the 0.70 limit.

## What the checks mean

| Check | Reading |
|---|---|
| `LOW_SHARPE` | IS Sharpe under the required minimum |
| `LOW_FITNESS` | fitness under minimum; inspect returns, Sharpe and turnover |
| `LOW_TURNOVER` / `HIGH_TURNOVER` | outside the acceptable trading band |
| `CONCENTRATED_WEIGHT` | concentration check failed; inspect weights and coverage |
| `LOW_SUB_UNIVERSE_SHARPE` | failed the platform’s sub-universe comparison |
| `SELF_CORRELATION` | too close to an alpha you already submitted |
| `MATCHES_COMPETITION` | inspect the returned competition check and its message |
| `UNITS` / `IS_LADDER_SHARPE` | unit mismatch or unstable across sub-periods |

## Local gate defaults

Reviewed against WQO 0.1.0 on 2026-09-07. These are local defaults, not universal
platform requirements; inspect BRAIN's actual returned checks and limits.

| Metric | Local rule |
|---|---|
| Sharpe | Absolute value ≥ 1.25 |
| Fitness | Absolute value ≥ 1.0 |
| Turnover | 1%–70%, inclusive |
| Drawdown | Absolute value ≤ 10%, skipped if missing |
| Self/production correlation | < 0.70 when available, skipped if missing |
| Weight concentration | BRAIN check; no separate local 10% threshold |

Missing Sharpe, fitness or turnover fails. The gate does not invert negative
expressions automatically. The self-correlation diagnostic mentions a configured
10% Sharpe-improvement exemption, but WQO cannot evaluate it and still fails that
local criterion. Do not promise that the platform will apply an exemption.
Skipped checks do not establish eligibility, and backtests do not guarantee
future performance.

## Interpreting fitness

The earlier research notes use this working formula:

```
Fitness = Sharpe × sqrt( |Returns| / max(Turnover, 0.125) )
```

A public primary BRAIN definition was not independently verified in this review;
confirm it in signed-in Learn documentation. WQO uses BRAIN's reported fitness.
Under this formula, Sharpe 1.26 and turnover 0.34 need absolute returns
`0.34 / 1.26² ≈ 0.2142` for fitness 1.0, with decimal units. Lowering turnover
alone below 0.125 does not reduce the denominator; parameter changes can also
change returns and Sharpe.

## Investigating failures

- **Low fitness or high turnover:** inspect returns, signal update frequency,
  smoothing and decay. No parameter change guarantees improvement.
- **Concentrated weight:** inspect coverage, stale values and outliers before
  testing backfill, neutralization or truncation changes.
- **Low sub-universe Sharpe:** compare the relevant universes and returned check
  definition; this does not by itself prove a large-cap-only signal.
- **Self-correlation:** investigate whether the hypothesis adds distinct
  information. Changing a field, wrapper or region is not a guaranteed fix.
- **Low Sharpe:** examine the rationale, sign and stability across periods.

Re-simulate approved research changes within the existing budget, record failed
candidates and re-run the gate. Repeated tuning on held-out data creates leakage.

Companion skill names above are optional guidance. If none are installed, use
the equivalent `wqo` command through this skill's bundled runner.
