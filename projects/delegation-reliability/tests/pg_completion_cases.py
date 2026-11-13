"""Real completion pipeline fixture; product code imports public P1 APIs only."""

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
from collections.abc import Awaitable, Callable
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Protocol

from psycopg import sql

from continuity_lab.action_api import open_action_client
from continuity_lab.case_control_api import CaseControlClient, open_case_control_client
from continuity_lab.delivery_api import open_delivery_client
from continuity_lab.execution_api import open_execution_client
from continuity_lab.postgres_api import (
    Confirmation,
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
)
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkPrincipal,
    WorkScope,
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
    SpecialistClient,
    SpecialistEndpoint,
)
from delegation_reliability.contracts import (
    CAPABILITY,
    DelegationRequest,
    Scope,
    canonical,
    produce_request,
)
from delegation_reliability.security import EvidenceRecord


class Closable(Protocol):
    async def close(self) -> None: ...


SCOPE = Scope("tenant_p3", "account_p3")
POLICY = canonical({"minimum_notice_days": 7, "policy_version": "policy_v1"})
RECIPIENT = "recipient_completion"
OWNER_MODES = frozenset({"install", "owner-check", "cleanup"})
COMMON = {
    "P3_COMPLETE_WORK_SCHEMA",
    "P3_COMPLETE_CASE_SCHEMA",
    "P3_COMPLETE_DIRECTORY",
    "P3_COMPLETE_RECEIVER_ID",
}
MODE_KEYS = {
    "install": COMMON,
    "exercise": COMMON | {"P3_COMPLETE_TOKEN", "P3_COMPLETE_SPECIALIST_PORT"},
    "verify": COMMON | {"P3_COMPLETE_TOKEN", "P3_COMPLETE_SPECIALIST_PORT"},
    "crash": COMMON
    | {"P3_COMPLETE_TOKEN", "P3_COMPLETE_SPECIALIST_PORT", "P3_COMPLETE_COMMIT_MARKER"},
    "verify-crash": COMMON | {"P3_COMPLETE_TOKEN", "P3_COMPLETE_SPECIALIST_PORT"},
    "owner-check": COMMON,
    "cleanup": COMMON,
}
BASE_KEYS = {
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
_ACTIVE_MODE: str | None = None
_DIAGNOSTIC_STAGE = "fixture"


def helper() -> ModuleType:
    # This explicit source fixture is tooling, not imported by the P3 distribution.
    path = Path(__file__).resolve().parents[3] / "local-setup/scripts/p3_case_fixture.py"
    specification = importlib.util.spec_from_file_location("p3_completion_case_helper", path)
    if specification is None or specification.loader is None:
        raise AssertionError("missing_case_fixture")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


CASE_HELPER = helper()


def validate_environment(mode: str) -> None:
    password = (
        "P3_COMPLETE_OWNER_PASSWORD" if mode in OWNER_MODES else "P3_COMPLETE_RUNTIME_PASSWORD"
    )
    required = {"P3_COMPLETE_PG_PORT", password, *MODE_KEYS[mode]}
    if not required <= set(os.environ) or set(os.environ) - required - BASE_KEYS:
        raise AssertionError("unsafe_child_environment")


def folder() -> Path:
    return Path(os.environ["P3_COMPLETE_DIRECTORY"])


def settings(*, case: bool = False, owner: bool = False) -> PostgresSettings:
    if _ACTIVE_MODE is None or owner != (_ACTIVE_MODE in OWNER_MODES):
        raise AssertionError("credential_role_not_allowed")
    name = os.environ["P3_COMPLETE_CASE_SCHEMA" if case else "P3_COMPLETE_WORK_SCHEMA"]
    pattern = r"p3_completion_[0-9a-f]{32}" if case else r"p1_work_completion_[0-9a-f]{32}"
    if re.fullmatch(pattern, name) is None:
        raise AssertionError("unsafe_schema")
    return PostgresSettings(
        port=int(os.environ["P3_COMPLETE_PG_PORT"]),
        schema=name,
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ[
            "P3_COMPLETE_OWNER_PASSWORD" if owner else "P3_COMPLETE_RUNTIME_PASSWORD"
        ],
    )


def directory() -> tuple[WorkDirectory, BearerToken]:
    token = BearerToken(os.environ["P3_COMPLETE_TOKEN"])
    return WorkDirectory(
        {token: WorkPrincipal("completion_actor", WorkScope(SCOPE.tenant_id, SCOPE.account_id))}
    ), token


def case_token() -> BearerToken:
    return BearerToken(os.environ["P3_COMPLETE_TOKEN"])


def state() -> dict[str, object]:
    value = json.loads((folder() / "case.json").read_text())
    assert type(value) is dict
    return value


def binding() -> ActionBinding:
    value = state()
    return ActionBinding(
        "case_completion",
        str(value["task_id"]),
        str(value["case_id"]),
        CASE_HELPER.ACTOR.actor_id,
        CASE_HELPER.ACTOR.scope_id,
        settings(case=True).schema,
    )


def controller() -> CaseControlClient:
    return open_case_control_client(
        actor=CASE_HELPER.ACTOR,
        token=case_token(),
        settings=settings(case=True),
        quote_database=folder() / "supplier.sqlite3",
    )


def cases(control: CaseControlClient) -> ExactManagedCaseAuthority:
    return ExactManagedCaseAuthority(control, scope=SCOPE, bindings=(binding(),))


def request(key: str, revision: int) -> DelegationRequest:
    return produce_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": CAPABILITY,
            "input_schema_version": 1,
            "scope": {"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id},
            "delegation_id": key,
            "case_id": "case_completion",
            "request_revision": revision,
            "context_snapshot": {
                "policy_version": "policy_v1",
                "policy_source_id": "policy_demo",
                "days_before_arrival": 14,
                "note": "Explicit synthetic completion fixture.",
            },
            "evidence": [
                {
                    "source_id": "policy_demo",
                    "version": "source_v1",
                    "sha256": hashlib.sha256(POLICY).hexdigest(),
                    "media_type": "application/json",
                    "byte_length": len(POLICY),
                    "width": None,
                    "height": None,
                }
            ],
            "deadline_at_ms": time.time_ns() // 1_000_000 + 45000,
            "result_route": {"conversation_id": "conversation_completion"},
            "attempt": {"attempt_id": "attempt_proposed", "number": 1},
        }
    )


