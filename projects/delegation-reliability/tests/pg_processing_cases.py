"""Actual v2 processing/receipt recovery fixtures; synthetic local data only."""

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
from dataclasses import asdict, replace
from pathlib import Path
from types import ModuleType
from typing import cast
from uuid import UUID, uuid4

from psycopg import sql

from continuity_lab.case_control_api import CaseControlClient, open_case_control_client
from continuity_lab.delivery_api import open_delivery_client
from continuity_lab.execution_api import ExecutionLimits, open_execution_client
from continuity_lab.postgres_api import open_postgres_client
from continuity_lab.receiver_api import (
    ReceiverBinding,
    initialize_result_receiver,
    open_result_receiver,
)
from continuity_lab.result_feed_api import open_result_feed_client
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
    WorkPayload,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from delegation_reliability import (
    ActionBinding,
    CaseSnapshot,
    CompletionPolicy,
    CompletionProcessor,
    DelegationDeliveryClient,
    DelegationRunner,
    DeliveryBinding,
    ExactManagedCaseAuthority,
    ProcessingDeliveryPort,
    ProjectionProjector,
    SpecialistResultObservation,
)
from delegation_reliability.contracts import (
    Attempt,
    DelegationRequest,
    Scope,
    canonical,
    encode_request,
    encode_result,
    parse_result,
    produce_request,
)
from delegation_reliability.delivery_contract import DelegationDelivery
from delegation_reliability.processing_api import open_processing_client
from delegation_reliability.processing_models import ProcessingAcknowledgement
from delegation_reliability.projection_admin import (
    install_projection_schema,
    upgrade_projection_schema_v2,
)
from delegation_reliability.projection_api import open_projection_client
from delegation_reliability.projection_models import (
    ProjectionBinding,
    ProjectionError,
    ProjectionLimits,
    parse_projected,
)
from delegation_reliability.security import EvidenceRecord

