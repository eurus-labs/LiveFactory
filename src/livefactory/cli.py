"""The `livefactory` command line.

In step 2 the CLI opens the store in-process as the operator and stamps human
commands with Actor.HUMAN. Peer-credential authentication arrives with the core
service in step 3 (spec section 13). The `dev` commands simulate the worker and
the supervisor and work only on stores created with `init --dev`.

Every command that changes state takes `--id`, the idempotency key. It is
printed before the write, so after an unknown outcome (exit 3) the operator can
rerun the same command with the same `--id`: a duplicate is answered from its
receipt and applies nothing twice.

Exit codes: 0 done (accepted, duplicate or late), 1 refused (rejected or
conflict) or invalid input, 2 usage error, 3 store unavailable or locked
(retry with the same --id), 4 store corrupt or incompatible (maintenance).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from livefactory import plumber
from livefactory.core.definition import COMPACT_IMPROVEMENT
from livefactory.core.events import (
    Actor,
    AnswerHandoff,
    Event,
    GrantAllowance,
    HumanDecision,
    ReleaseOutcome,
    ReleaseReceipt,
    ResolveConflict,
    StopIntent,
    StopWorkflow,
    SubmitWorkflow,
    Verdict,
)
from livefactory.core.ids import is_ulid
from livefactory.core.model import JobStatus, ReceiptOutcome, Revisions, Workflow
from livefactory.dev import FakeWorker, drive
from livefactory.ids import new_ulid
from livefactory.store import (
    Store,
    StoreCorrupt,
    StoreError,
    StoreIncompatible,
    StoreLocked,
    StoreMissing,
    StoreUnavailable,
)

EXIT_OK, EXIT_REFUSED, EXIT_USAGE, EXIT_UNAVAILABLE, EXIT_MAINTENANCE = 0, 1, 2, 3, 4
_OK = {ReceiptOutcome.ACCEPTED, ReceiptOutcome.DUPLICATE, ReceiptOutcome.LATE}


class _Refused(Exception):
    pass


def main(argv: Sequence[str] | None = None, out: TextIO = sys.stdout, err: TextIO = sys.stderr) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # usage errors and --help
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    if "id" in vars(args) and args.id is None:
        args.id = new_ulid()
    command: Callable[[argparse.Namespace, TextIO, TextIO], int] = args.run
    try:
        return command(args, out, err)
    except _Refused as exc:
        print(f"refused: {exc}", file=err)
        return EXIT_REFUSED
    except (StoreUnavailable, StoreLocked, StoreMissing) as exc:
        key = getattr(args, "id", None)
        hint = f"; rerun the same command with --id {key}" if key else ""
        print(f"store unavailable: {exc}{hint}", file=err)
        return EXIT_UNAVAILABLE
    except (StoreCorrupt, StoreIncompatible) as exc:
        print(f"maintenance required, do not retry: {exc}", file=err)
        return EXIT_MAINTENANCE
    except StoreError as exc:
        print(f"store error: {exc}", file=err)
        return EXIT_REFUSED


# -- commands -------------------------------------------------------------------


def _init(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    path = _db(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    Store.create(path, dev_mode=args.dev).close()
    print(f"created {path}{' (dev mode)' if args.dev else ''}", file=out)
    return EXIT_OK


def _validate(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    try:
        definition = plumber.load_definition(Path(args.file))
    except plumber.DefinitionError as exc:
        raise _Refused(str(exc)) from exc
    diagnostics = plumber.validate(definition)
    for d in diagnostics:
        where = f" [{d.stage_id}]" if d.stage_id else ""
        print(f"{d.severity.value}: {d.code}{where}: {d.message}", file=out)
    print(f"digest: {plumber.definition_digest(definition)}", file=out)
    return EXIT_REFUSED if plumber.errors(diagnostics) else EXIT_OK


def _submit(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    problems = plumber.errors(plumber.validate(COMPACT_IMPROVEMENT))
    if problems:
        raise _Refused("the built-in workflow does not validate: " + ", ".join(p.code for p in problems))
    return _send(args, out, err, SubmitWorkflow(args.id, args.workflow, COMPACT_IMPROVEMENT, Actor.HUMAN))


def _decide(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    parts = args.covers.split(",")
    if len(parts) != 3 or not all(parts):
        raise _Refused("--covers must be PROFILE,DIRECTION,PLAN exactly as `status` shows it")
    covers = Revisions(*parts)
    event = HumanDecision(args.id, args.job, covers, Verdict(args.verdict), Actor.HUMAN)
    return _send(args, out, err, event)


def _answer(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    return _send(args, out, err, AnswerHandoff(args.id, args.job, Actor.HUMAN))


def _stop(intent: StopIntent) -> Callable[[argparse.Namespace, TextIO, TextIO], int]:
    def run(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
        return _send(args, out, err, StopWorkflow(args.id, args.workflow, intent, Actor.HUMAN))

    return run


def _grant(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    return _send(args, out, err, GrantAllowance(args.id, args.job, args.amount, Actor.HUMAN))


def _resolve(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    return _send(args, out, err, ResolveConflict(args.id, args.workflow, Actor.HUMAN))


def _status(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    with Store.open(_db(args)) as store:
        state = store.state
        workflows = [state.workflows[args.workflow]] if args.workflow else list(state.workflows.values())
        if args.workflow and args.workflow not in state.workflows:
            raise _Refused(f"unknown workflow {args.workflow}")
        for workflow in workflows:
            _print_workflow(store, workflow, out)
        print(f"undelivered messages: {len(store.pending_outbox())}", file=out)
    return EXIT_OK


def _dev_run(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    with Store.open(_db(args)) as store:
        _require_dev(store)
        report = drive(store, FakeWorker())
        print(f"dispatched {len(report.dispatched)} attempt(s)", file=out)
        for message in report.waiting:
            print(f"waiting: {message}", file=out)
    return EXIT_OK


def _dev_release(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    with Store.open(_db(args)) as store:
        _require_dev(store)
        job = store.state.jobs.get(args.job)
        bundle = args.bundle or (job.bundle_digest if job else None) or ""
        event = ReleaseReceipt(args.id, args.job, bundle, ReleaseOutcome(args.outcome), Actor.SUPERVISOR)
        return _apply(store, event, out, err)


# -- helpers ----------------------------------------------------------------------


def _db(args: argparse.Namespace) -> Path:
    value = args.db or os.environ.get("LIVEFACTORY_DB")
    if not value:
        raise _Refused("set --db PATH or LIVEFACTORY_DB")
    return Path(value)


def _require_dev(store: Store) -> None:
    if not store.dev_mode:
        raise _Refused("dev commands need a store created with `init --dev`")


def _send(args: argparse.Namespace, out: TextIO, err: TextIO, event: Event) -> int:
    with Store.open(_db(args)) as store:
        return _apply(store, event, out, err)


def _apply(store: Store, event: Event, out: TextIO, err: TextIO) -> int:
    key = getattr(event, "command_id", None) or getattr(event, "decision_id", None) or getattr(
        event, "release_request_id", ""
    )
    print(f"id: {key}", file=err)
    receipt = store.submit(event).receipt
    detail = f": {receipt.reason}" if receipt.reason else ""
    print(f"{receipt.outcome.value}{detail}", file=out)
    return EXIT_OK if receipt.outcome in _OK else EXIT_REFUSED


def _print_workflow(store: Store, workflow: Workflow, out: TextIO) -> None:
    state = store.state
    reason = f" ({workflow.ending_reason})" if workflow.ending_reason else ""
    print(f"{workflow.workflow_id}  {workflow.status.value}{reason}", file=out)
    current = _covers(workflow.current_revisions)
    approved = _covers(workflow.approved_revisions)
    print(f"  revisions: {current}  approved: {approved}", file=out)
    if workflow.result_conflicts:
        conflicts = ", ".join(workflow.result_conflicts)
        print(f"  CONFLICT on attempts {conflicts} -> livefactory resolve {workflow.workflow_id}", file=out)
    for job_id in workflow.job_ids:
        job = state.jobs[job_id]
        note = f" {job.reason}" if job.reason else ""
        print(f"  {job_id:<28} {job.status.value}{note}", file=out)
        stage = workflow.definition.stages[job.stage_id]
        if job.status is JobStatus.AWAITING_DECISION and stage.routes.keys() >= {"approve"}:
            print(
                f"    -> livefactory decide {job_id} approve|revise|reject --covers {current}",
                file=out,
            )
        elif job.status is JobStatus.AWAITING_DECISION:
            print(f"    -> livefactory answer {job_id}", file=out)
        elif job.status is JobStatus.BLOCKED and job.reason and job.reason.endswith("_limit"):
            print(f"    -> livefactory grant {job_id} 1", file=out)


def _covers(revisions: Revisions | None) -> str:
    if revisions is None:
        return "none"
    return f"{revisions.profile},{revisions.direction},{revisions.plan}"


def _ulid(text: str) -> str:
    if not is_ulid(text):
        raise argparse.ArgumentTypeError("must be a canonical ULID")
    return text


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="livefactory", description="LiveFactory core command line")
    parser.add_argument("--db", help="store path (default: $LIVEFACTORY_DB)")
    commands = parser.add_subparsers(required=True, metavar="COMMAND")

    def command(name: str, run: Callable[[argparse.Namespace, TextIO, TextIO], int], help: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help)
        sub.set_defaults(run=run)
        return sub

    def with_id(sub: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sub.add_argument("--id", type=_ulid, default=None, help="idempotency key (default: new ULID)")
        return sub

    command("init", _init, "create a store").add_argument("--dev", action="store_true", help="allow dev commands")
    command("validate", _validate, "check a workflow definition file").add_argument("file")
    with_id(command("submit", _submit, "start the built-in improvement workflow")).add_argument("workflow")
    command("status", _status, "show workflows and what they wait for").add_argument("workflow", nargs="?")
    decide = with_id(command("decide", _decide, "decide an approval gate"))
    decide.add_argument("job")
    decide.add_argument("verdict", choices=[v.value for v in Verdict])
    decide.add_argument("--covers", required=True, help="PROFILE,DIRECTION,PLAN as shown by status")
    with_id(command("answer", _answer, "resume a job that asked a question")).add_argument("job")
    with_id(command("cancel", _stop(StopIntent.CANCEL), "cancel a workflow")).add_argument("workflow")
    with_id(command("reject", _stop(StopIntent.REJECT), "reject a workflow")).add_argument("workflow")
    grant = with_id(command("grant", _grant, "grant a blocked job a finite extra allowance"))
    grant.add_argument("job")
    grant.add_argument("amount", type=int)
    with_id(command("resolve", _resolve, "keep accepted results after a conflict")).add_argument("workflow")

    dev = commands.add_parser("dev", help="step-2 harness (dev-mode stores only)")
    dev_commands = dev.add_subparsers(required=True, metavar="DEV_COMMAND")
    dev_commands.add_parser("run", help="run the fake worker until a human is needed").set_defaults(run=_dev_run)
    release = dev_commands.add_parser("release", help="simulate a supervisor release receipt")
    release.set_defaults(run=_dev_release)
    release.add_argument("--id", type=_ulid, default=None)
    release.add_argument("job")
    release.add_argument("outcome", choices=[o.value for o in ReleaseOutcome])
    release.add_argument("--bundle", help="bundle digest (default: the job's)")
    return parser


def entry() -> None:
    try:
        code = main()
        sys.stdout.flush()
    except BrokenPipeError:
        # The reader went away (e.g. `| head`); stop quietly.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        code = EXIT_OK
    sys.exit(code)