def evidence(value: DelegationRequest) -> tuple[EvidenceRecord, ...]:
    return (EvidenceRecord(SCOPE, value.evidence[0], POLICY),)


def runner(control: CaseControlClient, value: DelegationRequest) -> DelegationRunner:
    registrations, token = directory()
    from uuid import uuid4

    return DelegationRunner(
        executions=open_execution_client(settings=settings(), directory=registrations, token=token),
        scope=SCOPE,
        owner_id=str(uuid4()),
        specialist=SpecialistClient(
            SpecialistEndpoint(int(os.environ["P3_COMPLETE_SPECIALIST_PORT"])),
            "Bearer " + os.environ["P3_COMPLETE_TOKEN"],
        ),
        case_authority=cases(control),
        evidence=evidence(value),
    )


def delivery(
    result_runner: DelegationRunner,
    value: DelegationRequest,
    hook: Callable[[str], None] | None = None,
    recipient: str = RECIPIENT,
) -> DelegationDeliveryClient:
    registrations, token = directory()
    return DelegationDeliveryClient(
        results=result_runner,
        deliveries=open_delivery_client(settings=settings(), directory=registrations, token=token),
        receiver=open_result_receiver(
            folder() / "receiver.sqlite3",
            receiver_id=os.environ["P3_COMPLETE_RECEIVER_ID"],
            bindings=(ReceiverBinding(WorkScope(SCOPE.tenant_id, SCOPE.account_id), RECIPIENT),),
            harness_failpoint=hook,
        ),
        scope=SCOPE,
        evidence=evidence(value),
        bindings=(DeliveryBinding("case_completion", "conversation_completion", recipient),),
    )


def authorizer(
    result_runner: DelegationRunner,
    value: DelegationRequest,
    hook: Callable[[str], None] | None = None,
) -> DelegationAuthorizer:
    registrations, token = directory()
    return DelegationAuthorizer(
        results=result_runner,
        actions=open_action_client(
            settings=settings(),
            directory=registrations,
            token=token,
            case_settings=settings(case=True),
            case_actor=CASE_HELPER.ACTOR,
            case_token=case_token(),
            harness_failpoint=hook,
        ),
        scope=SCOPE,
        evidence=evidence(value),
        bindings=(binding(),),
    )