CASES = (
    "projection_v2_backup_restore_upgrade",
    "rejected_history_terminal_ack",
    "postbegin_absence_unknown_unacked",
    "later_current_result_progresses_past_gap",
    "fresh_gap_cursor_resume",
    "receiver_commit_kill_original_reconciliation",
    "ack_precommit_kill_fresh_resume",
    "ack_postcommit_kill_original",
    "concurrent_terminal_ack_original",
    "wrong_attempt_or_digest_receipt_rejected",
    "immutable_policy_no_retarget",
    "stale_projection_fresh_applicability",
    "known_receipt_survives_outage_cancel",
    "source_scope_unavailable_zero_ack",
    "bounded_wrap_replay_capacity",
    "independent_identity_reconciliation_cleanup",
)
OWNER_MODES = {"install", "upgrade-crash", "restore-upgrade", "locks", "owner-check", "cleanup"}
MODES = OWNER_MODES | {
    "seed",
    "crash-begin",
    "crash-ack-before",
    "verify-gap",
    "crash-ack-after",
    "verify-ack-after",
    "crash-receiver",
    "resume-receiver",
    "race-a",
    "race-b",
    "verify",
}
COMMON = {
    "P3_PROCESS_WORK_SCHEMA",
    "P3_PROCESS_CASE_SCHEMA",
    "P3_PROCESS_SCHEMA",
    "P3_PROCESS_DIRECTORY",
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
SCOPE = Scope("tenant_p3", "account_p3")
POLICY = canonical({"minimum_notice_days": 7, "policy_version": "policy_v1"})
MODE = ""
STAGE = "fixture"


def helper() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "local-setup/scripts/p3_case_fixture.py"
    spec = importlib.util.spec_from_file_location("p3_projection_case_helper", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPER = helper()


def folder() -> Path:
    value = Path(os.environ["P3_PROCESS_DIRECTORY"])
    assert value.is_absolute() and value.is_dir() and not value.is_symlink()
    return value


def save(name: str, value: object) -> None:
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    assert len(raw) < 32768
    fd = os.open(folder() / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)


def load(name: str) -> dict[str, object]:
    value = json.loads((folder() / name).read_text())
    assert type(value) is dict
    return value


def settings(kind: str = "work", *, owner: bool = False, cap: bool = False) -> PostgresSettings:
    assert owner == (MODE in OWNER_MODES)
    schema = os.environ[
        {
            "work": "P3_PROCESS_WORK_SCHEMA",
            "case": "P3_PROCESS_CASE_SCHEMA",
            "projection": "P3_PROCESS_SCHEMA",
        }[kind]
    ]
    pattern = {
        "work": r"p1_work_processing_[0-9a-f]{32}",
        "case": r"p3_completion_[0-9a-f]{32}",
        "projection": r"p3_projection_[0-9a-f]{32}",
    }[kind]
    assert re.fullmatch(pattern, schema)
    if cap:
        assert kind == "projection"
        schema += "_cap"
    return PostgresSettings(
        port=int(os.environ["P3_PROCESS_PG_PORT"]),
        schema=schema,
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ[
            "P3_PROCESS_OWNER_PASSWORD" if owner else "P3_PROCESS_RUNTIME_PASSWORD"
        ],
    )


def directory(*, foreign: bool = False) -> tuple[WorkDirectory, BearerToken]:
    token = BearerToken(os.environ["P3_PROCESS_TOKEN"])
    scope = (
        WorkScope("foreign", "private") if foreign else WorkScope(SCOPE.tenant_id, SCOPE.account_id)
    )
    return WorkDirectory({token: WorkPrincipal("projection_actor", scope)}), token


def control() -> CaseControlClient:
    return open_case_control_client(
        actor=HELPER.ACTOR,
        token=BearerToken(os.environ["P3_PROCESS_TOKEN"]),
        settings=settings("case"),
        quote_database=folder() / "supplier.sqlite3",
    )


def cases(client: CaseControlClient) -> ExactManagedCaseAuthority:
    value = load("case.json")
    return ExactManagedCaseAuthority(
        client,
        scope=SCOPE,
        bindings=(
            ActionBinding(
                "case_projection",
                str(value["task_id"]),
                str(value["case_id"]),
                HELPER.ACTOR.actor_id,
                HELPER.ACTOR.scope_id,
                settings("case").schema,
            ),
        ),
    )


def request(number: int, revision: int = 2) -> DelegationRequest:
    return produce_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": "booking.evaluate_policy",
            "input_schema_version": 1,
            "scope": {"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id},
            "delegation_id": "projection_" + str(number),
            "case_id": "case_projection",
            "request_revision": revision,
            "context_snapshot": {
                "policy_version": "policy_v1",
                "policy_source_id": "policy_demo",
                "days_before_arrival": 14,
                "note": "Explicit synthetic projection fixture.",
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
            "deadline_at_ms": time.time_ns() // 1_000_000 + 60000,
            "result_route": {"conversation_id": "conversation_projection"},
            "attempt": {"attempt_id": "attempt_proposed", "number": 1},
        }
    )


def policy_result(value: DelegationRequest) -> bytes:
    data = json.loads(
        (Path(__file__).resolve().parents[3] / "contracts/delegation/v1.json").read_text()
    )
    result = parse_result(canonical(data["result"]))
    return encode_result(
        replace(
            result,
            scope=value.scope,
            delegation_id=value.delegation_id,
            case_id=value.case_id,
            request_revision=value.request_revision,
            input_fingerprint=value.input_fingerprint,
            attempt_id=value.attempt.attempt_id,
            completed_at_ms=time.time_ns() // 1_000_000,
        )
    )


async def seed() -> dict[str, object]:
    client = open_postgres_client(
        actor=HELPER.ACTOR,
        token=BearerToken(os.environ["P3_PROCESS_TOKEN"]),
        settings=settings("case"),
        quote_database=folder() / "supplier.sqlite3",
    )
    ctl = control()
    registrations, token = directory()
    work = open_work_client(settings=settings(), directory=registrations, token=token)
    execution = open_execution_client(settings=settings(), directory=registrations, token=token)
    try:
        case = await client.submit(idempotency_key="projection_case", request=HELPER.REQUEST)
        save("case.json", {"task_id": case.task_id, "case_id": case.case_id})
        await asyncio.to_thread(
            HELPER.inquire, settings("case"), folder() / "supplier.sqlite3", case.task_id
        )
        await ctl.revise(task_id=case.task_id, expected_revision=0, request=HELPER.ALTERNATE)
        await ctl.revise(task_id=case.task_id, expected_revision=1, request=HELPER.REQUEST)
        originals = []
        for number in range(7):
            value = request(number)
            accepted = await work.submit(
                idempotency_key=value.delegation_id,
                payload=WorkPayload(
                    "booking.evaluate_policy", encode_request(value), value.deadline_at_ms
                ),
            )
            grant = (
                await execution.issue(
                    work_id=accepted.record.work_id,
                    owner_id=str(uuid4()),
                    command_id="projection_issue_" + str(number),
                )
            ).attempt
            transport = replace(
                value, attempt=Attempt("attempt_" + UUID(grant.attempt_id).hex, grant.number)
            )
            body = b"{}" if number == 0 else policy_result(transport)
            result = await execution.complete(attempt=grant, body=body)
            assert result.disposition == "eligible_at_commit"
            originals.append(
                {
                    "work_id": accepted.record.work_id,
                    "attempt_id": grant.attempt_id,
                    "issue_command_id": grant.command_id,
                    "tenant_id": SCOPE.tenant_id,
                    "account_id": SCOPE.account_id,
                    "result_sha256": result.sha256,
                    "request_sha256": accepted.record.payload.sha256,
                    "delegation_id": value.delegation_id,
                }
            )
            await asyncio.sleep(0.005)
        save("originals.json", {"results": originals})
        projected = projector(ctl)
        try:
            for _ in range(2):
                await projected.project_once(limit=4)
        finally:
            await projected.close()
        probe = open_projection_client(
            settings=settings("projection"),
            directory=registrations,
            token=token,
            source_id=source(),
        )
        try:
            assert (await probe.checkpoint()).sequence == 7
        finally:
            await probe.close()
    finally:
        await asyncio.gather(client.close(), ctl.close(), work.close(), execution.close())
    return {"status": "passed", "source_results": 7, "projected_results": 7}


def source() -> str:
    return str(load("source.json")["source_id"])


def projector(
    ctl: CaseControlClient, *, cap: bool = False, hook: Callable[[str], None] | None = None
) -> ProjectionProjector:
    registrations, token = directory()
    value = request(0)
    return ProjectionProjector(
        events=open_result_feed_client(settings=settings(), directory=registrations, token=token),
        executions=open_execution_client(settings=settings(), directory=registrations, token=token),
        projections=open_projection_client(
            settings=settings("projection", cap=cap),
            directory=registrations,
            token=token,
            source_id=source(),
            harness_failpoint=hook,
        ),
        scope=SCOPE,
        evidence=(EvidenceRecord(SCOPE, value.evidence[0], POLICY),),
        case_authority=cases(ctl),
        timeout_ms=10000,
    )


def example() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "examples/result_processing.py"
    spec = importlib.util.spec_from_file_location("p3_processing_public_example", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXAMPLE = example()


def policy() -> CompletionPolicy:
    return CompletionPolicy(
        str(load("receiver.json")["receiver_id"]),
        (DeliveryBinding("case_projection", "conversation_projection", "recipient_processing"),),
    )


def evidence() -> tuple[EvidenceRecord, ...]:
    return (EvidenceRecord(SCOPE, request(0).evidence[0], POLICY),)


def hold(stage: str) -> None:
    match = {
        "upgrade-crash": ("processing.upgrade.before_commit", "upgrade_commit"),
        "crash-begin": ("delivery_begin.after_commit", "delivery_begin"),
        "crash-ack-before": ("processing.ack.before_commit", "ack_before"),
        "crash-ack-after": ("processing.ack.after_commit", "ack_after"),
        "crash-receiver": ("receiver.after_commit", "receiver_commit"),
        "race-a": ("processing.ack.before_commit", "processing_race"),
    }
    if MODE not in match or stage != match[MODE][0]:
        return
    name = match[MODE][1]
    reached = Path(os.environ["P3_PROCESS_BARRIER"])
    assert reached == folder() / (name + ".reached")
    fd = os.open(reached, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(str(os.getpid()) + "\n")
    deadline = time.monotonic() + 8
    while not (folder() / (name + ".released")).exists():
        assert time.monotonic() < deadline, "barrier_timeout"
        time.sleep(0.005)
    assert (folder() / (name + ".released")).read_text() == str(os.getpid()) + "\n"


def v1_rows() -> dict[str, object]:
    value = settings("projection", owner=True)
    with closing(value.connect(application_name="continuity-test")) as c:
        result = {}
        for table in ("projection_metadata", "projection_checkpoint", "projected_results"):
            rows = c.execute(
                sql.SQL("SELECT * FROM {}.{} ORDER BY 1").format(
                    sql.Identifier(value.schema), sql.Identifier(table)
                )
            ).fetchall()
            result[table] = json.loads(json.dumps(rows, default=str))
        return result


def install() -> dict[str, object]:
    install_work_schema(settings(owner=True))
    upgrade_work_schema_v2(
        settings(owner=True), limits=ExecutionLimits(max_active=2, lease_ms=10000)
    )
    upgrade_work_schema_v3(settings(owner=True))
    upgrade_work_schema_v4(settings(owner=True))
    HELPER.install(settings("case", owner=True), folder() / "supplier.sqlite3")
    with closing(settings(owner=True).connect(application_name="continuity-test")) as c:
        row = c.execute(
            sql.SQL("SELECT source_id::text FROM {}.result_feed_source").format(
                sql.Identifier(settings(owner=True).schema)
            )
        ).fetchone()
        assert row is not None
        save("source.json", {"source_id": row["source_id"]})
    install_projection_schema(
        settings("projection", owner=True),
        binding=ProjectionBinding(source(), WorkScope(SCOPE.tenant_id, SCOPE.account_id)),
        limits=ProjectionLimits(8),
    )
    receiver = initialize_result_receiver(folder() / "receiver.sqlite3")
    save("receiver.json", {"receiver_id": receiver})
    return {"status": "passed", "work_version": 4, "case_version": 4, "projection_version": 1}


def upgrade_crash() -> None:
    rows = v1_rows()
    saved_rows = rows["projected_results"]
    assert type(saved_rows) is list and len(saved_rows) == 7
    save("backup-v1.json", {"schema_version": 1, "rows": rows})
    upgrade_projection_schema_v2(
        settings("projection", owner=True), policy=policy(), harness_failpoint=hold
    )
    raise AssertionError("upgrade_crash_not_observed")


def restore_upgrade() -> dict[str, object]:
    backup = load("backup-v1.json")
    assert backup["schema_version"] == 1 and backup["rows"] == v1_rows()
    rows = backup["rows"]
    assert type(rows) is dict
    value = settings("projection", owner=True)
    with closing(value.connect(application_name="continuity-test")) as c:
        marker = c.execute(
            "SELECT obj_description(oid,'pg_namespace') AS marker,pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname=%s",
            [value.schema],
        ).fetchone()
        assert marker == {
            "marker": "delegation-result-projection-v1",
            "owner": "continuity_migrator",
        }
        c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(value.schema)))
    install_projection_schema(
        value,
        binding=ProjectionBinding(source(), WorkScope(SCOPE.tenant_id, SCOPE.account_id)),
        limits=ProjectionLimits(8),
    )
    with closing(value.connect(application_name="continuity-test")) as c, c.transaction():
        for r in rows["projected_results"]:
            c.execute(
                sql.SQL(
                    "INSERT INTO {}.projected_results VALUES(%s,%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s)"
                ).format(sql.Identifier(value.schema)),
                [
                    r[k]
                    for k in (
                        "event_sequence",
                        "event_id",
                        "work_id",
                        "attempt_id",
                        "result_sha256",
                        "event_sha256",
                        "body_json",
                        "body_sha256",
                    )
                ],
            )
        point = rows["projection_checkpoint"][0]
        c.execute(
            sql.SQL(
                "UPDATE {}.projection_checkpoint SET sequence=%s,record_count=%s WHERE singleton"
            ).format(sql.Identifier(value.schema)),
            [point["sequence"], point["record_count"]],
        )
    assert v1_rows() == rows
    upgrade_projection_schema_v2(value, policy=policy())
    upgrade_projection_schema_v2(value, policy=policy())
    install_projection_schema(
        value,
        binding=ProjectionBinding(source(), WorkScope(SCOPE.tenant_id, SCOPE.account_id)),
        limits=ProjectionLimits(8),
    )
    try:
        upgrade_projection_schema_v2(
            value, policy=CompletionPolicy(str(uuid4()), policy().bindings)
        )
        raise AssertionError("retarget_allowed")
    except ProjectionError as error:
        assert error.code == "identity_conflict"
    return {
        "status": "passed",
        "projection_version": 2,
        "backup_restore": True,
        "cases": [CASES[0]],
    }


class NeverInvoke:
    async def invoke_observed(self, value: DelegationRequest) -> SpecialistResultObservation:
        raise AssertionError("unexpected_invocation")

    async def close(self) -> None:
        pass


class Bundle:
    def __init__(
        self,
        *,
        wrong_receipt: DelegationDelivery | None = None,
        case_unavailable: bool = False,
        processing_hook: Callable[[str], None] | None = None,
    ) -> None:
        registrations, token = directory()
        self.control = control()

        class Unavailable:
            async def snapshot(self, *, case_id: str) -> CaseSnapshot:
                raise RuntimeError("case_unavailable")

        authority = Unavailable() if case_unavailable else cases(self.control)
        self.runner = DelegationRunner(
            executions=open_execution_client(
                settings=settings(), directory=registrations, token=token
            ),
            scope=SCOPE,
            owner_id=str(uuid4()),
            specialist=NeverInvoke(),
            case_authority=authority,
            evidence=evidence(),
        )
        self.delivery = DelegationDeliveryClient(
            results=self.runner,
            deliveries=open_delivery_client(
                settings=settings(), directory=registrations, token=token, harness_failpoint=hold
            ),
            receiver=open_result_receiver(
                folder() / "receiver.sqlite3",
                receiver_id=policy().receiver_id,
                bindings=(
                    ReceiverBinding(
                        WorkScope(SCOPE.tenant_id, SCOPE.account_id), "recipient_processing"
                    ),
                ),
                harness_failpoint=hold,
            ),
            scope=SCOPE,
            evidence=evidence(),
            bindings=policy().bindings,
        )
        self.metadata = open_processing_client(
            settings=settings("projection"),
            directory=registrations,
            token=token,
            source_id=source(),
            policy=policy(),
            harness_failpoint=hold if processing_hook is None else processing_hook,
        )
        self.feed = open_result_feed_client(
            settings=settings(), directory=registrations, token=token
        )
        self._wrong = wrong_receipt is not None
        delivery = self.delivery
        port: ProcessingDeliveryPort
        if wrong_receipt is not None:

            class Wrong:
                scope = delivery.scope
                receiver_id = delivery.receiver_id
                bindings = delivery.bindings

                async def inspect(self, work_id: str) -> DelegationDelivery:
                    assert wrong_receipt is not None
                    return wrong_receipt

                async def deliver_once(self, work_id: str) -> DelegationDelivery:
                    raise AssertionError("unexpected_send")

                async def close(self) -> None:
                    pass

            port = Wrong()
        else:
            port = delivery
        self.processor = CompletionProcessor(
            processing=self.metadata,
            source=self.feed,
            delivery=port,
            results=self.runner,
            scope=SCOPE,
            evidence=evidence(),
            timeout_ms=10000,
        )

    async def close(self) -> None:
        await self.processor.close()
        if self._wrong:
            await self.delivery.close()
        await asyncio.gather(self.runner.close(), self.control.close())


def originals() -> list[dict[str, str]]:
    rows = load("originals.json")["results"]
    assert type(rows) is list
    return rows


async def ack(bundle: Bundle, sequence: int) -> ProcessingAcknowledgement | None:
    row = load("original8.json") if sequence == 8 else originals()[sequence - 1]
    found = await bundle.feed.read(limit=8)
    event = next(e for e in found.events if e.work_id == row["work_id"])
    return cast(
        ProcessingAcknowledgement | None,
        await EXAMPLE.inspect_ack(bundle.metadata, event_id=event.event_id),
    )


async def verify_gap() -> dict[str, object]:
    b = Bundle()
    try:
        point = await b.metadata.checkpoint()
        assert (point.terminal_watermark, point.scan_after, point.terminal_count) == (1, 2, 1)
        assert await ack(b, 2) is None and await ack(b, 3) is None
        result = await EXAMPLE.process_results(b.processor, limit=1)
        assert result.outcomes[0].sequence == 3 and result.outcomes[0].state == "acknowledged"
        assert (result.after.terminal_watermark, result.after.terminal_count) == (1, 2)
        receipt = await ack(b, 3)
        assert receipt is not None and receipt.receipt is not None
        save("ack3.json", receipt.payload())
        # The original v1 public reader remains usable over owner-upgraded v2.
        registrations, token = directory()
        probe = open_projection_client(
            settings=settings("projection"),
            directory=registrations,
            token=token,
            source_id=source(),
        )
        try:
            assert (await probe.checkpoint()).sequence == 7
            row = await probe.get(
                work_id=originals()[0]["work_id"], attempt_id=originals()[0]["attempt_id"]
            )
            assert row is not None and row.validation == "rejected"
        finally:
            await probe.close()
        return {"status": "passed", "cases": [CASES[n] for n in (1, 2, 3, 4, 6)]}
    finally:
        await b.close()


async def verify_ack_after() -> dict[str, object]:
    b = Bundle()
    try:
        known = await ack(b, 4)
        assert known is not None and known.receipt is not None
        save("ack4.json", known.payload())
        assert (await b.metadata.checkpoint()).scan_after == 4
        return {"status": "passed", "cases": [CASES[7]]}
    finally:
        await b.close()


async def crash() -> None:
    b = Bundle()
    try:
        await EXAMPLE.process_results(
            b.processor, limit=2 if MODE in {"crash-begin", "crash-ack-before"} else 1
        )
        raise AssertionError("crash_not_observed")
    finally:
        await b.close()


async def resume_receiver() -> dict[str, object]:
    b = Bundle()
    try:
        result = await EXAMPLE.process_results(b.processor, limit=1)
        assert result.outcomes[0].sequence == 5 and result.outcomes[0].state == "acknowledged"
        known = await ack(b, 5)
        assert known is not None and known.receipt is not None
        save("ack5.json", known.payload())
        sixth = originals()[5]
        delivered = await b.delivery.deliver_once(sixth["work_id"])
        assert delivered.snapshot.receipt is not None
        other = await b.delivery.inspect(originals()[2]["work_id"])
        wrong = Bundle(wrong_receipt=other)
        try:
            try:
                await EXAMPLE.process_results(wrong.processor, limit=1)
                raise AssertionError("foreign_receipt_acknowledged")
            except ProjectionError as error:
                assert error.code == "identity_conflict"
            assert await ack(wrong, 6) is None
        finally:
            await wrong.close()
        task = str(load("case.json")["task_id"])
        await b.control.revise(task_id=task, expected_revision=2, request=HELPER.ALTERNATE)
        await b.control.revise(task_id=task, expected_revision=3, request=HELPER.REQUEST)
        registrations, token = directory()
        work = open_work_client(settings=settings(), directory=registrations, token=token)
        try:
            await work.cancel(work_id=sixth["work_id"], command_id="processing_late_cancel")
            await work.cancel(
                work_id=originals()[1]["work_id"], command_id="processing_unknown_cancel"
            )
        finally:
            await work.close()
        unavailable = Bundle(case_unavailable=True)
        try:
            result = await EXAMPLE.process_results(unavailable.processor, limit=1)
            assert result.outcomes[0].sequence == 6 and result.outcomes[0].state == "acknowledged"
            known = await ack(unavailable, 6)
            assert known is not None and known.receipt == delivered.snapshot.receipt
            save("ack6.json", known.payload())
        finally:
            await unavailable.close()
        entered, release = threading.Event(), threading.Event()

        def snapshot_hook(stage: str) -> None:
            if stage == "processing.snapshot.established":
                entered.set()
                assert release.wait(5)

        concurrent = Bundle(processing_hook=snapshot_hook)
        processing_task = asyncio.create_task(
            EXAMPLE.process_results(concurrent.processor, limit=1)
        )
        assert await asyncio.to_thread(entered.wait, 3)
        # New result after v2 upgrade exercises the old public projector's WRITE path.
        work = open_work_client(settings=settings(), directory=registrations, token=token)
        execution = open_execution_client(settings=settings(), directory=registrations, token=token)
        try:
            value = request(7, revision=4)
            accepted = await work.submit(
                idempotency_key=value.delegation_id,
                payload=WorkPayload(
                    "booking.evaluate_policy", encode_request(value), value.deadline_at_ms
                ),
            )
            grant = (
                await execution.issue(
                    work_id=accepted.record.work_id,
                    owner_id=str(uuid4()),
                    command_id="processing_eighth_issue",
                )
            ).attempt
            transport = replace(
                value, attempt=Attempt("attempt_" + UUID(grant.attempt_id).hex, grant.number)
            )
            completed = await execution.complete(attempt=grant, body=policy_result(transport))
            assert completed.disposition == "eligible_at_commit"
            save(
                "original8.json",
                {
                    "work_id": accepted.record.work_id,
                    "attempt_id": grant.attempt_id,
                    "issue_command_id": grant.command_id,
                    "request_sha256": accepted.record.payload.sha256,
                    "result_sha256": completed.sha256,
                    "delegation_id": value.delegation_id,
                    "tenant_id": SCOPE.tenant_id,
                    "account_id": SCOPE.account_id,
                },
            )
            p = projector(b.control)
            try:
                projected = await p.project_once(limit=4)
                assert (
                    projected.after.sequence == 8
                    and len(projected.rows) == 1
                    and projected.rows[0].event.work_id == accepted.record.work_id
                )
            finally:
                await p.close()
            release.set()
            result = await processing_task
            assert (
                result.outcomes[0].sequence == 7 and result.outcomes[0].acknowledgement is not None
            )
            assert (
                result.outcomes[0].acknowledgement.reason == "outdated"
                and result.after.projected_through == 7
            )
            assert (await concurrent.metadata.checkpoint()).projected_through == 8
            save(
                "snapshot-isolation.json",
                {
                    "processing_snapshot": 7,
                    "new_projection_checkpoint": 8,
                    "assertion": "coherent_isolation_not_exact_old_interleave_reproduction",
                },
            )
            save("ack7.json", result.outcomes[0].acknowledgement.payload())
            sent = await b.delivery.deliver_once(accepted.record.work_id)
            assert sent.snapshot.receipt is not None
        finally:
            release.set()
            await asyncio.gather(processing_task, return_exceptions=True)
            await concurrent.close()
            await asyncio.gather(work.close(), execution.close())
        return {"status": "passed", "cases": [CASES[n] for n in (5, 9, 11, 12)]}
    finally:
        await b.close()


async def race() -> dict[str, object]:
    b = Bundle()
    try:
        result = await EXAMPLE.process_results(b.processor, limit=1)
        assert len(result.outcomes) == 1 and result.outcomes[0].sequence == 8
        known = result.outcomes[0].acknowledgement
        assert known is not None and known.receipt is not None
        if MODE == "race-a":
            save("ack8-a.json", known.payload())
            return {"status": "passed", "cases": []}
        deadline = time.monotonic() + 1
        while not (folder() / "ack8-a.json").exists():
            assert time.monotonic() < deadline
            await asyncio.sleep(0.005)
        assert known.payload() == load("ack8-a.json")
        save("ack8-b.json", known.payload())
        return {"status": "passed", "cases": [CASES[8]]}
    finally:
        await b.close()


def locks() -> dict[str, object]:
    value = settings("projection", owner=True)
    with closing(value.connect(application_name="continuity-test")) as c:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            rows = c.execute(
                """SELECT a.pid,pg_blocking_pids(a.pid) AS blockers FROM pg_stat_activity a WHERE a.datname=current_database() AND a.usename='livekit_lab' AND EXISTS(SELECT 1 FROM pg_locks l JOIN pg_class r ON r.oid=l.relation JOIN pg_namespace n ON n.oid=r.relnamespace WHERE l.pid=a.pid AND n.nspname=%s AND r.relname='processing_control')""",
                [value.schema],
            ).fetchall()
            pids = {r["pid"] for r in rows}
            if any(any(pid in pids for pid in r["blockers"]) for r in rows):
                return {"status": "passed", "blocked": True}
            time.sleep(0.005)
    raise AssertionError("sql_contention_not_observed")


async def verify() -> dict[str, object]:
    b = Bundle()
    try:
        point = await b.metadata.checkpoint()
        assert (
            point.terminal_watermark,
            point.scan_after,
            point.terminal_count,
            point.projected_through,
        ) == (1, 8, 7, 8)
        for _ in range(2):
            result = await EXAMPLE.process_results(b.processor, limit=8)
            assert (
                len(result.outcomes) == 1
                and result.outcomes[0].sequence == 2
                and result.outcomes[0].state == "unknown"
            )
            assert result.after.terminal_watermark == 1 and result.after.terminal_count == 7
        assert await ack(b, 2) is None
        assert (await b.runner.inspect(originals()[1]["work_id"])).execution.record.cancel_requested
        for invalid in (0, 9, True):
            try:
                await b.processor.process_once(limit=invalid)
                raise AssertionError("invalid_limit_accepted")
            except ProjectionError as error:
                assert error.code == "invalid_input"
        registrations, token = directory()
        try:
            open_processing_client(
                settings=settings("projection"),
                directory=registrations,
                token=token,
                source_id=source(),
                policy=CompletionPolicy(str(uuid4()), policy().bindings),
            )
            raise AssertionError("policy_retarget_accepted")
        except ProjectionError as error:
            assert error.code == "identity_conflict"
        foreign, token = directory(foreign=True)
        try:
            open_processing_client(
                settings=settings("projection"),
                directory=foreign,
                token=token,
                source_id=source(),
                policy=policy(),
            )
            raise AssertionError("foreign_scope_accepted")
        except ProjectionError as foreign_error:
            assert foreign_error.code == "unauthorized"
        try:
            open_processing_client(
                settings=settings("projection"),
                directory=registrations,
                token=token,
                source_id=str(uuid4()),
                policy=policy(),
            )
            raise AssertionError("foreign_source_accepted")
        except ProjectionError as source_error:
            assert source_error.code == "source_mismatch"
        known = await ack(b, 8)
        assert known is not None and known.payload() == load("ack8-a.json")
        return {"status": "passed", "cases": [CASES[n] for n in (10, 13, 14)]}
    finally:
        await b.close()


def owner_check() -> dict[str, object]:
    value = settings("projection", owner=True)
    all_originals = originals() + [load("original8.json")]
    with closing(value.connect(application_name="continuity-test")) as c:
        ps = sql.Identifier(value.schema)
        ws = sql.Identifier(settings(owner=True).schema)
        rows = c.execute(
            sql.SQL("""SELECT p.*,e.event_id::text AS source_event_id,e.work_id::text AS source_work_id,e.attempt_id::text AS source_attempt_id,
            e.tenant_id,e.account_id,i.command_id,w.sha256 AS request_sha,r.sha256 AS result_sha,r.body AS result_body
            FROM {}.projected_results p JOIN {}.result_feed_events e ON e.sequence=p.event_sequence
            JOIN {}.issued_attempts i ON i.attempt_id=e.attempt_id AND i.work_id=e.work_id AND i.tenant_id=e.tenant_id AND i.account_id=e.account_id
            JOIN {}.accepted_work w ON w.work_id=i.work_id JOIN {}.attempt_results r ON r.attempt_id=i.attempt_id
            ORDER BY p.event_sequence""").format(ps, ws, ws, ws, ws)
        ).fetchall()
        assert len(rows) == 8
        backup = load("backup-v1.json")["rows"]
        assert type(backup) is dict
        for index, r in enumerate(rows):
            before = all_originals[index]
            projected = parse_projected(r["body_json"].encode())
            assert projected.event.event_id == r["source_event_id"]
            assert projected.event.work_id == r["source_work_id"] == before["work_id"]
            assert projected.event.attempt_id == r["source_attempt_id"] == before["attempt_id"]
            assert projected.event.issue_command_id == r["command_id"] == before["issue_command_id"]
            assert projected.request_sha256 == r["request_sha"] == before["request_sha256"]
            assert (
                projected.event.result_sha256
                == r["result_sha"]
                == before["result_sha256"]
                == hashlib.sha256(bytes(r["result_body"])).hexdigest()
            )
            assert (r["tenant_id"], r["account_id"]) == (SCOPE.tenant_id, SCOPE.account_id)
            if index < 7:
                assert r["body_json"] == backup["projected_results"][index]["body_json"]
        control_row = c.execute(
            sql.SQL(
                "SELECT terminal_watermark,terminal_count,scan_after FROM {}.processing_control"
            ).format(ps)
        ).fetchone()
        assert control_row == {"terminal_watermark": 1, "terminal_count": 7, "scan_after": 2}
        receipt_truth = {}
        acks = c.execute(
            sql.SQL("SELECT * FROM {}.processing_acks ORDER BY event_sequence").format(ps)
        ).fetchall()
        assert [r["event_sequence"] for r in acks] == [1, 3, 4, 5, 6, 7, 8]
        from delegation_reliability.processing_models import parse_ack

        for a in acks:
            saved = parse_ack(a["body_json"].encode())
            assert saved.event.source_id == source() and saved.policy_sha256 == policy().sha256
            original_projection = parse_projected(
                rows[saved.event.sequence - 1]["body_json"].encode()
            )
            assert (
                saved.event == original_projection.event
                and saved.request_sha256 == original_projection.request_sha256
            )
            assert saved.projected_sha256 == rows[saved.event.sequence - 1]["body_sha256"]
            assert hashlib.sha256(a["body_json"].encode()).hexdigest() == a["body_sha256"]
            if saved.receipt is not None:
                receipt = c.execute(
                    sql.SQL(
                        """SELECT d.work_id::text,d.attempt_id::text,d.receiver_id::text,d.recipient_id,d.result_sha256,r.receipt_id::text,r.accepted_at_ms FROM {}.result_delivery_intents d JOIN {}.result_delivery_receipts r USING(delivery_id) WHERE d.delivery_id=%s::uuid"""
                    ).format(ws, ws),
                    [saved.receipt.delivery_id],
                ).fetchone()
                assert (
                    receipt is not None
                    and receipt["work_id"] == saved.event.work_id
                    and receipt["attempt_id"] == saved.event.attempt_id
                )
                assert (
                    receipt["receipt_id"] == saved.receipt.receipt_id
                    and receipt["result_sha256"] == saved.event.result_sha256
                    and receipt["accepted_at_ms"] == saved.receipt.accepted_at_ms
                )
                assert (
                    receipt["receiver_id"] == policy().receiver_id
                    and receipt["recipient_id"] == "recipient_processing"
                )
                receipt_truth[saved.receipt.delivery_id] = (
                    saved,
                    asdict(saved.receipt),
                    bytes(rows[saved.event.sequence - 1]["result_body"]),
                )
        assert len(receipt_truth) == 5
        for table, n in [
            ("result_delivery_intents", 6),
            ("result_delivery_possible", 6),
            ("result_delivery_receipts", 5),
            ("result_actions", 0),
        ]:
            count_row = c.execute(
                sql.SQL("SELECT count(*) AS n FROM {}.{}").format(ws, sql.Identifier(table))
            ).fetchone()
            assert count_row is not None and count_row["n"] == n
    with closing(
        sqlite3.connect((folder() / "receiver.sqlite3").as_uri() + "?mode=ro", uri=True)
    ) as c:
        received = c.execute(
            "SELECT delivery_id,intent_json,receipt_json FROM result_receipts"
        ).fetchall()
        assert len(received) == 5
        for delivery_id, intent_raw, receipt_raw in received:
            intent, receipt = json.loads(intent_raw), json.loads(receipt_raw)
            saved, expected_receipt, body = receipt_truth[delivery_id]
            assert receipt == expected_receipt
            assert (
                intent["work_id"] == saved.event.work_id
                and intent["attempt_id"] == saved.event.attempt_id
            )
            assert intent["result_sha256"] == saved.event.result_sha256
            assert base64.b64decode(intent["body"], validate=True) == body
            assert intent["delivery_id"] == receipt["delivery_id"] == delivery_id
            assert intent["receiver_id"] == receipt["receiver_id"] == policy().receiver_id
            assert intent["recipient_id"] == receipt["recipient_id"] == "recipient_processing"
            assert intent["scope"] == {"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id}
    with closing(settings("case", owner=True).connect(application_name="continuity-test")) as c:
        for table in ("action_intents", "mutation_effects"):
            count_row = c.execute(
                sql.SQL("SELECT count(*) AS n FROM {}.{}").format(
                    sql.Identifier(settings("case", owner=True).schema), sql.Identifier(table)
                )
            ).fetchone()
            assert count_row is not None and count_row["n"] == 0
    assert HELPER.supplier_truth(folder() / "supplier.sqlite3")["applied_calls"] == 0
    return {"status": "passed", "cases": [CASES[15]]}


def cleanup() -> dict[str, object]:
    for kind, markers in [
        ("projection", {"delegation-result-projection-v1", "delegation-result-projection-v2"}),
        (
            "work",
            {
                "continuity-readonly-work-v1",
                "continuity-readonly-work-v2",
                "continuity-readonly-work-v3",
                "continuity-readonly-work-v4",
            },
        ),
    ]:
        value = settings(kind, owner=True)
        with closing(value.connect(application_name="continuity-test")) as c:
            row = c.execute(
                "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                [value.schema],
            ).fetchone()
            if row is not None:
                assert row["owner"] == "continuity_migrator" and row["marker"] in markers
                c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(value.schema)))
            assert (
                c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", [value.schema]).fetchone()
                is None
            )
    HELPER.cleanup(settings("case", owner=True))
    return {"status": "passed", "schemas_removed": True}


def main() -> int:
    global MODE, STAGE
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=sorted(MODES))
    MODE = parser.parse_args().mode
    try:
        required = COMMON | {
            "P3_PROCESS_PG_PORT",
            "P3_PROCESS_OWNER_PASSWORD" if MODE in OWNER_MODES else "P3_PROCESS_RUNTIME_PASSWORD",
        }
        if MODE not in OWNER_MODES:
            required.add("P3_PROCESS_TOKEN")
        if MODE in {
            "upgrade-crash",
            "crash-begin",
            "crash-ack-before",
            "crash-ack-after",
            "crash-receiver",
            "race-a",
        }:
            required.add("P3_PROCESS_BARRIER")
        assert required <= set(os.environ) and not set(os.environ) - required - BASE
        STAGE = MODE
        if MODE == "install":
            report = install()
        elif MODE == "seed":
            report = asyncio.run(seed())
        elif MODE == "upgrade-crash":
            upgrade_crash()
            raise AssertionError("no_kill")
        elif MODE == "restore-upgrade":
            report = restore_upgrade()
        elif MODE == "verify-gap":
            report = asyncio.run(verify_gap())
        elif MODE == "verify-ack-after":
            report = asyncio.run(verify_ack_after())
        elif MODE == "resume-receiver":
            report = asyncio.run(resume_receiver())
        elif MODE in {"race-a", "race-b"}:
            report = asyncio.run(race())
        elif MODE == "locks":
            report = locks()
        elif MODE == "verify":
            report = asyncio.run(verify())
        elif MODE == "owner-check":
            report = owner_check()
        elif MODE == "cleanup":
            report = cleanup()
        else:
            asyncio.run(crash())
            raise AssertionError("no_kill")
        print(json.dumps(report))
        return 0
    except Exception:  # noqa: BLE001 - fixed stage only, never credential or dependency text
        print(json.dumps({"status": "failed", "code": STAGE}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
