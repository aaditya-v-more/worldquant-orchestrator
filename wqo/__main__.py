"""Command line interface — this is what the Claude skills invoke.

Everything prints JSON to stdout unless noted, so output can be parsed
directly. Human-facing reports (``gate``, ``submit``) also render a table
unless ``--json`` is passed.

Exit codes:
    0  success
    1  generic error
    2  authentication required / biometric check pending
    3  daily budget exhausted
    4  submission refused (unconfirmed or gate not clean)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from . import account as account_mod
from . import alphas as alphas_mod
from . import config, endpoints, mining, submit as submit_mod
from .catalog import Catalog
from .session import ApiError, AuthError, BiometricRequired, BrainSession
from .simulate import (
    SimJob,
    SlotManager,
    build_settings,
    normalize_test_period,
    simulate_many,
    simulate_one,
)
from .store import BudgetExceeded, Ledger

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_AUTH = 2
EXIT_BUDGET = 3
EXIT_REFUSED = 4


def emit(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def _session(args, *, authenticate: bool = True) -> BrainSession:
    session = BrainSession(verbose=getattr(args, "verbose", False))
    if authenticate:
        session.ensure_auth()
    return session


def _ledger() -> Ledger:
    config.ensure_data_dir()
    return Ledger()


def _settings_from(args) -> dict:
    return build_settings(
        region=args.region,
        delay=args.delay,
        universe=args.universe,
        neutralization=args.neutralization,
        decay=args.decay,
        truncation=args.truncation,
        instrumentType=args.instrument_type,
        pasteurization=args.pasteurization,
        nanHandling=args.nan_handling,
        unitHandling=args.unit_handling,
        testPeriod=normalize_test_period(args.test_period),
    )


# --------------------------------------------------------------------------
# auth
# --------------------------------------------------------------------------


def cmd_auth(args) -> int:
    session = BrainSession(verbose=args.verbose)
    if args.auth_command == "logout":
        session.logout()
        emit({"status": "logged out"})
        return EXIT_OK

    if args.auth_command == "persona":
        payload = session.complete_persona()
        emit({"status": "verified", "user": payload.get("user")})
        return EXIT_OK

    if args.auth_command == "login":
        payload = session.authenticate()
        emit({"status": "authenticated", "user": payload.get("user")})
        return EXIT_OK

    # status
    session.ensure_auth()
    me = session.whoami()
    with _ledger() as ledger:
        learned = ledger.get("learned_concurrency", config.DEFAULT_CONCURRENCY)
        emit(
            {
                "authenticated": True,
                "user": me,
                "concurrency": learned,
                "simulations_today": ledger.simulations_today(),
                "simulation_budget": config.BUDGET.simulations_per_day,
                "submissions_today": ledger.submissions_today(),
                "submission_budget": config.BUDGET.submissions_per_day,
                "credentials_path": str(config.CREDENTIALS_PATH),
            }
        )
    return EXIT_OK


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------


def cmd_data(args) -> int:
    session = _session(args)
    with Catalog(session) as catalog:
        if args.data_command == "datasets":
            items = catalog.datasets(
                region=args.region,
                delay=args.delay,
                universe=args.universe,
                search=args.search,
                refresh=args.refresh,
            )
            emit(
                [
                    {
                        "id": d.get("id"),
                        "name": d.get("name"),
                        "category": (d.get("category") or {}).get("name"),
                        "fieldCount": d.get("fieldCount"),
                        "alphaCount": d.get("alphaCount"),
                        "valueScore": d.get("valueScore"),
                    }
                    for d in items
                ]
                if not args.raw
                else items
            )
        elif args.data_command == "fields":
            items = catalog.fields(
                dataset_id=args.dataset,
                region=args.region,
                delay=args.delay,
                universe=args.universe,
                search=args.search,
                field_type=args.type,
                refresh=args.refresh,
            )
            if args.limit:
                items = items[: args.limit]
            emit(
                [
                    {
                        "id": f.get("id"),
                        "description": f.get("description"),
                        "type": f.get("type"),
                        "coverage": f.get("coverage"),
                        "userCount": f.get("userCount"),
                        "alphaCount": f.get("alphaCount"),
                    }
                    for f in items
                ]
                if not args.raw
                else items
            )
        else:  # operators
            items = catalog.operators(refresh=args.refresh)
            emit(
                [
                    {
                        "name": o.get("name"),
                        "category": o.get("category"),
                        "definition": o.get("definition"),
                        "description": o.get("description"),
                    }
                    for o in items
                ]
                if not args.raw
                else items
            )
    return EXIT_OK


# --------------------------------------------------------------------------
# simulate
# --------------------------------------------------------------------------


def cmd_sim(args) -> int:
    if args.sim_command == "recent":
        with _ledger() as ledger:
            emit([dict(row) for row in ledger.recent_simulations(args.limit)])
        return EXIT_OK

    session = _session(args)
    with _ledger() as ledger:
        if args.sim_command == "run":
            job = SimJob(code=args.code, settings=_settings_from(args), label=args.label)
            result = simulate_one(
                session,
                job,
                ledger=ledger,
                slots=SlotManager(ledger),
                reuse_cached=not args.no_cache,
                on_progress=(
                    (lambda p: print(f"[wqo] progress {p:.0%}", file=sys.stderr))
                    if args.verbose
                    else None
                ),
            )
            emit(result.summary())
            return EXIT_OK if result.ok else EXIT_ERROR

        # batch
        spec = json.loads(sys.stdin.read() if args.file == "-" else open(args.file).read())
        base = _settings_from(args)
        jobs = []
        for entry in spec:
            if isinstance(entry, str):
                jobs.append(SimJob(code=entry, settings=base))
            else:
                settings = dict(base, **(entry.get("settings") or {}))
                jobs.append(
                    SimJob(
                        code=entry["code"], settings=settings, label=entry.get("label")
                    )
                )
        results = simulate_many(
            session,
            jobs,
            ledger=ledger,
            slots=SlotManager(ledger),
            reuse_cached=not args.no_cache,
            on_result=(
                (lambda r: print(f"[wqo] done: {r.label or r.code[:60]}", file=sys.stderr))
                if args.verbose
                else None
            ),
        )
        emit([r.summary() for r in results])
    return EXIT_OK


# --------------------------------------------------------------------------
# alpha
# --------------------------------------------------------------------------


def cmd_alpha(args) -> int:
    session = _session(args)
    command = args.alpha_command

    if command == "get":
        emit(alphas_mod.get(session, args.alpha_id))
    elif command == "list":
        emit(
            list(
                alphas_mod.search(
                    session,
                    status=args.status,
                    region=args.region,
                    universe=args.universe,
                    delay=args.delay,
                    min_sharpe=args.min_sharpe,
                    min_fitness=args.min_fitness,
                    color=args.color,
                    tag=args.tag,
                    grade=args.grade,
                    order=args.order,
                    limit=args.limit,
                )
            )
        )
    elif command == "pnl":
        emit(alphas_mod.pnl(session, args.alpha_id))
    elif command == "yearly":
        emit(alphas_mod.yearly_stats(session, args.alpha_id))
    elif command == "corr":
        kind = "prod" if args.prod else "self"
        payload = alphas_mod.correlation(session, args.alpha_id, kind)
        emit({"kind": kind, "max": alphas_mod.max_correlation(payload), "data": payload})
    elif command == "tag":
        emit(
            alphas_mod.patch(
                session,
                args.alpha_id,
                name=args.name,
                color=args.color,
                tags=args.tags.split(",") if args.tags else None,
                category=args.category,
                description=args.description,
                favorite=args.favorite,
                hidden=args.hidden,
            )
        )
    return EXIT_OK


# --------------------------------------------------------------------------
# gate / submit
# --------------------------------------------------------------------------


def cmd_gate(args) -> int:
    session = _session(args)
    prep = submit_mod.prepare(
        session,
        args.alpha_id,
        with_correlations=not args.no_correlations,
        with_brain_check=not args.no_check,
    )
    if args.json:
        emit(prep.to_dict())
    else:
        print(prep.report.render())
        print(f"  url: {endpoints.alpha_url(args.alpha_id)}")
    return EXIT_OK if prep.report.passed else EXIT_ERROR


def cmd_submit(args) -> int:
    session = _session(args)
    with _ledger() as ledger:
        prep = submit_mod.prepare(session, args.alpha_id)
        if not args.confirm:
            if args.json:
                emit(
                    dict(
                        prep.to_dict(),
                        submitted=False,
                        reason="confirmation required — re-run with --confirm",
                    )
                )
            else:
                print(prep.report.render())
                print(f"  url: {endpoints.alpha_url(args.alpha_id)}")
                print()
                print(
                    "NOT SUBMITTED. Submission is irreversible and uses daily quota.\n"
                    f"To submit, re-run with --confirm:\n"
                    f"  python -m wqo submit {args.alpha_id} --confirm"
                )
            return EXIT_REFUSED

        result = submit_mod.submit(
            session,
            args.alpha_id,
            confirmed=True,
            force=args.force,
            ledger=ledger,
            preparation=prep,
        )
        emit(result)
    return EXIT_OK


# --------------------------------------------------------------------------
# mine
# --------------------------------------------------------------------------


def cmd_mine(args) -> int:
    session = _session(args)
    # Only an explicit --neutralizations turns mining into a sweep. Left off,
    # variants stays None so each template runs under its own regime.
    variants = (
        tuple({"neutralization": n} for n in args.neutralizations.split(","))
        if args.neutralizations
        else None
    )
    # Knobs the user pinned explicitly override the regime; the rest are left
    # to whichever template is generating the expression.
    overrides = {
        key: value
        for key, value in (
            ("decay", args.decay),
            ("truncation", args.truncation),
            ("testPeriod", normalize_test_period(args.test_period)),
        )
        if value is not None
    }
    spec = mining.GenerationSpec(
        region=args.region,
        delay=args.delay,
        universe=args.universe,
        dataset_id=args.dataset,
        field_search=args.search,
        variants=variants,
        overrides=overrides,
        template_names=tuple(args.templates.split(",")) if args.templates else None,
        max_fields=args.max_fields,
        budget=args.budget,
        seed=args.seed,
    )
    with _ledger() as ledger, Catalog(session) as catalog:
        if args.dry_run:
            jobs = mining.generate(catalog, spec)
            emit([{"code": j.code, "label": j.label} for j in jobs])
            return EXIT_OK
        summary = mining.run(
            session,
            spec,
            ledger=ledger,
            catalog=catalog,
            shortlist_size=args.shortlist,
            on_result=(
                (lambda r: print(f"[wqo] {r.status}: {r.label}", file=sys.stderr))
                if args.verbose
                else None
            ),
        )
        emit(summary)
    return EXIT_OK


# --------------------------------------------------------------------------
# account: competitions, standing, team, learn, notifications
# --------------------------------------------------------------------------


def cmd_account(args) -> int:
    session = _session(args)
    command = args.account_command

    if command == "status":
        emit(account_mod.standing(session))
    elif command == "competitions":
        items = account_mod.competitions(session, mine=args.mine)
        emit(
            items
            if args.raw
            else [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "status": c.get("status"),
                    "scoring": c.get("scoring"),
                    "teamBased": c.get("teamBased"),
                    "startDate": c.get("startDate"),
                    "endDate": c.get("endDate"),
                }
                for c in items
            ]
        )
    elif command == "competition":
        if args.alphas:
            emit(account_mod.competition_alphas(session, args.competition_id))
        elif args.agreement:
            emit(account_mod.competition_agreement(session, args.competition_id))
        else:
            emit(account_mod.competition(session, args.competition_id))
    elif command == "activity":
        emit(account_mod.activity_summary(session))
    elif command == "teams":
        emit(account_mod.teams(session))
    elif command == "events":
        emit(account_mod.events(session))
    elif command == "tutorials":
        emit(account_mod.tutorials(session))
    elif command == "messages":
        emit(account_mod.messages(session))
    elif command == "agreements":
        emit(account_mod.agreements(session))
    elif command == "probe":
        emit(account_mod.probe(session))
    return EXIT_OK


# --------------------------------------------------------------------------
# raw api / discovery
# --------------------------------------------------------------------------


def cmd_api(args) -> int:
    session = _session(args)
    kwargs: dict[str, Any] = {}
    if args.data:
        kwargs["json"] = json.loads(args.data)
    if args.query:
        kwargs["params"] = dict(pair.split("=", 1) for pair in args.query)
    response = session.request(args.method.upper(), args.path, **kwargs)
    body: Any
    try:
        body = response.json()
    except ValueError:
        body = response.text
    emit(
        {
            "status": response.status_code,
            "headers": dict(response.headers),
            "body": body,
        }
    )
    return EXIT_OK if response.status_code < 400 else EXIT_ERROR


def cmd_discover(args) -> int:
    """Probe for a machine-readable API spec behind authentication."""
    session = _session(args)
    found = {}
    for path in ("/openapi.json", "/v3/api-docs", "/swagger.json", "/docs"):
        try:
            response = session.request("GET", path)
        except ApiError as exc:
            found[path] = f"error: {exc}"
            continue
        if response.status_code < 400:
            try:
                found[path] = response.json()
            except ValueError:
                found[path] = response.text[:2000]
        else:
            found[path] = f"status {response.status_code}"
    emit(found)
    return EXIT_OK


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------


def add_settings_args(parser: argparse.ArgumentParser) -> None:
    d = config.DEFAULT_SETTINGS
    parser.add_argument("--region", default=d["region"])
    parser.add_argument("--delay", type=int, default=d["delay"])
    parser.add_argument("--universe", default=d["universe"])
    parser.add_argument("--neutralization", default=d["neutralization"])
    parser.add_argument("--decay", type=int, default=d["decay"])
    parser.add_argument("--truncation", type=float, default=d["truncation"])
    parser.add_argument("--instrument-type", default=d["instrumentType"])
    parser.add_argument("--pasteurization", default=d["pasteurization"])
    parser.add_argument("--nan-handling", default=d["nanHandling"])
    parser.add_argument("--unit-handling", default=d["unitHandling"])
    parser.add_argument(
        "--test-period",
        default=d["testPeriod"],
        help="out-of-sample tail reserved from the backtest, e.g. 1y, 6m, 1y6m",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wqo", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    # auth
    auth = sub.add_parser("auth", help="authentication and account status")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_sub.add_parser("login", help="authenticate and cache the session cookie")
    auth_sub.add_parser("status", help="show account, quotas, and learned concurrency")
    auth_sub.add_parser("persona", help="finish a biometric check done in a browser")
    auth_sub.add_parser("logout", help="drop the cached session")
    auth.set_defaults(func=cmd_auth)

    # data
    data = sub.add_parser("data", help="datasets, datafields, operators")
    data_sub = data.add_subparsers(dest="data_command", required=True)
    for name in ("datasets", "fields", "operators"):
        p = data_sub.add_parser(name)
        p.add_argument("--refresh", action="store_true", help="bypass the local cache")
        p.add_argument("--raw", action="store_true", help="print full API records")
        if name != "operators":
            p.add_argument("--region", default="USA")
            p.add_argument("--delay", type=int, default=1)
            p.add_argument("--universe", default="TOP3000")
            p.add_argument("--search")
        if name == "fields":
            p.add_argument("--dataset")
            p.add_argument("--type", help="MATRIX, VECTOR, GROUP, ...")
            p.add_argument("--limit", type=int, default=0)
    data.set_defaults(func=cmd_data)

    # sim
    sim = sub.add_parser("sim", help="run backtests")
    sim_sub = sim.add_subparsers(dest="sim_command", required=True)
    run = sim_sub.add_parser("run", help="simulate one expression")
    run.add_argument("--code", required=True)
    run.add_argument("--label")
    run.add_argument("--no-cache", action="store_true", help="re-run even if simulated before")
    add_settings_args(run)
    batch = sim_sub.add_parser("batch", help="simulate a JSON list of expressions")
    batch.add_argument("--file", required=True, help="path to JSON list, or - for stdin")
    batch.add_argument("--no-cache", action="store_true")
    add_settings_args(batch)
    recent = sim_sub.add_parser("recent", help="show recent runs from the local ledger")
    recent.add_argument("--limit", type=int, default=20)
    sim.set_defaults(func=cmd_sim)

    # alpha
    alpha = sub.add_parser("alpha", help="inspect and manage alphas")
    alpha_sub = alpha.add_subparsers(dest="alpha_command", required=True)
    for name in ("get", "pnl", "yearly"):
        p = alpha_sub.add_parser(name)
        p.add_argument("alpha_id")
    corr = alpha_sub.add_parser("corr", help="self or production correlation")
    corr.add_argument("alpha_id")
    corr.add_argument("--prod", action="store_true", help="production instead of self")
    listing = alpha_sub.add_parser("list", help="filter your own alphas")
    listing.add_argument("--status", help="UNSUBMITTED, ACTIVE, ...")
    listing.add_argument("--region")
    listing.add_argument("--universe")
    listing.add_argument("--delay", type=int)
    listing.add_argument("--min-sharpe", type=float)
    listing.add_argument("--min-fitness", type=float)
    listing.add_argument("--color")
    listing.add_argument("--tag")
    listing.add_argument(
        "--grade",
        help="INFERIOR, AVERAGE, GOOD, EXCELLENT, SPECTACULAR (matched locally)",
    )
    listing.add_argument("--order", default="-dateCreated")
    listing.add_argument("--limit", type=int, default=50)
    tag = alpha_sub.add_parser("tag", help="edit name, colour, tags, description")
    tag.add_argument("alpha_id")
    tag.add_argument("--name")
    tag.add_argument("--color")
    tag.add_argument("--tags", help="comma separated")
    tag.add_argument("--category")
    tag.add_argument("--description")
    tag.add_argument("--favorite", action="store_true", default=None)
    tag.add_argument("--hidden", action="store_true", default=None)
    alpha.set_defaults(func=cmd_alpha)

    # gate
    gate_p = sub.add_parser("gate", help="pre-submission report (read-only)")
    gate_p.add_argument("alpha_id")
    gate_p.add_argument("--json", action="store_true")
    gate_p.add_argument("--no-correlations", action="store_true")
    gate_p.add_argument("--no-check", action="store_true")
    gate_p.set_defaults(func=cmd_gate)

    # submit
    submit_p = sub.add_parser("submit", help="submit an alpha (requires --confirm)")
    submit_p.add_argument("alpha_id")
    submit_p.add_argument("--confirm", action="store_true", help="actually submit")
    submit_p.add_argument("--force", action="store_true", help="submit despite a failing gate")
    submit_p.add_argument("--json", action="store_true")
    submit_p.set_defaults(func=cmd_submit)

    # mine
    mine = sub.add_parser("mine", help="autonomous candidate generation and backtesting")
    mine.add_argument("--dataset")
    mine.add_argument("--search", help="restrict to datafields matching this text")
    mine.add_argument("--region", default="USA")
    mine.add_argument("--delay", type=int, default=1)
    mine.add_argument("--universe", default="TOP3000")
    mine.add_argument("--neutralizations", help="comma separated, e.g. SUBINDUSTRY,MARKET")
    mine.add_argument(
        "--decay", type=int, help="pin decay; default is the template's own regime"
    )
    mine.add_argument(
        "--truncation",
        type=float,
        help="pin truncation; default is the template's own regime",
    )
    mine.add_argument(
        "--test-period", help="out-of-sample tail, e.g. 1y, 6m, 1y6m (default none)"
    )
    mine.add_argument("--templates", help="comma separated template names")
    mine.add_argument("--max-fields", type=int, default=40)
    mine.add_argument("--budget", type=int, default=40, help="max simulations this run")
    mine.add_argument("--shortlist", type=int, default=10)
    mine.add_argument("--seed", type=int)
    mine.add_argument("--dry-run", action="store_true", help="print candidates, simulate nothing")
    mine.set_defaults(func=cmd_mine)

    # account
    acct = sub.add_parser(
        "account", help="competitions, standing, team, learn, notifications"
    )
    acct_sub = acct.add_subparsers(dest="account_command", required=True)
    acct_sub.add_parser("status", help="your rank, score, and level progress")
    comps = acct_sub.add_parser("competitions", help="list competitions")
    comps.add_argument("--mine", action="store_true", help="only ones you joined")
    comps.add_argument("--raw", action="store_true", help="full API records")
    comp = acct_sub.add_parser("competition", help="one competition")
    comp.add_argument("competition_id")
    comp.add_argument("--alphas", action="store_true", help="your entered alphas")
    comp.add_argument("--agreement", action="store_true", help="terms text")
    acct_sub.add_parser(
        "activity", help="simulation/submission counters and referrals"
    )
    for name, helptext in (
        ("teams", "teams you belong to"),
        ("events", "webinars and scheduled events"),
        ("tutorials", "the Learn tab course list"),
        ("messages", "platform notifications"),
        ("agreements", "agreements on file"),
        ("probe", "which endpoints this account level can reach"),
    ):
        acct_sub.add_parser(name, help=helptext)
    acct.set_defaults(func=cmd_account)

    # api
    api = sub.add_parser("api", help="raw authenticated request to any endpoint")
    api.add_argument("method")
    api.add_argument("path")
    api.add_argument("--data", help="JSON request body")
    api.add_argument("--query", action="append", help="k=v, repeatable")
    api.set_defaults(func=cmd_api)

    discover = sub.add_parser("discover", help="probe for a machine-readable API spec")
    discover.set_defaults(func=cmd_discover)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BiometricRequired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_AUTH
    except AuthError as exc:
        print(f"auth error: {exc}", file=sys.stderr)
        return EXIT_AUTH
    except BudgetExceeded as exc:
        print(f"budget: {exc}", file=sys.stderr)
        return EXIT_BUDGET
    except submit_mod.SubmissionRefused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except ApiError as exc:
        print(f"api error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