async def _barrier(path: Path) -> None:
    deadline = asyncio.get_running_loop().time() + 4
    while not path.is_file():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("barrier_timeout")
        await asyncio.sleep(0.01)


async def exercise() -> dict[str, object]:
    global _DIAGNOSTIC_STAGE
    from continuity_lab.work_api import open_work_client

    _DIAGNOSTIC_STAGE = "case_setup"
    client = open_postgres_client(
        actor=CASE_HELPER.ACTOR,
        token=case_token(),
        settings=settings(case=True),
        quote_database=folder() / "supplier.sqlite3",
    )
    control = controller()
    registrations, token = directory()
    work = open_work_client(settings=settings(), directory=registrations, token=token)
    owned: list[Closable] = []
    tasks: list[Awaitable[object]] = []
    guard_release = threading.Event()
    try:
        accepted = await client.submit(
            idempotency_key="completion_case", request=CASE_HELPER.REQUEST
        )
        (folder() / "case.json").write_text(
            json.dumps({"task_id": accepted.task_id, "case_id": accepted.case_id})
        )
        await asyncio.to_thread(
            CASE_HELPER.inquire,
            settings(case=True),
            folder() / "supplier.sqlite3",
            accepted.task_id,
        )
        await control.revise(
            task_id=accepted.task_id, expected_revision=0, request=CASE_HELPER.ALTERNATE
        )
        await control.revise(
            task_id=accepted.task_id, expected_revision=1, request=CASE_HELPER.REQUEST
        )
        quote_a = await client.prepare_quote(
            task_id=accepted.task_id, expected_revision=2, command_id="quote_a"
        )
        exact = cases(control)
        coordinator = DelegationCoordinator(executions=work, scope=SCOPE, case_authority=exact)
        owned.append(coordinator)
        a = request("delegation_completion_a", 2)
        ar = runner(control, a)
        owned.append(ar)
        submitted_a = await coordinator.submit(a)
        pending = asyncio.create_task(ar.run_once(submitted_a.view.record.work_id, "run_a"))
        tasks.append(pending)
        await _barrier(folder() / "delayed_a.held")
        await control.revise(
            task_id=accepted.task_id, expected_revision=2, request=CASE_HELPER.ALTERNATE
        )
        await control.revise(
            task_id=accepted.task_id, expected_revision=3, request=CASE_HELPER.REQUEST
        )
        quote_b = await client.prepare_quote(
            task_id=accepted.task_id, expected_revision=4, command_id="quote_b"
        )
        (folder() / "delayed_a.release").touch(mode=0o600)
        result_a = await pending
        assert result_a.view.result is not None and result_a.view.applicability == "outdated"
        observed = ["actual_case_v4_issued_policy_result"]
        ad = delivery(ar, a)
        aa = authorizer(ar, a)
        owned.extend((ad, aa))
        for call in (
            ad.deliver_once(submitted_a.view.record.work_id),
            aa.authorize_once(
                submitted_a.view.record.work_id,
                confirmation=Confirmation(quote_a.quote, True),
                command_id="stale_a",
            ),
        ):
            try:
                await call
            except CompletionError as error:
                assert error.code == "not_eligible"
            else:
                raise AssertionError("stale_a_used")
        assert await aa.inspect(submitted_a.view.record.work_id) is None
        observed.append("revision_a_outdated_zero_delivery_or_action")
        _DIAGNOSTIC_STAGE = "current_b"
        b = request("delegation_completion_b", 4)
        br = runner(control, b)
        owned.append(br)
        submitted_b = await coordinator.submit(b)
        wid_b = submitted_b.view.record.work_id
        result_b = await br.run_once(wid_b, "run_b")
        assert result_b.recorded is not None
        assert result_b.view.applicability == "candidate"
        observed.append("current_b_useful_strict_result")

        def ack_loss(stage: str) -> None:
            if stage == "receiver.after_commit":
                raise OSError("synthetic_ack_loss")

        bd = delivery(br, b, ack_loss)
        owned.append(bd)
        delivered = await bd.deliver_once(wid_b)
        assert delivered.snapshot.intent is not None and delivered.snapshot.receipt is not None
        assert delivered.state == "accepted" and delivered.receiver_invoked
        observed.append("receiver_commit_ack_loss_original_receipt")
        wrong = delivery(br, b, recipient="wrong_recipient")
        owned.append(wrong)
        try:
            await wrong.deliver_once(wid_b)
        except CompletionError as error:
            assert error.code == "identity_conflict"
        else:
            raise AssertionError("delivery_retargeted")
        observed.append("changed_delivery_binding_cannot_retarget")
        _DIAGNOSTIC_STAGE = "cancel_race"
        cancel = request("delegation_completion_cancel", 4)
        cr = runner(control, cancel)
        owned.append(cr)
        accepted_c = await coordinator.submit(cancel)
        wid_c = accepted_c.view.record.work_id
        await cr.run_once(wid_c, "run_cancel")

        def hold_guard(stage: str) -> None:
            if stage == "authorize.before_locks":
                (folder() / "guard.held").touch(mode=0o600)
                if not guard_release.wait(4):
                    raise AssertionError("guard_release_timeout")

        ca = authorizer(cr, cancel, hold_guard)
        owned.append(ca)
        pending_action = asyncio.create_task(
            ca.authorize_once(
                wid_c, confirmation=Confirmation(quote_b.quote, True), command_id="cancel_guard"
            )
        )
        tasks.append(pending_action)
        await _barrier(folder() / "guard.held")
        await coordinator.cancel(wid_c, "cancel_after_preflight")
        guard_release.set()
        try:
            await pending_action
        except CompletionError as error:
            assert error.code == "expired"
        else:
            raise AssertionError("cancelled_result_created_intent")
        assert await ca.inspect(wid_c) is None
        observed.append("work_cancel_after_preflight_zero_intent")
        _DIAGNOSTIC_STAGE = "exact_authorization"
        ba = authorizer(br, b)
        owned.append(ba)
        exact_b = Confirmation(quote_b.quote, True)
        action = await ba.authorize_once(wid_b, confirmation=exact_b, command_id="authorize_b")
        assert (
            action.receipt.expected_revision == 4 and action.receipt.intent.quote == quote_b.quote
        )
        observed.append("exact_confirmation_guarded_intent")
        applied = await asyncio.to_thread(
            CASE_HELPER.mutate, settings(case=True), folder() / "supplier.sqlite3", accepted.task_id
        )
        assert applied["status"] == "passed"
        truth = CASE_HELPER.supplier_truth(folder() / "supplier.sqlite3")
        assert truth["applied_calls"] == 1 and len(truth["mutation_receipts"]) == 1
        observed.append("actual_leased_fake_effect_once")
        await coordinator.cancel(wid_b, "after_action")
        replay = await ba.authorize_once(wid_b, confirmation=exact_b, command_id="authorize_b")
        assert replay.reconciled and replay.receipt == action.receipt
        assert (await bd.deliver_once(wid_b)).snapshot == delivered.snapshot
        observed.append("late_work_cancel_preserves_known_facts")
        (folder() / "proof.json").write_text(
            json.dumps(
                {
                    "work_b": wid_b,
                    "result_b_sha": result_b.recorded.sha256,
                    "delivery_id": delivered.snapshot.intent.delivery_id,
                    "receipt_id": delivered.snapshot.receipt.receipt_id,
                    "action_id": action.receipt.action_id,
                    "effect_id": action.receipt.intent.effect_id,
                    "confirmation": exact_b.payload(),
                }
            )
        )
        return {"status": "passed", "cases": observed}
    finally:
        guard_release.set()
        (folder() / "delayed_a.release").touch(mode=0o600, exist_ok=True)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for item in reversed(owned):
            await item.close()
        await work.close()
        await control.close()
        await client.close()


