"""Closed actual P1/P3 action schedules; synthetic suppliers, no product changes.

Only the explicit owner/worker helper imports P1 internals. This consumer composes
installed public clients and the unchanged configured public example.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import cast
from uuid import uuid4

from psycopg import sql

from continuity_lab.action_api import ActionError, ActionReceipt, open_action_client
from continuity_lab.case_control_api import CaseControlClient, open_case_control_client
from continuity_lab.delivery_api import open_delivery_client
from continuity_lab.execution_api import open_execution_client
from continuity_lab.postgres_api import (
    Confirmation,
    IntentAlreadyCommitted,
    InvalidConfirmation,
    ManagedCaseClient,
    open_postgres_client,
    parse_confirmation_payload,
)
from continuity_lab.receiver_api import (
    ReceiverBinding,
    initialize_result_receiver,
    open_result_receiver,
)
from continuity_lab.work_admin import (
    install_work_schema,
    upgrade_work_schema_v2,
    upgrade_work_schema_v3,
    upgrade_work_schema_v4,
)
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from delegation_reliability import (
    ActionBinding,
    CompletionError,
    DelegationAuthorizer,
    DelegationCoordinator,
    DelegationDeliveryClient,
    DelegationRunner,
    DeliveryBinding,
    ExactManagedCaseAuthority,
    SpecialistResultObservation,
)
from delegation_reliability.contracts import (
    DelegationRequest,
    Scope,
    canonical,
    encode_request,
    parse_request,
    parse_result,
    produce_request,
)
from delegation_reliability.security import EvidenceRecord

CASES = (
    "validated_a_b_revision_first_atomic_rejection",
    "valid_b_exact_confirmation_effect_progress",
    "a_intent_first_b_revision_rejected",
    "committed_revision_boundary_original_receipt",
    "preintent_cancel_zero_authority",
    "postintent_predispatch_cancel_zero_apply",
    "after_claim_cancel_zero_apply",
    "postreservation_cancel_original_apply",
    "known_external_success_late_cancel_deadline",
    "action_precommit_kill_rollback_progress",
    "action_postcommit_kill_original_receipt",
    "supplier_commit_kill_fresh_lookup_no_reapply",
    "changed_confirmation_scope_conflicts_zero_new_effect",
    "waiter_abort_retains_guard_io_cleanup",
    "result_receiver_distinct_from_supplier_effect",
    "independent_full_identity_reconciliation_cleanup",
)
MODES = (
    "install",
    "prepare-b-first",
    "action-b-first",
    "revise-b-first",
    "lock-b-first",
    "finish-b-first",
    "prepare-a-first",
    "action-a-first",
    "revise-a-first",
    "lock-a-first",
    "finish-a-first",
    "cancel-before-intent",
    "prepare-claim",
    "worker-claim",
    "cancel-claim",
    "prepare-reserved",
    "worker-reserved",
    "cancel-reserved",
    "prepare-applied",
    "worker-applied",
    "cancel-applied",
    "recover-applied",
    "prepare-precommit",
    "action-precommit",
    "recover-precommit",
    "prepare-postcommit",
    "action-postcommit",
    "recover-postcommit",
    "owned-lifetime",
    "owner-check",
    "cleanup",
)
OWNER_MODES = {"install", "lock-b-first", "lock-a-first", "owner-check", "cleanup"}
BARRIERS = {
    "action-b-first": "a_before_locks_b_first",
    "action-a-first": "a_before_locks_a_first",
    "revise-b-first": "b_before_revise_b_first",
    "revise-a-first": "b_before_revise_a_first",
    "lock-b-first": "case_admission_b_first",
    "lock-a-first": "case_admission_a_first",
    "worker-claim": "worker_claim",
    "worker-reserved": "worker_reserved",
    "worker-applied": "supplier_committed",
    "action-precommit": "action_before_commit",
    "action-postcommit": "action_after_commit",
}
BASE = {
    "PATH",
    "HOME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SYSTEMROOT",
    "__CF_USER_TEXT_ENCODING",
    "NO_COLOR",
    "CI",
}
MODE = ""
STAGE = "fixture"
SCOPE = Scope("tenant_action", "account_action")
POLICY = canonical({"minimum_notice_days": 7, "policy_version": "policy_v1"})
RECIPIENT = "recipient_action"
MARKER = "p3-action-race-work-fixture-v1"
WORK_MARKERS = {i: "continuity-readonly-work-v" + str(i) for i in (1, 2, 3, 4)}
ROOT = Path(__file__).resolve().parents[3]


def module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    # dataclasses in the configured public example require its normal module entry.
    import sys

    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


HELPER = module(ROOT / "local-setup/scripts/p3_action_case_fixture.py", "p3_action_fixture")
EXAMPLE = module(
    ROOT / "projects/delegation-reliability/examples/policy_completion.py",
    "p3_action_public_example",
)
CONTRACT = cast(dict[str, object], json.loads((ROOT / "contracts/delegation/v1.json").read_text()))


def environment(mode: str) -> None:
    required = {
        "P3_RACE_WORK_SCHEMA",
        "P3_RACE_CASE_SCHEMA",
        "P3_RACE_DIRECTORY",
        "P3_RACE_PG_PORT",
    }
    required.add("P3_RACE_OWNER_PASSWORD" if mode in OWNER_MODES else "P3_RACE_RUNTIME_PASSWORD")
    if mode not in OWNER_MODES:
        required.add("P3_RACE_TOKEN")
    if mode in BARRIERS:
        required.add("P3_RACE_BARRIER")
    assert required <= os.environ.keys() and not (os.environ.keys() - required - BASE), (
        "unsafe_child_environment"
    )
    assert re.fullmatch(r"p1_work_actionrace_[0-9a-f]{32}", os.environ["P3_RACE_WORK_SCHEMA"])
    assert re.fullmatch(r"p3_completion_[0-9a-f]{32}", os.environ["P3_RACE_CASE_SCHEMA"])


def folder() -> Path:
    value = Path(os.environ["P3_RACE_DIRECTORY"])
    assert value.is_dir() and not value.is_symlink()
    return value


def settings(*, case: bool = False) -> PostgresSettings:
    owner = MODE in OWNER_MODES
    return PostgresSettings(
        port=int(os.environ["P3_RACE_PG_PORT"]),
        schema=os.environ["P3_RACE_CASE_SCHEMA" if case else "P3_RACE_WORK_SCHEMA"],
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ["P3_RACE_OWNER_PASSWORD" if owner else "P3_RACE_RUNTIME_PASSWORD"],
    )


def save(name: str, value: object) -> None:
    assert re.fullmatch(r"[a-z][a-z0-9_]*\.json", name)
    fd = os.open(folder() / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical(value))


def load(name: str) -> dict[str, object]:
    value = json.loads((folder() / name).read_bytes())
    assert type(value) is dict
    return cast(dict[str, object], value)


def case_data(label: str) -> dict[str, object]:
    return load("case_" + label + ".json")


def result_data(label: str) -> dict[str, object]:
    return load("result_" + label + ".json")


def supplier(label: str) -> Path:
    return folder() / ("supplier_" + label + ".sqlite3")


def registrations(*, foreign: bool = False) -> tuple[WorkDirectory, BearerToken]:
    token = BearerToken(os.environ["P3_RACE_TOKEN"])
    return WorkDirectory(
        {
            token: WorkPrincipal(
                "race_actor",
                WorkScope(SCOPE.tenant_id, "foreign_account" if foreign else SCOPE.account_id),
            )
        }
    ), token


def client(label: str) -> ManagedCaseClient:
    return open_postgres_client(
        actor=HELPER.ACTOR,
        token=BearerToken(os.environ["P3_RACE_TOKEN"]),
        settings=settings(case=True),
        quote_database=supplier(label),
    )


def control(label: str) -> CaseControlClient:
    return open_case_control_client(
        actor=HELPER.ACTOR,
        token=BearerToken(os.environ["P3_RACE_TOKEN"]),
        settings=settings(case=True),
        quote_database=supplier(label),
    )


def binding(label: str) -> ActionBinding:
    value = case_data(label)
    return ActionBinding(
        "case_" + label,
        str(value["task_id"]),
        str(value["case_id"]),
        HELPER.ACTOR.actor_id,
        HELPER.ACTOR.scope_id,
        settings(case=True).schema,
    )


def evidence() -> tuple[EvidenceRecord, ...]:
    # Descriptor is validated by the canonical request codec instead of a private factory.
    value = request("evidence", 2)
    return (EvidenceRecord(SCOPE, value.evidence[0], POLICY),)


def request(label: str, revision: int, *, horizon_ms: int = 60000) -> DelegationRequest:
    raw = cast(dict[str, object], json.loads(canonical(CONTRACT["producer_input"])))
    raw.update(
        scope={"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id},
        delegation_id="delegation_" + label,
        case_id="case_b_first" if label == "b_first_b" else "case_" + label,
        request_revision=revision,
        deadline_at_ms=time.time_ns() // 1_000_000 + horizon_ms,
    )
    raw["result_route"] = {"conversation_id": "conversation_action"}
    raw["evidence"] = [
        {
            "source_id": "policy_demo",
            "version": "source_v1",
            "sha256": hashlib.sha256(POLICY).hexdigest(),
            "media_type": "application/json",
            "byte_length": len(POLICY),
            "width": None,
            "height": None,
        }
    ]
    return produce_request(raw)


class LocalPolicy:
    """Strict scripted read-only producer; P1 alone issues and records its attempt."""

    async def invoke_observed(self, value: DelegationRequest) -> SpecialistResultObservation:
        original = parse_result(canonical(CONTRACT["result"]))
        result = replace(
            original,
            scope=value.scope,
            delegation_id=value.delegation_id,
            case_id=value.case_id,
            request_revision=value.request_revision,
            attempt_id=value.attempt.attempt_id,
            input_fingerprint=value.input_fingerprint,
            completed_at_ms=time.time_ns() // 1_000_000,
        )
        return SpecialistResultObservation(result, "candidate", time.time_ns() // 1_000_000)

    async def close(self) -> None:
        pass


class Bundle:
    def __init__(
        self,
        label: str,
        *,
        hook: Callable[[str], None] | None = None,
        timeout_ms: int = 10000,
        cleanup_ms: int = 1000,
        foreign: bool = False,
    ) -> None:
        self.label = label
        self.control = control(label)
        self.client = client(label)
        directory, token = registrations(foreign=foreign)
        authority = ExactManagedCaseAuthority(self.control, scope=SCOPE, bindings=(binding(label),))
        self.coordinator = DelegationCoordinator(
            executions=open_work_client(settings=settings(), directory=directory, token=token),
            scope=SCOPE,
            case_authority=authority,
        )
        self.runner = DelegationRunner(
            executions=open_execution_client(settings=settings(), directory=directory, token=token),
            scope=SCOPE,
            owner_id=str(uuid4()),
            specialist=LocalPolicy(),
            case_authority=authority,
            evidence=evidence(),
        )
        self.actions = open_action_client(
            settings=settings(),
            directory=directory,
            token=token,
            case_settings=settings(case=True),
            case_actor=HELPER.ACTOR,
            case_token=token,
            harness_failpoint=hook,
        )
        self.authorizer = DelegationAuthorizer(
            results=self.runner,
            actions=self.actions,
            scope=SCOPE,
            evidence=evidence(),
            bindings=(binding(label),),
            max_active=1,
            timeout_ms=timeout_ms,
            cleanup_ms=cleanup_ms,
        )
        self.delivery = DelegationDeliveryClient(
            results=self.runner,
            deliveries=open_delivery_client(settings=settings(), directory=directory, token=token),
            receiver=open_result_receiver(
                folder() / "receiver.sqlite3",
                receiver_id=str(load("receiver.json")["receiver_id"]),
                bindings=(
                    ReceiverBinding(WorkScope(SCOPE.tenant_id, SCOPE.account_id), RECIPIENT),
                ),
            ),
            scope=SCOPE,
            evidence=evidence(),
            bindings=(DeliveryBinding("case_" + label, "conversation_action", RECIPIENT),),
        )

    async def close(self) -> None:
        await self.authorizer.close()
        await self.delivery.close()
        await self.runner.close()
        await self.coordinator.close()
        await self.control.close()
        await self.client.close()


def exact(label: str) -> Confirmation:
    payload = load("quote_" + label + ".json")
    return parse_confirmation_payload(canonical(payload["quote"]).decode(), explicit=True)


def action_payload(value: ActionReceipt) -> dict[str, object]:
    return {
        "action_id": value.action_id,
        "work_id": value.work_id,
        "attempt_id": value.attempt_id,
        "sha256": value.result_sha256,
        "expected_revision": value.expected_revision,
        "command_id": value.command_id,
        "committed_at_ms": value.committed_at_ms,
        "confirmation": value.confirmation.payload(),
        "intent": value.intent.payload(),
    }


async def prepare(label: str, *, commit: bool = False, horizon_ms: int = 60000) -> None:
    global STAGE
    STAGE = "prepare_" + label
    HELPER.initialize_supplier(supplier(label))
    c = client(label)
    ctl = control(label)
    try:
        accepted = await c.submit(idempotency_key="case_" + label, request=HELPER.REQUEST)
        save("case_" + label + ".json", {"task_id": accepted.task_id, "case_id": accepted.case_id})
        await asyncio.to_thread(
            HELPER.inquire, settings(case=True), supplier(label), accepted.task_id
        )
        await ctl.revise(task_id=accepted.task_id, expected_revision=0, request=HELPER.ALTERNATE)
        await ctl.revise(task_id=accepted.task_id, expected_revision=1, request=HELPER.REQUEST)
        quote = await c.prepare_quote(
            task_id=accepted.task_id, expected_revision=2, command_id="quote_" + label
        )
        save("quote_" + label + ".json", {"quote": quote.quote.payload()})
    finally:
        await c.close()
        await ctl.close()
    b = Bundle(label)
    try:
        value = request(label, 2, horizon_ms=horizon_ms)
        accepted_work = await b.coordinator.submit(value)
        wid = accepted_work.view.record.work_id
        outcome = await b.runner.run_once(wid, "run_" + label)
        assert outcome.view.applicability == "candidate" and outcome.recorded is not None
        assert outcome.view.execution.current_attempt is not None
        save(
            "result_" + label + ".json",
            {
                "work_id": wid,
                "attempt_id": outcome.view.execution.current_attempt.attempt_id,
                "sha256": outcome.recorded.sha256,
                "request_sha256": accepted_work.view.record.payload.sha256,
                "request": json.loads(encode_request(value)),
            },
        )
        if commit:
            await authorize(b, label)
    finally:
        await b.close()


async def authorize(b: Bundle, label: str, *, quote_label: str | None = None) -> ActionReceipt:
    row = result_data(label)
    result = await b.authorizer.authorize_once(
        str(row["work_id"]), confirmation=exact(quote_label or label), command_id="action_" + label
    )
    receipt = result.receipt
    path = folder() / ("action_" + label + ".json")
    if path.exists():
        assert load(path.name) == action_payload(receipt)
    else:
        save(path.name, action_payload(receipt))
    return receipt


def hold(name: str, *, timeout: float = 12) -> None:
    reached = Path(os.environ["P3_RACE_BARRIER"])
    assert reached == folder() / (name + ".reached")
    HELPER.marker(reached)
    deadline = time.monotonic() + timeout
    release = reached.with_suffix(".released")
    while not release.exists():
        assert time.monotonic() < deadline, "barrier_timeout"
        time.sleep(0.002)
    assert release.read_text() == str(os.getpid()) + "\n", "wrong_barrier_release"


def action_hook(stage: str) -> None:
    match = {
        "action-b-first": "authorize.before_locks",
        "action-a-first": "authorize.before_locks",
        "action-precommit": "authorize.before_commit",
        "action-postcommit": "authorize.after_commit",
    }
    if stage == match.get(MODE):
        hold(BARRIERS[MODE])


def reply(*ids: int, **fields: object) -> dict[str, object]:
    return {"status": "passed", **({"cases": [CASES[i] for i in ids]} if ids else {}), **fields}


async def apply(label: str, *, hook: Callable[[str], None] | None = None) -> dict[str, object]:
    value = await asyncio.to_thread(
        HELPER.mutate,
        settings(case=True),
        supplier(label),
        str(case_data(label)["task_id"]),
        failpoint=hook,
    )
    assert type(value) is dict
    return cast(dict[str, object], value)


async def cancel(label: str, *, command_id: str | None = None) -> str:
    c = client(label)
    try:
        command = command_id or "cancel_" + label
        receipt = await c.cancel(task_id=str(case_data(label)["task_id"]), command_id=command)
        snapshot = {
            "cancellation_id": receipt.cancellation_id,
            "task_id": receipt.task_id,
            "case_id": receipt.case_id,
            "command_id": receipt.command_id,
            "reason": receipt.reason.value,
            "disposition": receipt.disposition.value,
            "created_at": receipt.created_at,
        }
        name = "cancellation_" + command + ".json"
        if (folder() / name).exists():
            assert load(name) == snapshot and receipt.created is False
        else:
            save(name, snapshot)
        return receipt.disposition.value
    finally:
        await c.close()


def applied(label: str) -> int:
    return int(HELPER.supplier_truth(supplier(label))["applied_calls"])


async def action_order() -> dict[str, object]:
    label = "b_first" if MODE == "action-b-first" else "a_first"
    b = Bundle(label, hook=action_hook)
    try:
        if label == "b_first":
            try:
                await authorize(b, label)
            except CompletionError as error:
                assert error.code == "stale_revision", error.code
            else:
                raise AssertionError("stale_a_committed")
            assert await b.authorizer.inspect(str(result_data(label)["work_id"])) is None
            save(
                "stale_a.json", {"work_id": result_data(label)["work_id"], "code": "stale_revision"}
            )
            return reply(scenario=label, action_code="stale_revision")
        await authorize(b, label)
        return reply(scenario=label, action_committed=True)
    finally:
        await b.close()


async def revise_order() -> dict[str, object]:
    label = "b_first" if MODE == "revise-b-first" else "a_first"
    c = control(label)  # prewarm before parent lock admission
    try:
        await asyncio.to_thread(hold, BARRIERS[MODE])
        if label == "a_first":
            try:
                await c.revise(
                    task_id=str(case_data(label)["task_id"]),
                    expected_revision=2,
                    request=HELPER.ALTERNATE,
                )
            except IntentAlreadyCommitted:
                return reply(scenario=label, revision_code="intent_committed")
            raise AssertionError("revision_replaced_committed_intent")
        await c.revise(
            task_id=str(case_data(label)["task_id"]), expected_revision=2, request=HELPER.ALTERNATE
        )
        row = await c.revise(
            task_id=str(case_data(label)["task_id"]), expected_revision=3, request=HELPER.REQUEST
        )
        assert row.revision == 4
        return reply(scenario=label, case_revision=4)
    finally:
        await c.close()


async def finish_b() -> dict[str, object]:
    label = "b_first"
    b = Bundle(label)
    try:
        case = await b.control.case(task_id=str(case_data(label)["task_id"]))
        assert case.revision == 4 and case.intent is None
        assert applied(label) == 0
        quote = await b.client.prepare_quote(
            task_id=case.task_id, expected_revision=4, command_id="quote_b_current"
        )
        save("quote_b_first_b.json", {"quote": quote.quote.payload()})
        value = request("b_first_b", 4)
        # Same trusted logical case, separate independently confirmed current work.
        raw = json.loads(encode_request(value))
        raw.pop("input_fingerprint")
        raw["case_id"] = "case_b_first"
        value = produce_request(raw)
        submitted = await b.coordinator.submit(value)
        wid = submitted.view.record.work_id
        result = await b.runner.run_once(wid, "run_b_current")
        assert result.recorded is not None and result.view.execution.current_attempt is not None
        save(
            "result_b_first_b.json",
            {
                "work_id": wid,
                "attempt_id": result.view.execution.current_attempt.attempt_id,
                "sha256": result.recorded.sha256,
                "request_sha256": submitted.view.record.payload.sha256,
                "request": json.loads(encode_request(value)),
            },
        )
        received = await b.delivery.deliver_once(wid)
        assert received.state == "accepted" and received.snapshot.receipt is not None
        action = await authorize(b, "b_first_b")
        assert action.expected_revision == 4
        assert (await apply(label))["effect_state"] == "succeeded" and applied(label) == 1
        inspection = await EXAMPLE.inspect_accepted(
            wid,
            coordinator=b.coordinator,
            runner=b.runner,
            delivery=b.delivery,
            authorizer=b.authorizer,
        )
        assert inspection.action == action and inspection.delivery.snapshot == received.snapshot
        assert inspection.delivery.state == "accepted"
        save(
            "delivery_b_first.json",
            {
                "delivery_id": received.snapshot.receipt.delivery_id,
                "receipt_id": received.snapshot.receipt.receipt_id,
            },
        )
        return reply(0, 1)
    finally:
        await b.close()


async def finish_a() -> dict[str, object]:
    label = "a_first"
    b = Bundle(label)
    try:
        original = await authorize(b, label)
        current = await b.control.case(task_id=str(case_data(label)["task_id"]))
        assert current.revision == 2 and current.intent == original.intent
        # Even an equal request cannot revise an already committed intent.
        try:
            await b.control.revise(
                task_id=current.task_id, expected_revision=2, request=HELPER.REQUEST
            )
        except IntentAlreadyCommitted:
            pass
        else:
            raise AssertionError("postintent_equal_revision_admitted")
        delivered = await b.delivery.deliver_once(str(result_data(label)["work_id"]))
        assert delivered.snapshot.receipt is not None and applied(label) == 0
        inspection = await EXAMPLE.inspect_accepted(
            str(result_data(label)["work_id"]),
            coordinator=b.coordinator,
            runner=b.runner,
            delivery=b.delivery,
            authorizer=b.authorizer,
        )
        assert inspection.action == original and inspection.delivery.state == "accepted"
        assert inspection.action.intent.effect_id == original.intent.effect_id
        # Receiver truth alone did not call a supplier or witness human playback.
        assert (await apply(label))["effect_state"] == "succeeded" and applied(label) == 1
        assert await cancel(label) == "already_terminal"
        assert await authorize(b, label) == original
        save(
            "delivery_a_first.json",
            {
                "delivery_id": delivered.snapshot.receipt.delivery_id,
                "receipt_id": delivered.snapshot.receipt.receipt_id,
            },
        )
    finally:
        await b.close()
    await prepare("predispatch", commit=True)
    assert await cancel("predispatch") == "cancelled_before_dispatch"
    assert (await apply("predispatch"))["effect_state"] == "cancelled" and applied(
        "predispatch"
    ) == 0
    return reply(2, 3, 5, 14)


async def preintent() -> dict[str, object]:
    await prepare("preintent")
    assert await cancel("preintent") == "cancelled_before_commit"
    b = Bundle("preintent")
    try:
        try:
            await authorize(b, "preintent")
        except CompletionError as error:
            assert error.code == "not_eligible"
        else:
            raise AssertionError("cancelled_case_intent_created")
        assert await b.authorizer.inspect(str(result_data("preintent")["work_id"])) is None
        assert applied("preintent") == 0
        return reply(4)
    finally:
        await b.close()


async def worker() -> dict[str, object]:
    label = MODE.removeprefix("worker-")
    expected_stage = {
        "claim": "mutation_worker.after_claim",
        "reserved": "mutation_worker.after_dispatch_reserved",
        "applied": "mutation_worker.after_supplier_success",
    }[label]

    def hook(stage: str) -> None:
        if stage == expected_stage:
            hold(BARRIERS[MODE])

    value = await apply(label, hook=hook)
    if label == "claim":
        assert (
            value["effect_state"] == "cancelled"
            and value["worker_code"] == "transition_conflict"
            and applied(label) == 0
        )
        return reply(6, state="cancelled", worker_code="transition_conflict")
    assert label == "reserved" and value["effect_state"] == "succeeded" and applied(label) == 1
    return reply(7, state="succeeded", supplier_applied_calls=1)


async def cancel_applied() -> dict[str, object]:
    assert applied("applied") == 1
    disposition = await cancel("applied")
    assert disposition == "requested_best_effort"
    deadline = time.monotonic() + 12
    while True:
        work_expired, lease_expired = await asyncio.to_thread(
            HELPER.expired,
            settings(case=True),
            str(case_data("applied")["task_id"]),
            settings(),
            str(result_data("applied")["work_id"]),
        )
        if work_expired and lease_expired:
            break
        assert time.monotonic() < deadline, "expiry_not_observed"
        await asyncio.sleep(0.01)
    return reply(
        disposition=disposition, supplier_applied_calls=1, work_expired=True, lease_expired=True
    )


async def recover(label: str) -> dict[str, object]:
    global STAGE
    b = Bundle(label)
    try:
        if label == "precommit":
            assert await b.actions.find_action(command_id="action_" + label) is None
            assert (await b.control.case(task_id=str(case_data(label)["task_id"]))).intent is None
            assert applied(label) == 0
            await authorize(b, label)
        else:
            original = await b.actions.find_action(command_id="action_" + label)
            assert original is not None
            if (folder() / ("action_" + label + ".json")).exists():
                assert load("action_" + label + ".json") == action_payload(original)
            else:
                save("action_" + label + ".json", action_payload(original))
            assert await authorize(b, label) == original
        if label == "postcommit":
            # Changed consent and a foreign account cannot consume/rewrite a fact.
            STAGE = "recover_postcommit_invalid_explicit"
            try:
                altered = Confirmation(exact(label).quote, False)
                await b.authorizer.authorize_once(
                    str(result_data(label)["work_id"]),
                    confirmation=altered,
                    command_id="action_" + label,
                )
            except InvalidConfirmation as error:
                assert error.code == "invalid_confirmation"
            else:
                raise AssertionError("invalid_confirmation_constructor_accepted")
            STAGE = "recover_postcommit_changed_quote"
            quote = exact(label).quote
            changed = Confirmation(replace(quote, amount_minor=quote.amount_minor + 1), True)
            try:
                await b.authorizer.authorize_once(
                    str(result_data(label)["work_id"]),
                    confirmation=changed,
                    command_id="action_" + label,
                )
            except CompletionError as changed_facade_error:
                assert changed_facade_error.code == "identity_conflict", changed_facade_error.code
            else:
                raise AssertionError("changed_quote_replayed_original")
            exact_row = result_data(label)
            try:
                await b.actions.authorize(
                    work_id=str(exact_row["work_id"]),
                    attempt_id=str(exact_row["attempt_id"]),
                    result_sha256=str(exact_row["sha256"]),
                    expected_revision=2,
                    confirmation=changed,
                    command_id="action_" + label,
                )
            except ActionError as changed_guard_error:
                assert changed_guard_error.code == "identity_conflict", changed_guard_error.code
            else:
                raise AssertionError("changed_quote_replaced_guarded_receipt")
            assert await b.actions.find_action(command_id="action_" + label) == original
            assert applied(label) == 0
            STAGE = "recover_postcommit_foreign_scope"
            directory, token = registrations(foreign=True)
            wrong = open_action_client(
                settings=settings(),
                directory=directory,
                token=token,
                case_settings=settings(case=True),
                case_actor=HELPER.ACTOR,
                case_token=token,
            )
            try:
                assert await wrong.find_action(command_id="action_" + label) is None
                assert await wrong.action(work_id=str(result_data(label)["work_id"])) is None
                foreign_row = result_data(label)
                try:
                    await wrong.authorize(
                        work_id=str(foreign_row["work_id"]),
                        attempt_id=str(foreign_row["attempt_id"]),
                        result_sha256=str(foreign_row["sha256"]),
                        expected_revision=2,
                        confirmation=exact(label),
                        command_id="foreign_action",
                    )
                except ActionError as foreign_error:
                    assert foreign_error.code == "not_found", foreign_error.code
                else:
                    raise AssertionError("foreign_scope_created_action")
            finally:
                await wrong.close()
        STAGE = "recover_" + label + "_effect"
        result = await apply(label)
        assert result["effect_state"] == "succeeded" and applied(label) == 1
        # Terminal worker replay and action replay retain original known identities.
        assert (await apply(label)) == result and applied(label) == 1
        STAGE = "recover_" + label + "_terminal_cancel"
        if label == "applied":
            assert await cancel(label) == "requested_best_effort"
        assert await cancel(label, command_id="terminal_" + label) == "already_terminal"
        assert await authorize(b, label) == await b.actions.find_action(
            command_id="action_" + label
        )
        return reply(
            *((8, 11) if label == "applied" else (9,) if label == "precommit" else (10, 12)),
            **({"state": "succeeded"} if label == "applied" else {}),
            supplier_applied_calls=1,
        )
    finally:
        await b.close()


async def lifetime() -> dict[str, object]:
    for variant in ("timeout", "cancel"):
        label = "lifetime_" + variant
        await prepare(label)
        entered, release = threading.Event(), threading.Event()

        def hook(
            stage: str, entered: threading.Event = entered, release: threading.Event = release
        ) -> None:
            if stage == "authorize.before_commit":
                entered.set()
                assert release.wait(2), "held_guard_timeout"

        b = Bundle(label, hook=hook, timeout_ms=1000, cleanup_ms=20)
        task = asyncio.create_task(authorize(b, label))
        try:
            deadline = time.monotonic() + 3
            while not entered.is_set():
                assert time.monotonic() < deadline
                await asyncio.sleep(0.002)
            if variant == "cancel":
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("caller_cancel_ignored")
            else:
                try:
                    await task
                except CompletionError as error:
                    assert error.code == "acknowledgement_unknown", error.code
                else:
                    raise AssertionError("timeout_not_observed")
            assert b.authorizer.pending_count == 1 and b.actions.pending_count == 1
            try:
                await b.authorizer.authorize_once(
                    str(result_data(label)["work_id"]),
                    confirmation=exact(label),
                    command_id="second_" + label,
                )
            except CompletionError as error:
                assert error.code == "capacity"
            else:
                raise AssertionError("abandoned_io_freed_slot")
            try:
                await b.authorizer.close()
            except CompletionError as error:
                assert error.code == "cleanup_incomplete"
            else:
                raise AssertionError("held_guard_closed")
            release.set()
            deadline = time.monotonic() + 3
            while b.authorizer.pending_count:
                assert time.monotonic() < deadline
                await asyncio.sleep(0.005)
            await b.authorizer.close()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await b.close()
        fresh = Bundle(label)
        try:
            receipt = await fresh.actions.find_action(command_id="action_" + label)
            assert receipt is not None
            save("action_" + label + ".json", action_payload(receipt))
            assert await authorize(fresh, label) == receipt
            assert applied(label) == 0
        finally:
            await fresh.close()
    return reply(13, variants=2, cleanup_complete=True)


def inventory_digest(records: list[dict[str, object]]) -> str:
    """Bounded evidence framing, distinct from the 256-node P3 wire envelope.

    Hash complete canonical records with count and fixed-width lengths. Neither
    an omitted record nor a shifted record boundary can have the same framing.
    """
    assert type(records) is list and 1 <= len(records) <= 64, "inventory_record_count"
    digest = hashlib.sha256(b"p3-action-race-reconciliation-v1\x00")
    digest.update(len(records).to_bytes(2, "big"))
    total = 0
    for record in records:
        assert type(record) is dict, "inventory_record_shape"
        encoded = canonical(record)
        assert 1 <= len(encoded) <= 4096, "inventory_record_bytes"
        total += len(encoded)
        assert total <= 65536, "inventory_total_bytes"
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def owner_check() -> dict[str, object]:
    global STAGE
    # Separate owner reads independently join every saved original to authoritative
    # request/result, exact human confirmation, case intent/effect and supplier truth.
    totals = {"actions": 0, "applied": 0, "receipts": 0, "results": 0}
    inventory: list[dict[str, object]] = []
    with closing(settings().connect(application_name="continuity-test")) as connection:
        for path in sorted(folder().glob("result_*.json")):
            row = load(path.name)
            label = path.stem.removeprefix("result_")
            STAGE = "owner_result_" + label
            actual = connection.execute(
                sql.SQL(
                    "SELECT w.*,r.attempt_id,r.body AS result_body,r.sha256 AS result_sha256,r.disposition FROM {}.accepted_work w JOIN {}.attempt_results r USING(work_id,tenant_id,account_id) WHERE w.work_id=%s::uuid"
                ).format(sql.Identifier(settings().schema), sql.Identifier(settings().schema)),
                (row["work_id"],),
            ).fetchone()
            assert actual is not None
            assert (
                actual["tenant_id"] == SCOPE.tenant_id and actual["account_id"] == SCOPE.account_id
            )
            assert actual["sha256"] == row["request_sha256"] and bytes(actual["body"]) == canonical(
                row["request"]
            )
            assert (
                str(actual["attempt_id"]) == row["attempt_id"]
                and actual["result_sha256"] == row["sha256"]
            )
            assert hashlib.sha256(bytes(actual["result_body"])).hexdigest() == row["sha256"]
            result = parse_result(bytes(actual["result_body"]))
            req = parse_request(bytes(actual["body"]))
            assert (
                result.input_fingerprint == req.input_fingerprint
                and result.request_revision == req.request_revision
            )
            assert result.attempt_id == "attempt_" + str(row["attempt_id"]).replace("-", "")
            assert actual["disposition"] == "eligible_at_commit"
            totals["results"] += 1
            identity: dict[str, object] = {
                "scope": [SCOPE.tenant_id, SCOPE.account_id],
                "work_id": row["work_id"],
                "attempt_id": row["attempt_id"],
                "request_sha256": row["request_sha256"],
                "result_sha256": row["sha256"],
            }
            inventory.append(identity)
            action = connection.execute(
                sql.SQL("SELECT * FROM {}.result_actions WHERE work_id=%s::uuid").format(
                    sql.Identifier(settings().schema)
                ),
                (row["work_id"],),
            ).fetchone()
            if label in {"b_first", "preintent"}:
                assert action is None
                continue
            assert action is not None
            STAGE = "owner_action_" + label
            saved = load("action_" + label + ".json")
            assert (
                str(action["action_id"]) == saved["action_id"]
                and str(action["attempt_id"]) == row["attempt_id"]
                and action["result_sha256"] == row["sha256"]
            )
            assert (
                action["tenant_id"] == SCOPE.tenant_id and action["account_id"] == SCOPE.account_id
            )
            assert (
                action["case_schema"] == settings(case=True).schema
                and action["case_scope_id"] == HELPER.ACTOR.scope_id
                and action["case_actor_id"] == HELPER.ACTOR.actor_id
            )
            assert (
                json.loads(action["confirmation_json"]) == saved["confirmation"]
                and json.loads(action["intent_json"]) == saved["intent"]
            )
            actual_label = "b_first" if label == "b_first_b" else label
            case = case_data(actual_label)
            assert (
                str(action["case_task_id"]) == case["task_id"]
                and str(action["case_id"]) == case["case_id"]
            )
            assert action["expected_revision"] == req.request_revision
            joined = connection.execute(
                sql.SQL(
                    "SELECT i.*,c.payload_json AS confirmation_payload,c.actor_id AS confirmation_actor,c.scope_id AS confirmation_scope,e.state AS effect_state,e.result_json,e.dispatch_count FROM {}.action_intents i JOIN {}.confirmations c USING(confirmation_id,task_id) LEFT JOIN {}.mutation_effects e USING(intent_id,task_id) WHERE i.intent_id=%s"
                ).format(*([sql.Identifier(settings(case=True).schema)] * 3)),
                (str(action["intent_id"]),),
            ).fetchone()
            assert joined is not None and json.loads(joined["payload_json"]) == saved["intent"]
            assert json.loads(joined["confirmation_payload"]) == saved["confirmation"]
            assert (
                joined["scope_id"] == joined["confirmation_scope"] == HELPER.ACTOR.scope_id
                and joined["actor_id"] == joined["confirmation_actor"] == HELPER.ACTOR.actor_id
            )
            STAGE = "owner_effect_" + actual_label
            truth = HELPER.supplier_truth(supplier(actual_label))
            assert truth["applied_calls"] in {0, 1}
            assert truth["all_apply_calls"] == truth["applied_calls"], "unexpected_physical_reapply"
            if actual_label in {
                "b_first",
                "a_first",
                "reserved",
                "applied",
                "precommit",
                "postcommit",
            }:
                assert (
                    truth["applied_calls"] == 1
                    and joined["effect_state"] == "succeeded"
                    and joined["dispatch_count"] == 1
                )
                assert len(truth["mutation_receipts"]) == 1
                receipt = truth["mutation_receipts"][0]
                assert (
                    receipt["effect_id"]
                    == joined["effect_id"]
                    == cast(dict[str, object], saved["intent"])["effect_id"]
                )
                assert receipt["scope_id"] == HELPER.ACTOR.scope_id
                assert receipt["result"] == json.loads(joined["result_json"])
                assert truth["bookings"][0][3] == 1
            elif actual_label in {"predispatch", "claim"}:
                assert (
                    truth["applied_calls"] == 0
                    and joined["effect_state"] == "cancelled"
                    and joined["dispatch_count"] == 0
                    and joined["result_json"] is None
                )
            else:
                assert (
                    actual_label.startswith("lifetime_")
                    and truth["applied_calls"] == 0
                    and joined["effect_state"] is None
                )
            identity.update(
                action_id=saved["action_id"],
                intent_id=joined["intent_id"],
                effect_id=joined["effect_id"],
                confirmation_sha256=hashlib.sha256(canonical(saved["confirmation"])).hexdigest(),
                supplier_result_sha256=None
                if joined["result_json"] is None
                else hashlib.sha256(canonical(json.loads(joined["result_json"]))).hexdigest(),
            )
            totals["actions"] += 1
            totals["applied"] += truth["applied_calls"]
        completion_count = 0
        for path in sorted(folder().glob("case_*.json")):
            label = path.stem.removeprefix("case_")
            STAGE = "owner_completion_" + label
            case = load(path.name)
            completed = connection.execute(
                sql.SQL(
                    "SELECT o.payload_json AS outcome_json,o.created_at AS outcome_created,e.event_id,e.payload_json AS event_json,e.created_at AS event_created,d.state AS notification_state,d.attempts AS notification_attempts,d.target_id,d.error_code "
                    "FROM {}.business_outcomes o JOIN {}.completion_events e USING(task_id) JOIN {}.completion_deliveries d USING(event_id) WHERE o.task_id=%s"
                ).format(*([sql.Identifier(settings(case=True).schema)] * 3)),
                (case["task_id"],),
            ).fetchone()
            if label.startswith("lifetime_"):
                assert completed is None
                continue
            assert completed is not None
            outcome = json.loads(completed["outcome_json"])
            event = json.loads(completed["event_json"])
            assert event == {
                "schema_version": 1,
                "kind": "workflow.completed",
                "event_id": completed["event_id"],
                "outcome": outcome,
                "created_at": completed["event_created"],
            }
            assert (
                outcome["schema_version"] == 1
                and outcome["task_id"] == case["task_id"]
                and outcome["case_id"] == case["case_id"]
                and outcome["scope_id"] == HELPER.ACTOR.scope_id
            )
            assert (
                outcome["created_at"] == completed["outcome_created"] == completed["event_created"]
            )
            assert outcome["error_code"] is None
            assert (
                completed["notification_state"] == "pending"
                and completed["notification_attempts"] == 0
                and completed["target_id"] is None
                and completed["error_code"] is None
            )
            expected_cancellation = (
                "cancelled_before_commit"
                if label == "preintent"
                else "cancelled_before_dispatch"
                if label in {"predispatch", "claim"}
                else "requested_best_effort"
                if label in {"reserved", "applied"}
                else "not_requested"
            )
            assert outcome["cancellation"] == expected_cancellation
            if label == "preintent":
                assert (
                    outcome["intent_id"] is None
                    and outcome["effect_id"] is None
                    and outcome["state"] == "cancelled"
                    and outcome["result"] is None
                )
            else:
                action = load("action_" + ("b_first_b" if label == "b_first" else label) + ".json")
                intent = cast(dict[str, object], action["intent"])
                assert (
                    outcome["intent_id"] == intent["intent_id"]
                    and outcome["effect_id"] == intent["effect_id"]
                )
                if label in {"predispatch", "claim"}:
                    assert outcome["state"] == "cancelled" and outcome["result"] is None
                else:
                    truth = HELPER.supplier_truth(supplier(label))
                    assert (
                        outcome["state"] == "succeeded"
                        and outcome["result"] == truth["mutation_receipts"][0]["result"]
                    )
            inventory.append(
                {
                    "task_id": case["task_id"],
                    "completion_event_id": completed["event_id"],
                    "business_outcome_sha256": hashlib.sha256(canonical(outcome)).hexdigest(),
                    "completion_event_sha256": hashlib.sha256(canonical(event)).hexdigest(),
                    "notification_state": "pending",
                    "notification_attempts": 0,
                }
            )
            completion_count += 1
        assert completion_count == 9
        receiver = folder() / "receiver.sqlite3"
        with closing(sqlite3.connect(f"file:{receiver}?mode=ro", uri=True)) as sqlite:
            rows = sqlite.execute("SELECT * FROM result_receipts").fetchall()
            # Decode using named columns instead of relying on positional shape.
            columns = [
                r[1] for r in sqlite.execute("PRAGMA table_info(result_receipts)").fetchall()
            ]
            for raw in rows:
                STAGE = "owner_receiver"
                rr = dict(zip(columns, raw, strict=True))
                authoritative = connection.execute(
                    sql.SQL(
                        "SELECT i.*,r.receipt_id,r.accepted_at_ms FROM {}.result_delivery_intents i JOIN {}.result_delivery_receipts r USING(delivery_id) WHERE i.delivery_id=%s::uuid"
                    ).format(*([sql.Identifier(settings().schema)] * 2)),
                    (rr["delivery_id"],),
                ).fetchone()
                assert authoritative is not None
                assert str(authoritative["receiver_id"]) == str(
                    load("receiver.json")["receiver_id"]
                )
                # Receiver schema uses canonical intent/receipt JSON; exact shape validated below.
                stored_intent = json.loads(rr["intent_json"])
                stored_receipt = json.loads(rr["receipt_json"])
                assert stored_intent["scope"] == {
                    "tenant_id": SCOPE.tenant_id,
                    "account_id": SCOPE.account_id,
                }
                assert stored_intent["recipient_id"] == authoritative["recipient_id"] == RECIPIENT
                assert (
                    stored_intent["result_sha256"]
                    == authoritative["result_sha256"]
                    == stored_receipt["result_sha256"]
                )
                assert (
                    stored_receipt["receipt_id"] == str(authoritative["receipt_id"])
                    and stored_receipt["accepted_at_ms"] == authoritative["accepted_at_ms"]
                )
                assert (
                    stored_intent["receiver_id"]
                    == stored_receipt["receiver_id"]
                    == str(authoritative["receiver_id"])
                )
                assert (
                    stored_intent["delivery_id"]
                    == stored_receipt["delivery_id"]
                    == str(authoritative["delivery_id"])
                    == rr["delivery_id"]
                )
                assert stored_intent["work_id"] == str(authoritative["work_id"]) and stored_intent[
                    "attempt_id"
                ] == str(authoritative["attempt_id"])
                body = base64.b64decode(stored_intent["body"], validate=True)
                assert hashlib.sha256(body).hexdigest() == authoritative["result_sha256"]
                result_row = connection.execute(
                    sql.SQL("SELECT body FROM {}.attempt_results WHERE attempt_id=%s::uuid").format(
                        sql.Identifier(settings().schema)
                    ),
                    (authoritative["attempt_id"],),
                ).fetchone()
                assert result_row is not None and body == bytes(result_row["body"])
                inventory.append(
                    {
                        "delivery_id": rr["delivery_id"],
                        "receipt_id": str(authoritative["receipt_id"]),
                        "receiver_id": str(authoritative["receiver_id"]),
                        "recipient_id": authoritative["recipient_id"],
                        "result_sha256": authoritative["result_sha256"],
                    }
                )
                totals["receipts"] += 1
        STAGE = "owner_cancellation_receipts"
        for path in sorted(folder().glob("cancellation_*.json")):
            saved_cancel = load(path.name)
            authoritative_cancel = connection.execute(
                sql.SQL("SELECT * FROM {}.cancellation_commands WHERE cancellation_id=%s").format(
                    sql.Identifier(settings(case=True).schema)
                ),
                (saved_cancel["cancellation_id"],),
            ).fetchone()
            assert authoritative_cancel is not None
            for key in ("cancellation_id", "task_id", "command_id", "disposition", "created_at"):
                assert authoritative_cancel[key] == saved_cancel[key]
            assert (
                authoritative_cancel["scope_id"] == HELPER.ACTOR.scope_id
                and authoritative_cancel["actor_id"] == HELPER.ACTOR.actor_id
            )
            payload = json.loads(authoritative_cancel["payload_json"])
            assert (
                payload["case_id"] == saved_cancel["case_id"]
                and payload["reason"] == saved_cancel["reason"]
            )
            inventory.append(
                {
                    "cancellation_id": saved_cancel["cancellation_id"],
                    "command_id": saved_cancel["command_id"],
                    "disposition": saved_cancel["disposition"],
                }
            )
        assert totals == {"actions": 10, "applied": 6, "receipts": 2, "results": 12}, totals
        STAGE = "owner_global_counts"
        counts = connection.execute(
            sql.SQL(
                "SELECT (SELECT count(*) FROM {}.result_actions) AS actions,(SELECT count(*) FROM {}.action_intents) AS intents,(SELECT count(*) FROM {}.confirmations) AS confirmations,(SELECT count(*) FROM {}.mutation_effects) AS effects,(SELECT count(*) FROM {}.attempt_results) AS results"
            ).format(
                sql.Identifier(settings().schema),
                *([sql.Identifier(settings(case=True).schema)] * 3),
                sql.Identifier(settings().schema),
            )
        ).fetchone()
        assert counts == {
            "actions": 10,
            "intents": 10,
            "confirmations": 10,
            "effects": 8,
            "results": 12,
        }
        for scenario in ("b_first", "a_first"):
            graph = json.loads((folder() / ("graph_" + scenario + ".json")).read_text())
            assert len(graph) == 2 and sorted(len(r["blockers"]) for r in graph) == [1, 2]
    save(
        "owner_proof.json",
        {
            "status": "passed",
            "exact_reconciliation": True,
            **totals,
            "reconciliation_sha256": inventory_digest(inventory),
        },
    )
    return reply(15, exact_reconciliation=True)


def install() -> dict[str, object]:
    # Local ownership evidence is separate from the authority's versioned marker.
    save(
        "work_owner.json",
        {"marker": MARKER, "schema": settings().schema, "case_schema": settings(case=True).schema},
    )
    install_work_schema(settings())
    upgrade_work_schema_v2(settings())
    upgrade_work_schema_v3(settings())
    upgrade_work_schema_v4(settings())
    HELPER.install(settings(case=True), folder() / "bootstrap_supplier.sqlite3")
    save(
        "receiver.json", {"receiver_id": initialize_result_receiver(folder() / "receiver.sqlite3")}
    )
    return reply(work_version=4, case_version=4)


def cleanup() -> dict[str, object]:
    HELPER.cleanup(settings(case=True))
    with closing(settings().connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
            (settings().schema,),
        ).fetchone()
        if row is not None:
            assert load("work_owner.json") == {
                "marker": MARKER,
                "schema": settings().schema,
                "case_schema": settings(case=True).schema,
            }, "wrong_fixture_owner"
            version = connection.execute(
                sql.SQL("SELECT version FROM {}.schema_metadata WHERE singleton").format(
                    sql.Identifier(settings().schema)
                )
            ).fetchone()
            assert (
                version is not None
                and type(version["version"]) is int
                and version["version"] in WORK_MARKERS
            )
            assert row == {
                "owner": "continuity_migrator",
                "marker": WORK_MARKERS[version["version"]],
            }, "wrong_authority_owner"
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(settings().schema))
            )
        assert connection.execute(
            "SELECT count(*) AS n FROM pg_namespace WHERE nspname=ANY(%s)",
            ([settings().schema, settings(case=True).schema],),
        ).fetchone() == {"n": 0}
    return reply(cleanup_complete=True)


async def run() -> dict[str, object]:
    global STAGE
    STAGE = MODE
    if MODE == "install":
        return install()
    if MODE == "cleanup":
        return cleanup()
    if MODE == "owner-check":
        return owner_check()
    if MODE.startswith("lock-"):
        return cast(
            dict[str, object],
            HELPER.ordered_lock(
                settings(case=True), folder(), "b_first" if MODE == "lock-b-first" else "a_first"
            ),
        )
    if MODE in {"prepare-b-first", "prepare-a-first"}:
        label = "b_first" if MODE == "prepare-b-first" else "a_first"
        await prepare(label)
        return reply(scenario=label, revision=2)
    if MODE in {"action-b-first", "action-a-first"}:
        return await action_order()
    if MODE in {"revise-b-first", "revise-a-first"}:
        return await revise_order()
    if MODE == "finish-b-first":
        return await finish_b()
    if MODE == "finish-a-first":
        return await finish_a()
    if MODE == "cancel-before-intent":
        return await preintent()
    if MODE.startswith("prepare-"):
        label = MODE.removeprefix("prepare-")
        commit = label not in {"precommit", "postcommit"}
        await prepare(label, commit=commit, horizon_ms=8000 if label == "applied" else 60000)
        return reply(scenario=label, intent_committed=commit)
    if MODE.startswith("worker-"):
        return await worker()
    if MODE == "cancel-applied":
        return await cancel_applied()
    if MODE.startswith("cancel-"):
        label = MODE.removeprefix("cancel-")
        disposition = await cancel(label)
        assert disposition == (
            "cancelled_before_dispatch" if label == "claim" else "requested_best_effort"
        )
        return reply(disposition=disposition)
    if MODE.startswith("recover-"):
        return await recover(MODE.removeprefix("recover-"))
    if MODE in {"action-precommit", "action-postcommit"}:
        label = MODE.removeprefix("action-")
        b = Bundle(label, hook=action_hook)
        try:
            await authorize(b, label)
        finally:
            await b.close()
        raise AssertionError("kill_boundary_not_killed")
    assert MODE == "owned-lifetime"
    return await lifetime()


def main() -> int:
    global MODE
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=MODES)
    MODE = parser.parse_args().mode
    environment(MODE)
    try:
        outcome = asyncio.run(run())
    except Exception as error:  # noqa: BLE001 - bounded synthetic fixture diagnostics only
        code = getattr(error, "code", None)
        safe = (
            code
            if type(code) is str and re.fullmatch(r"[a-z_]{1,48}", code)
            else "assertion_failed"
        )
        print(
            json.dumps(
                {
                    "status": "failed",
                    "mode": MODE,
                    "stage": STAGE,
                    "code": safe,
                    "type": type(error).__name__[:48],
                }
            )
        )
        return 1
    print(json.dumps(outcome))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
