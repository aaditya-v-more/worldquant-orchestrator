# Synthetic research walkthrough

This is an illustrative transcript, not a live account recording. `DEMO_ALPHA`
is an invented identifier; the expression is a generic example. The outcome
below is invented and does not claim backtest performance or submission eligibility.

```text
1. Discover a field
   python -m wqo data fields --dataset pv1 --search close

2. Test a generic expression (a real invocation would consume simulation quota)
   python -m wqo sim run --code 'rank(close)'
   Illustrative outcome: backtest completes; gate fails.

3. Review the result
   python -m wqo gate DEMO_ALPHA
   Illustrative outcome: not eligible for submission.

4. Stop at the human checkpoint
   python -m wqo submit DEMO_ALPHA
   Without --confirm, the command prints a report and refuses to submit (exit 4).
```

Run commands from the repository root through `.venv/bin/python -m wqo` after
setting up your own account. Do not run commands containing `DEMO_ALPHA` against
BRAIN; it is a placeholder. Most research candidates fail the gate.