async def verify(*, crash: bool) -> dict[str, object]:
    from continuity_lab.work_api import open_work_client
    from delegation_reliability.contracts import parse_request

    registrations, token = directory()
    work = open_work_client(settings=settings(), directory=registrations, token=token)
    control = controller()
    owned: list[Closable] = []
    try:
        value = await work.find(
            idempotency_key="delegation_completion_crash" if crash else "delegation_completion_b"
        )
        assert value is not None
        req = parse_request(value.payload.body)
        r = runner(control, req)
        owned.append(r)
        d = delivery(r, req)
        owned.append(d)
        outcome = await d.deliver_once(value.work_id)
        assert outcome.state == "accepted" and not outcome.receiver_invoked
        assert outcome.snapshot.receipt is not None
        if not crash:
            proof = json.loads((folder() / "proof.json").read_text())
            assert outcome.snapshot.receipt.receipt_id == proof["receipt_id"]
            a = authorizer(r, req)
            owned.append(a)
            confirmation = parse_confirmation_payload(
                canonical(proof["confirmation"]["quote"]).decode(), explicit=True
            )
            actual = await a.authorize_once(
                value.work_id, confirmation=confirmation, command_id="authorize_b"
            )
            assert actual.reconciled and actual.receipt.action_id == proof["action_id"]
        return {
            "status": "passed",
            "cases": [
                "receiver_commit_sigkill_fresh_reconciliation"
                if crash
                else "fresh_process_original_delivery_action_read"
            ],
        }
    finally:
        for item in reversed(owned):
            await item.close()
        await work.close()
        await control.close()


