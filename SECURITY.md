# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Report it privately through GitHub's
[security advisory form](https://github.com/aaditya-v-more/worldquant-orchestrator/security/advisories/new),
which is visible only to the maintainers until a fix is published.

Include what you did, what happened, and what you expected. A proof of concept
helps; a live exploit against someone else's account does not — please do not
test against any BRAIN account but your own.

Expect an acknowledgement within a week.

## What counts here

This tool holds a BRAIN session cookie on disk and can take irreversible
actions against a live account. The classes of bug that matter most:

- **Credential or session exposure** — anything that writes, logs, echoes or
  transmits `~/.brain_credentials.json` or the cached session cookie, including
  into an error message, a debug dump or a committed file.
- **Submission without confirmation** — any path that reaches a live submit
  without an explicit `--confirm`. Submission is irreversible and consumes a
  daily quota.
- **Budget or slot accounting that undercounts**, letting the tool exceed a cap
  it believes it is respecting.
- **Leaking one user's alphas to another** — expressions and statistics are
  contributor IP.
- **Bypassing the Persona biometric check.**

## What does not

- Rate limiting or 429s from BRAIN. That is the platform throttling you, and
  the tool is designed to back off and learn the limit.
- The `403` responses on `/users/self/consultant` and
  `/alphas/{id}/correlations/prod`. Those are account-level gates, not bugs.
- Anything requiring an attacker to already have your credentials file or
  local shell.

## Your own account

If you believe your BRAIN credentials were exposed, change your password on
[the platform](https://platform.worldquantbrain.com) first, then delete the
cached session with `wqo auth logout`. Tell us afterwards — securing the
account comes first.

## Implemented safeguards and limits

See [the safety controls](docs/safety.md) for submission reservations, uncertain
outcomes, local quota windows, shared simulation slots and output redaction.