async def crash() -> None:
    from continuity_lab.work_api import open_work_client

    registrations, token = directory()
    work = open_work_client(settings=settings(), directory=registrations, token=token)
    control = controller()
    req = request("delegation_completion_crash", 4)
    coordinator = DelegationCoordinator(executions=work, scope=SCOPE, case_authority=cases(control))
    r = runner(control, req)

    def hold(stage: str) -> None:
        if stage == "receiver.after_commit":
            target = Path(os.environ["P3_COMPLETE_COMMIT_MARKER"])
            with target.open("x") as stream:
                stream.write(str(os.getpid()) + "\n")
            os.chmod(target, 0o600)
            if not threading.Event().wait(30):
                raise AssertionError("parent_did_not_kill")

    d = delivery(r, req, hold)
    try:
        accepted = await coordinator.submit(req)
        await r.run_once(accepted.view.record.work_id, "run_crash")
        await d.deliver_once(accepted.view.record.work_id)
    finally:
        await d.close()
        await r.close()
        await coordinator.close()
        await control.close()


def owner_check() -> dict[str, object]:
    global _DIAGNOSTIC_STAGE
    _DIAGNOSTIC_STAGE = "owner_work"
    tables = {
        "accepted_work": 4,
        "cancellation_commands": 2,
        "issued_attempts": 4,
        "attempt_results": 4,
        "result_delivery_intents": 2,
        "result_delivery_possible": 2,
        "result_delivery_receipts": 2,
        "result_actions": 1,
    }
    measured: dict[str, int] = {}
    proof = json.loads((folder() / "proof.json").read_text())
    case = json.loads((folder() / "case.json").read_text())
    with closing(settings(owner=True).connect(application_name="continuity-test")) as connection:
        for name, expected in tables.items():
            row = connection.execute(
                sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                    sql.Identifier(settings(owner=True).schema), sql.Identifier(name)
                )
            ).fetchone()
            assert row is not None and row["count"] == expected
            measured[name] = row["count"]
        foreign = connection.execute(
            sql.SQL(
                "SELECT count(*) AS count FROM {}.accepted_work WHERE tenant_id<>'tenant_p3' OR account_id<>'account_p3'"
            ).format(sql.Identifier(settings(owner=True).schema))
        ).fetchone()
        assert foreign is not None and foreign["count"] == 0
        rows = connection.execute(
            sql.SQL(
                "SELECT r.body,r.sha256,w.body AS original FROM {}.attempt_results r JOIN {}.accepted_work w USING(work_id)"
            ).format(*[sql.Identifier(settings(owner=True).schema)] * 2)
        ).fetchall()
        for row in rows:
            assert hashlib.sha256(bytes(row["body"])).hexdigest() == row["sha256"]
        action = connection.execute(
            sql.SQL("SELECT * FROM {}.result_actions").format(
                sql.Identifier(settings(owner=True).schema)
            )
        ).fetchone()
        assert action is not None
        assert str(action["action_id"]) == proof["action_id"]
        assert str(action["work_id"]) == proof["work_b"]
        assert action["result_sha256"] == proof["result_b_sha"]
        assert action["case_schema"] == settings(case=True, owner=True).schema
        assert (action["case_actor_id"], action["case_scope_id"]) == (
            CASE_HELPER.ACTOR.actor_id,
            CASE_HELPER.ACTOR.scope_id,
        )
        assert str(action["case_task_id"]) == case["task_id"]
        assert str(action["case_id"]) == case["case_id"]
        assert action["expected_revision"] == 4
        assert json.loads(action["confirmation_json"]) == proof["confirmation"]
        guarded_result = connection.execute(
            sql.SQL(
                "SELECT r.sha256,r.disposition,r.body,i.work_id::text,i.tenant_id,i.account_id "
                "FROM {}.attempt_results r JOIN {}.issued_attempts i USING(attempt_id) "
                "WHERE r.attempt_id=%s::uuid"
            ).format(*[sql.Identifier(settings(owner=True).schema)] * 2),
            [action["attempt_id"]],
        ).fetchone()
        assert guarded_result is not None and guarded_result["disposition"] == "eligible_at_commit"
        assert guarded_result["sha256"] == action["result_sha256"]
        assert guarded_result["work_id"] == proof["work_b"]
        assert (guarded_result["tenant_id"], guarded_result["account_id"]) == (
            SCOPE.tenant_id,
            SCOPE.account_id,
        )
        assert hashlib.sha256(bytes(guarded_result["body"])).hexdigest() == action["result_sha256"]
        deliveries = connection.execute(
            sql.SQL(
                "SELECT d.delivery_id::text,d.work_id::text,d.attempt_id::text,d.result_sha256,"
                "d.receiver_id::text,d.recipient_id,r.receipt_id::text,r.accepted_at_ms,a.body,a.sha256 "
                "FROM {}.result_delivery_intents d JOIN {}.result_delivery_receipts r USING(delivery_id) "
                "JOIN {}.attempt_results a USING(attempt_id)"
            ).format(*[sql.Identifier(settings(owner=True).schema)] * 3)
        ).fetchall()
        assert len(deliveries) == 2
        assert any(
            row["delivery_id"] == proof["delivery_id"] and row["receipt_id"] == proof["receipt_id"]
            for row in deliveries
        )
        for row in deliveries:
            assert row["receiver_id"] == os.environ["P3_COMPLETE_RECEIVER_ID"]
            assert row["recipient_id"] == RECIPIENT
            assert row["result_sha256"] == row["sha256"]
            assert hashlib.sha256(bytes(row["body"])).hexdigest() == row["sha256"]
    _DIAGNOSTIC_STAGE = "owner_case"
    with closing(
        settings(case=True, owner=True).connect(application_name="continuity-test")
    ) as connection:
        for table, expected in (
            ("action_intents", 1),
            ("mutation_effects", 1),
            ("business_outcomes", 1),
        ):
            row = connection.execute(
                sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                    sql.Identifier(settings(case=True, owner=True).schema), sql.Identifier(table)
                )
            ).fetchone()
            assert row is not None and row["count"] == expected
        effect = connection.execute(
            sql.SQL(
                "SELECT i.intent_id,i.task_id,i.effect_id,i.revision,i.payload_json,e.state,e.dispatch_count,"
                "c.payload_json AS confirmation,c.actor_id,c.scope_id,q.payload_json AS quote "
                "FROM {}.action_intents i JOIN {}.mutation_effects e USING(intent_id) "
                "JOIN {}.confirmations c USING(confirmation_id) JOIN {}.quotes q USING(quote_id)"
            ).format(*[sql.Identifier(settings(case=True, owner=True).schema)] * 4)
        ).fetchone()
        assert effect is not None and effect["state"] == "succeeded"
        assert effect["dispatch_count"] == 1 and effect["effect_id"] == proof["effect_id"]
        assert effect["intent_id"] == str(action["intent_id"])
        assert effect["task_id"] == case["task_id"] and effect["revision"] == 4
        assert json.loads(effect["payload_json"]) == json.loads(action["intent_json"])
        assert json.loads(effect["confirmation"]) == proof["confirmation"]
        assert json.loads(effect["quote"]) == proof["confirmation"]["quote"]
        assert (effect["actor_id"], effect["scope_id"]) == (
            CASE_HELPER.ACTOR.actor_id,
            CASE_HELPER.ACTOR.scope_id,
        )
    _DIAGNOSTIC_STAGE = "owner_receiver"
    with closing(
        sqlite3.connect((folder() / "receiver.sqlite3").as_uri() + "?mode=ro", uri=True)
    ) as connection:
        receiver_rows = connection.execute(
            "SELECT delivery_id,intent_json,receipt_json FROM result_receipts"
        ).fetchall()
        assert len(receiver_rows) == 2
        for delivery_id, intent_json, receipt_json in receiver_rows:
            intent, receipt = json.loads(intent_json), json.loads(receipt_json)
            original = next(row for row in deliveries if row["delivery_id"] == delivery_id)
            assert intent["scope"] == {"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id}
            assert (
                intent["work_id"] == original["work_id"]
                and intent["attempt_id"] == original["attempt_id"]
            )
            assert base64.b64decode(intent["body"], validate=True) == bytes(original["body"])
            assert receipt == {
                key: original[key]
                for key in (
                    "delivery_id",
                    "receipt_id",
                    "receiver_id",
                    "recipient_id",
                    "result_sha256",
                    "accepted_at_ms",
                )
            }
            assert all(
                intent[key] == receipt[key]
                for key in ("delivery_id", "receiver_id", "recipient_id", "result_sha256")
            )
    truth = CASE_HELPER.supplier_truth(folder() / "supplier.sqlite3")
    assert truth["applied_calls"] == 1 and len(truth["mutation_receipts"]) == 1
    assert truth["mutation_receipts"][0]["effect_id"] == proof["effect_id"]
    assert truth["mutation_receipts"][0]["scope_id"] == CASE_HELPER.ACTOR.scope_id
    assert truth["bookings"] == [[CASE_HELPER.ACTOR.scope_id, "DEMO-BK-001", "2030-12-10", 1]]
    return {
        "status": "passed",
        "work_counts": measured,
        "receiver_receipts": len(receiver_rows),
        "case_intents": 1,
        "applied_calls": truth["applied_calls"],
    }


def cleanup() -> dict[str, object]:
    selected = settings(owner=True)
    with closing(selected.connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
            [selected.schema],
        ).fetchone()
        if row is not None:
            assert row["owner"] == "continuity_migrator" and row["marker"] in {
                "continuity-readonly-work-v1",
                "continuity-readonly-work-v2",
                "continuity-readonly-work-v3",
            }
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(selected.schema))
            )
    CASE_HELPER.cleanup(settings(case=True, owner=True))
    return {"status": "passed", "schemas_removed": True}


def main() -> int:
    global _ACTIVE_MODE
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=MODE_KEYS)
    args = parser.parse_args()
    try:
        validate_environment(args.mode)
        _ACTIVE_MODE = args.mode
        if args.mode == "install":
            install_work_schema(settings(owner=True))
            upgrade_work_schema_v2(settings(owner=True))
            upgrade_work_schema_v3(settings(owner=True))
            CASE_HELPER.install(settings(case=True, owner=True), folder() / "supplier.sqlite3")
            initialize_result_receiver(
                folder() / "receiver.sqlite3", receiver_id=os.environ["P3_COMPLETE_RECEIVER_ID"]
            )
            report = {"status": "passed", "work_version": 3, "case_version": 4}
        elif args.mode == "owner-check":
            report = owner_check()
        elif args.mode == "cleanup":
            report = cleanup()
        elif args.mode == "exercise":
            report = asyncio.run(exercise())
        elif args.mode == "verify":
            report = asyncio.run(verify(crash=False))
        elif args.mode == "verify-crash":
            report = asyncio.run(verify(crash=True))
        else:
            asyncio.run(crash())
            raise AssertionError("crash_not_observed")
        print(json.dumps(report))
        return 0
    except Exception:  # noqa: BLE001 - retain fixed stage only, never private dependency details
        print(json.dumps({"status": "failed", "code": _DIAGNOSTIC_STAGE}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
