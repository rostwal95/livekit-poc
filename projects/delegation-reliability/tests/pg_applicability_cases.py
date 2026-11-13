"""Actual P3 v3 applicability/retention fixtures; synthetic local authority only."""

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
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from types import ModuleType
from typing import cast
from unittest.mock import patch
from uuid import UUID, uuid4

from psycopg import sql

from continuity_lab.action_api import Confirmation, open_action_client
from continuity_lab.case_control_api import CaseControlClient, open_case_control_client
from continuity_lab.delivery_api import open_delivery_client
from continuity_lab.execution_api import ExecutionLimits, IssuedAttempt, open_execution_client
from continuity_lab.postgres_api import open_postgres_client, parse_confirmation_payload
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
    WorkError,
    WorkPayload,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from delegation_reliability import (
    ActionBinding,
    ApplicabilityRefresh,
    ApplicabilityRefresher,
    CaseSnapshot,
    CompletionError,
    CompletionPolicy,
    CompletionProcessor,
    DelegationAuthorizer,
    DelegationDeliveryClient,
    DelegationRunner,
    DisplayTombstone,
    ExactManagedCaseAuthority,
    ProjectionProjector,
    RefreshPolicy,
    SpecialistResultObservation,
    open_applicability_client,
)
from delegation_reliability.applicability_models import parse_refresh, parse_tombstone
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
from delegation_reliability.delivery_contract import DeliveryBinding
from delegation_reliability.processing_api import open_processing_client
from delegation_reliability.processing_models import parse_ack
from delegation_reliability.projection_admin import (
    install_projection_schema,
    upgrade_projection_schema_v2,
    upgrade_projection_schema_v3,
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
    "projection_v3_nonempty_upgrade_preserves_v2",
    "upgrade_precommit_kill_repeat",
    "populated_refresh_tombstone_backup_restore",
    "late_a_outdated_valid_b_guarded_effect",
    "work_cancel_invalidates_preserves_receipt",
    "case_cancel_monotonic_invalidation",
    "local_deadline_asof_latch",
    "historical_lease_expiry_not_postcommit_invalidation",
    "historical_attempt_exact_identity",
    "case_unavailable_then_recovery",
    "concurrent_local_cas_no_regression",
    "refresh_precommit_kill_resume",
    "refresh_postcommit_kill_original_replay",
    "hidden_display_preserves_replay_truth",
    "hidden_unknown_later_result_progress",
    "scope_source_binding_zero_refresh",
    "retained_capacity_original_replay",
    "independent_identity_reconciliation_cleanup",
)
OWNER_MODES = {"install", "upgrade-crash", "upgrade", "locks", "restore", "owner-check", "cleanup"}
MODES = OWNER_MODES | {
    "seed",
    "refresh-before",
    "resume",
    "refresh-after",
    "replay",
    "race-a",
    "race-b",
    "classify",
    "hide-before",
    "hide-resume",
    "hide-after",
    "progress",
    "verify",
}
COMMON = {
    "P3_REFRESH_WORK_SCHEMA",
    "P3_REFRESH_CASE_SCHEMA",
    "P3_REFRESH_SCHEMA",
    "P3_REFRESH_DIRECTORY",
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
REFRESH_POLICY = RefreshPolicy(32, 8)
MODE = ""
STAGE = "fixture"


def helper() -> ModuleType:
    path = Path(__file__).resolve().parents[3] / "local-setup/scripts/p3_case_fixture.py"
    spec = importlib.util.spec_from_file_location("p3_projection_case_helper", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def folder() -> Path:
    value = Path(os.environ["P3_REFRESH_DIRECTORY"])
    assert value.is_absolute() and value.is_dir() and not value.is_symlink()
    return value


def save(name: str, value: object) -> None:
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    assert len(raw) < 262144
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
            "work": "P3_REFRESH_WORK_SCHEMA",
            "case": "P3_REFRESH_CASE_SCHEMA",
            "projection": "P3_REFRESH_SCHEMA",
        }[kind]
    ]
    pattern = {
        "work": r"p1_work_applicability_[0-9a-f]{32}",
        "case": r"p3_completion_[0-9a-f]{32}",
        "projection": r"p3_projection_[0-9a-f]{32}",
    }[kind]
    assert re.fullmatch(pattern, schema)
    if cap:
        assert kind == "projection"
        schema += "_cap"
    return PostgresSettings(
        port=int(os.environ["P3_REFRESH_PG_PORT"]),
        schema=schema,
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ[
            "P3_REFRESH_OWNER_PASSWORD" if owner else "P3_REFRESH_RUNTIME_PASSWORD"
        ],
    )


def directory(*, foreign: bool = False) -> tuple[WorkDirectory, BearerToken]:
    token = BearerToken(os.environ["P3_REFRESH_TOKEN"])
    scope = (
        WorkScope("foreign", "private") if foreign else WorkScope(SCOPE.tenant_id, SCOPE.account_id)
    )
    return WorkDirectory({token: WorkPrincipal("projection_actor", scope)}), token


def control() -> CaseControlClient:
    return open_case_control_client(
        actor=HELPER.ACTOR,
        token=BearerToken(os.environ["P3_REFRESH_TOKEN"]),
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


def request(number: int, revision: int = 4) -> DelegationRequest:
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


def policy() -> CompletionPolicy:
    return CompletionPolicy(
        str(load("receiver.json")["receiver_id"]),
        (DeliveryBinding("case_projection", "conversation_projection", "recipient_processing"),),
    )


def evidence() -> tuple[EvidenceRecord, ...]:
    return (EvidenceRecord(SCOPE, request(0).evidence[0], POLICY),)


def originals() -> list[dict[str, str]]:
    rows = load("originals.json")["results"]
    assert type(rows) is list
    if (folder() / "original9.json").exists():
        rows = rows + [load("original9.json")["result"]]
    return rows


HELPER = helper()


def example() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "examples/result_applicability.py"
    spec = importlib.util.spec_from_file_location("p3_public_applicability_example", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EXAMPLE = example()
OLD_TABLES = ("projection_checkpoint", "projected_results", "processing_control", "processing_acks")
ALL_TABLES = (
    "projection_metadata",
    "projection_checkpoint",
    "projected_results",
    "processing_control",
    "processing_acks",
    "refresh_control",
    "applicability_refreshes",
    "applicability_heads",
)


def hold(stage: str) -> None:
    match = {
        "upgrade-crash": ("applicability.upgrade.before_commit", "upgrade_commit"),
        "refresh-before": ("applicability.refresh.before_commit", "refresh_before"),
        "refresh-after": ("applicability.refresh.after_commit", "refresh_after"),
        "hide-before": ("applicability.hide.before_commit", "hide_before"),
        "hide-after": ("applicability.hide.after_commit", "hide_after"),
        "race-a": ("applicability.refresh.before_commit", "refresh_race"),
    }
    if MODE not in match or stage != match[MODE][0]:
        return
    name = match[MODE][1]
    reached = Path(os.environ["P3_REFRESH_BARRIER"])
    assert reached == folder() / (name + ".reached")
    fd = os.open(reached, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(str(os.getpid()) + "\n")
    deadline = time.monotonic() + 10
    while not (folder() / (name + ".released")).exists():
        assert time.monotonic() < deadline, "barrier_timeout"
        time.sleep(0.005)
    assert (folder() / (name + ".released")).read_text() == str(os.getpid()) + "\n"


class NeverInvoke:
    async def invoke_observed(self, value: DelegationRequest) -> SpecialistResultObservation:
        raise AssertionError("unexpected_invocation")

    async def close(self) -> None:
        pass


class Bundle:
    def __init__(self) -> None:
        registrations, token = directory()
        self.control = control()
        self.runner = DelegationRunner(
            executions=open_execution_client(
                settings=settings(), directory=registrations, token=token
            ),
            scope=SCOPE,
            owner_id=str(uuid4()),
            specialist=NeverInvoke(),
            case_authority=cases(self.control),
            evidence=evidence(),
        )
        self.delivery = DelegationDeliveryClient(
            results=self.runner,
            deliveries=open_delivery_client(
                settings=settings(), directory=registrations, token=token
            ),
            receiver=open_result_receiver(
                folder() / "receiver.sqlite3",
                receiver_id=policy().receiver_id,
                bindings=(
                    ReceiverBinding(
                        WorkScope(SCOPE.tenant_id, SCOPE.account_id), "recipient_processing"
                    ),
                ),
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
        )
        self.feed = open_result_feed_client(
            settings=settings(), directory=registrations, token=token
        )
        self.processor = CompletionProcessor(
            processing=self.metadata,
            source=self.feed,
            delivery=self.delivery,
            results=self.runner,
            scope=SCOPE,
            evidence=evidence(),
            timeout_ms=10000,
        )

    async def close(self) -> None:
        await self.processor.close()
        await asyncio.gather(self.runner.close(), self.control.close())


class Unavailable:
    async def snapshot(self, *, case_id: str) -> CaseSnapshot:
        raise RuntimeError("synthetic_case_unavailable")


class StaleCase:
    async def snapshot(self, *, case_id: str) -> CaseSnapshot:
        # Explicit injected stale read; independent owner checks retain actual cancellation.
        return CaseSnapshot(SCOPE, case_id, 4, False)


class RefreshBundle:
    def __init__(self, *, cap: bool = False, case_mode: str = "actual") -> None:
        registrations, token = directory()
        self.control = control()
        self.metadata = open_applicability_client(
            settings=settings("projection", cap=cap),
            directory=registrations,
            token=token,
            source_id=source(),
            policy=RefreshPolicy(1, 1) if cap else REFRESH_POLICY,
            harness_failpoint=hold,
        )
        self.feed = open_result_feed_client(
            settings=settings(), directory=registrations, token=token
        )
        self.execution = open_execution_client(
            settings=settings(), directory=registrations, token=token
        )
        authority = (
            Unavailable()
            if case_mode == "unavailable"
            else StaleCase()
            if case_mode == "stale"
            else cases(self.control)
        )
        self.refresher = ApplicabilityRefresher(
            events=self.feed,
            executions=self.execution,
            applicability=self.metadata,
            scope=SCOPE,
            evidence=evidence(),
            case_authority=authority,
            timeout_ms=10000,
        )

    async def close(self) -> None:
        await self.refresher.close()
        await self.control.close()


def target(label: str) -> dict[str, str]:
    assert label in {"a", "b", "c", "d", "e_old", "e_new", "f", "g", "h"}
    if label == "h":
        return next(r for r in originals() if r["label"] == label)
    return cast(dict[str, str], load("result_" + label + ".json"))


def command(name: str) -> str:
    return str(load("commands.json")[name])


async def refresh(
    bundle: RefreshBundle, label: str, name: str, revision: int | None = None
) -> ApplicabilityRefresh:

    row = target(label)
    if revision is None:
        revision = (
            await bundle.metadata.inspect(work_id=row["work_id"], attempt_id=row["attempt_id"])
        ).revision
    return cast(
        ApplicabilityRefresh,
        await EXAMPLE.refresh_result(
            bundle.refresher,
            work_id=row["work_id"],
            attempt_id=row["attempt_id"],
            command_id=command(name),
            expected_revision=revision,
        ),
    )


def table_rows(names: tuple[str, ...], *, cap: bool = False) -> dict[str, object]:
    value = settings("projection", owner=MODE in OWNER_MODES, cap=cap)
    with closing(value.connect(application_name="continuity-test")) as c, c.transaction():
        c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        return {
            name: [
                r["row"]
                for r in c.execute(
                    sql.SQL(
                        "SELECT row_to_json(t)::text AS row FROM {} t ORDER BY row_to_json(t)::text"
                    ).format(sql.Identifier(value.schema, name))
                ).fetchall()
            ]
            for name in names
        }


def install() -> dict[str, object]:
    install_work_schema(settings(owner=True))
    upgrade_work_schema_v2(
        settings(owner=True), limits=ExecutionLimits(max_active=2, max_attempts=3, lease_ms=3000)
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
    save(
        "receiver.json", {"receiver_id": initialize_result_receiver(folder() / "receiver.sqlite3")}
    )
    for cap in (False, True):
        install_projection_schema(
            settings("projection", owner=True, cap=cap),
            binding=ProjectionBinding(source(), WorkScope(SCOPE.tenant_id, SCOPE.account_id)),
            limits=ProjectionLimits(1 if cap else 9),
        )
        upgrade_projection_schema_v2(settings("projection", owner=True, cap=cap), policy=policy())
    names = (
        "before",
        "after",
        "race",
        "a",
        "b_cancel",
        "b_stale",
        "g_missing",
        "g_current",
        "g_cancel",
        "g_stale",
        "g_outage",
        "f",
        "e_old",
        "e_new",
        "cap",
        "cap_over",
        "scope",
        "source",
        "after_restore",
    )
    save("commands.json", {name: str(uuid4()) for name in names})
    return {"status": "passed", "projection_version": 2}


async def seed() -> dict[str, object]:
    global STAGE
    STAGE = "seed_case"
    managed = open_postgres_client(
        actor=HELPER.ACTOR,
        token=BearerToken(os.environ["P3_REFRESH_TOKEN"]),
        settings=settings("case"),
        quote_database=folder() / "supplier.sqlite3",
    )
    ctl = control()
    registrations, token = directory()
    work = open_work_client(settings=settings(), directory=registrations, token=token)
    execution = open_execution_client(settings=settings(), directory=registrations, token=token)
    records = []

    async def issue(label: str, value: DelegationRequest) -> IssuedAttempt:
        accepted = await work.submit(
            idempotency_key=value.delegation_id,
            payload=WorkPayload(
                "booking.evaluate_policy", encode_request(value), value.deadline_at_ms
            ),
        )
        return (
            await execution.issue(
                work_id=accepted.record.work_id,
                owner_id=str(uuid4()),
                command_id="applicability_issue_" + label,
            )
        ).attempt

    async def complete(
        label: str, value: DelegationRequest, grant: IssuedAttempt, *, clarification: bool = False
    ) -> None:
        transport = replace(
            value, attempt=Attempt("attempt_" + UUID(grant.attempt_id).hex, grant.number)
        )
        body = policy_result(transport)
        if clarification:
            body = encode_result(replace(parse_result(body), uncertainty="missing", eligible=None))
        result = await execution.complete(attempt=grant, body=body)
        records.append(
            {
                "label": label,
                "work_id": grant.record.work_id,
                "attempt_id": grant.attempt_id,
                "issue_command_id": grant.command_id,
                "tenant_id": SCOPE.tenant_id,
                "account_id": SCOPE.account_id,
                "result_sha256": result.sha256,
                "request_sha256": grant.record.payload.sha256,
                "delegation_id": value.delegation_id,
                "deadline_at_ms": str(value.deadline_at_ms),
                "disposition": result.disposition,
                "number": str(grant.number),
            }
        )
        save("result_" + label + ".json", records[-1])

    try:
        case = await managed.submit(idempotency_key="applicability_case", request=HELPER.REQUEST)
        save("case.json", {"task_id": case.task_id, "case_id": case.case_id})
        await asyncio.to_thread(
            HELPER.inquire, settings("case"), folder() / "supplier.sqlite3", case.task_id
        )
        await ctl.revise(task_id=case.task_id, expected_revision=0, request=HELPER.ALTERNATE)
        await ctl.revise(task_id=case.task_id, expected_revision=1, request=HELPER.REQUEST)
        qa = await managed.prepare_quote(
            task_id=case.task_id, expected_revision=2, command_id="refresh_quote_a"
        )
        STAGE = "seed_a_running"
        a = request(0, 2)
        STAGE = "seed_issue_a"
        ag = await issue("a", a)
        STAGE = "seed_observe_a"
        assert (await execution.observe(work_id=ag.record.work_id)).status == "running"
        STAGE = "seed_revision_3"
        await ctl.revise(task_id=case.task_id, expected_revision=2, request=HELPER.ALTERNATE)
        STAGE = "seed_revision_4"
        await ctl.revise(task_id=case.task_id, expected_revision=3, request=HELPER.REQUEST)
        STAGE = "seed_quote_b"
        qb = await managed.prepare_quote(
            task_id=case.task_id, expected_revision=4, command_id="refresh_quote_b"
        )
        STAGE = "seed_confirmations"
        save(
            "confirmations.json",
            {
                "a": Confirmation(qa.quote, True).payload(),
                "b": Confirmation(qb.quote, True).payload(),
            },
        )
        STAGE = "seed_request_b"
        b = request(1)
        STAGE = "seed_issue_b"
        bg = await issue("b", b)
        STAGE = "seed_complete_b"
        await complete("b", b, bg)
        STAGE = "seed_complete_a"
        await complete("a", a, ag)
        assert records[-1]["disposition"] == "eligible_at_commit"
        STAGE = "seed_project_b"
        for cap in (False, True):
            p = projector(ctl, cap=cap)
            try:
                assert len((await p.project_once(limit=1)).rows) == 1
            finally:
                await p.close()
        bundle = Bundle()
        try:
            step = await bundle.processor.process_once(limit=1)
            assert step.outcomes[0].state == "acknowledged"
            assert (await bundle.metadata.checkpoint()).terminal_count == 1
            known_b = (await bundle.delivery.inspect(target("b")["work_id"])).snapshot.receipt
            acknowledgement = step.outcomes[0].acknowledgement
            assert known_b is not None and acknowledgement is not None
            save(
                "known_b.json",
                {
                    "delivery": asdict(known_b),
                    "ack": acknowledgement.canonical().decode(),
                },
            )
        finally:
            await bundle.close()
        STAGE = "seed_other_results"
        for label, num in (("c", 2), ("d", 3)):
            value = request(num)
            await complete(label, value, await issue(label, value))
        STAGE = "seed_historical_lease"
        e = request(4)
        eg = await issue("e_old", e)
        cutoff = time.monotonic() + 4
        while (await execution.observe(work_id=eg.record.work_id)).status == "running":
            assert time.monotonic() < cutoff
            await asyncio.sleep(0.01)
        STAGE = "seed_complete_old_lease"
        await complete("e_old", e, eg)
        assert records[-1]["disposition"] == "lease_expired"
        STAGE = "seed_issue_new_lease"
        eg_new = await issue("e_new", e)
        STAGE = "seed_complete_new_lease"
        await complete("e_new", e, eg_new)
        STAGE = "seed_short_deadline"
        short_input = request(5).to_wire()
        short_input.pop("input_fingerprint")
        short_input["deadline_at_ms"] = time.time_ns() // 1_000_000 + 10000
        f = produce_request(short_input)
        await complete("f", f, await issue("f", f))
        STAGE = "seed_clarification"
        g = request(6)
        await complete("g", g, await issue("g", g), clarification=True)
        save("originals.json", {"results": records})
        STAGE = "seed_project_remaining"
        p = projector(ctl)
        try:
            assert len((await p.project_once(limit=8)).rows) == 7
        finally:
            await p.close()
        delivery = open_delivery_client(settings=settings(), directory=registrations, token=token)
        try:
            c = target("c")
            intent = await delivery.prepare(
                work_id=c["work_id"],
                attempt_id=c["attempt_id"],
                result_sha256=c["result_sha256"],
                receiver_id=policy().receiver_id,
                recipient_id="recipient_processing",
            )
            assert (await delivery.begin(intent=intent)).created
            save("possible_c.json", {"delivery_id": intent.delivery_id})
        finally:
            await delivery.close()
        STAGE = "seed_snapshot_v2"
        save("old_v2.json", table_rows(OLD_TABLES))
    finally:
        await asyncio.gather(managed.close(), ctl.close(), work.close(), execution.close())
    return {"status": "passed", "source_results": 8, "projected_results": 8, "old_ack_count": 1}


def upgrade() -> dict[str, object]:
    if MODE == "upgrade-crash":
        upgrade_projection_schema_v3(
            settings("projection", owner=True), policy=REFRESH_POLICY, harness_failpoint=hold
        )
        raise AssertionError("missing_kill")
    assert table_rows(OLD_TABLES) == load("old_v2.json")
    with closing(
        settings("projection", owner=True).connect(application_name="continuity-test")
    ) as c:
        assert c.execute(
            sql.SQL("SELECT version FROM {}.projection_metadata").format(
                sql.Identifier(settings("projection", owner=True).schema)
            )
        ).fetchone() == {"version": 2}
    for cap in (False, True):
        value = settings("projection", owner=True, cap=cap)
        pol = RefreshPolicy(1, 1) if cap else REFRESH_POLICY
        upgrade_projection_schema_v3(value, policy=pol)
        upgrade_projection_schema_v3(value, policy=pol)
        upgrade_projection_schema_v2(value, policy=policy())
        install_projection_schema(
            value,
            binding=ProjectionBinding(source(), WorkScope(SCOPE.tenant_id, SCOPE.account_id)),
            limits=ProjectionLimits(1 if cap else 9),
        )
        try:
            upgrade_projection_schema_v3(
                value, policy=replace(pol, max_commands=pol.max_commands + 1)
            )
        except ProjectionError as error:
            assert error.code == "identity_conflict"
        else:
            raise AssertionError("changed_policy_accepted")
    assert table_rows(OLD_TABLES) == load("old_v2.json")
    return {"status": "passed", "projection_version": 3, "cases": [CASES[0], CASES[1]]}


async def refresh_mode() -> dict[str, object]:
    bundle = RefreshBundle()
    try:
        name, expected = {
            "refresh-before": ("before", 0),
            "resume": ("before", 0),
            "refresh-after": ("after", 1),
            "replay": ("after", 1),
            "race-a": ("race", 2),
            "race-b": ("race", 2),
        }[MODE]
        value = await refresh(bundle, "b", name, expected)
        assert value.classification == "current" and value.revision == expected + 1
        if MODE in {"refresh-before", "refresh-after"}:
            raise AssertionError("missing_kill")
        if MODE == "resume":
            save("first_refresh.json", {"body": value.canonical().decode()})
            return {"status": "passed", "cases": [CASES[11]]}
        if MODE == "replay":
            original = await bundle.metadata.command(command_id=command("after"))
            assert original is not None and original.canonical() == value.canonical()
            assert (await refresh(bundle, "b", "before", 0)).canonical() == str(
                load("first_refresh.json")["body"]
            ).encode()
            return {"status": "passed", "cases": [CASES[12]]}
        if MODE == "race-a":
            save("race_refresh.json", {"body": value.canonical().decode()})
            return {"status": "passed", "revision": 3}
        assert (await bundle.metadata.command(command_id=command("race"))) == value
        try:
            await refresh(bundle, "b", "b_stale", 2)
        except ProjectionError as error:
            assert error.code == "checkpoint_conflict"
        else:
            raise AssertionError("stale_cas_accepted")
        return {"status": "passed", "cases": [CASES[10]]}
    finally:
        await bundle.close()


def locks() -> dict[str, object]:
    value = settings("projection", owner=True)
    with closing(value.connect(application_name="continuity-test")) as c:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            rows = c.execute(
                "SELECT a.pid,pg_blocking_pids(a.pid) AS blockers FROM pg_stat_activity a WHERE a.datname=current_database() AND a.usename='livekit_lab' AND EXISTS(SELECT 1 FROM pg_locks l JOIN pg_class r ON r.oid=l.relation JOIN pg_namespace n ON n.oid=r.relnamespace WHERE l.pid=a.pid AND n.nspname=%s AND r.relname='refresh_control')",
                [value.schema],
            ).fetchall()
            pids = {r["pid"] for r in rows}
            if any(any(pid in pids for pid in r["blockers"]) for r in rows):
                return {"status": "passed", "blocked": True, "blocking_graphs": 1}
            time.sleep(0.005)
    raise AssertionError("sql_contention_not_observed")


def confirmation(label: str) -> Confirmation:
    value = load("confirmations.json")[label]
    assert type(value) is dict and value["explicit"] is True and type(value["quote"]) is dict
    return parse_confirmation_payload(
        json.dumps(value["quote"], sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        explicit=value["explicit"],
    )


async def classify() -> dict[str, object]:
    global STAGE
    bundle = RefreshBundle()
    service = Bundle()
    registrations, token = directory()
    managed = open_postgres_client(
        actor=HELPER.ACTOR,
        token=token,
        settings=settings("case"),
        quote_database=folder() / "supplier.sqlite3",
    )
    work = open_work_client(settings=settings(), directory=registrations, token=token)
    authorizer = DelegationAuthorizer(
        results=service.runner,
        actions=open_action_client(
            settings=settings(),
            directory=registrations,
            token=token,
            case_settings=settings("case"),
            case_actor=HELPER.ACTOR,
            case_token=token,
        ),
        scope=SCOPE,
        evidence=evidence(),
        bindings=(
            ActionBinding(
                "case_projection",
                str(load("case.json")["task_id"]),
                str(load("case.json")["case_id"]),
                HELPER.ACTOR.actor_id,
                HELPER.ACTOR.scope_id,
                settings("case").schema,
            ),
        ),
    )
    try:
        STAGE = "late_a_current_b"
        a = await refresh(bundle, "a", "a")
        b = await bundle.metadata.command(command_id=command("race"))
        assert a.classification == "outdated" and a.retained.highest_case_revision == 4
        assert b is not None and b.classification == "current"
        try:
            await authorizer.authorize_once(
                target("a")["work_id"],
                confirmation=confirmation("a"),
                command_id="applicability_stale_a",
            )
        except CompletionError as error:
            assert error.code == "not_eligible"
        else:
            raise AssertionError("stale_a_authorized")
        assert await authorizer.inspect(target("a")["work_id"]) is None
        authorized = await authorizer.authorize_once(
            target("b")["work_id"],
            confirmation=confirmation("b"),
            command_id="applicability_current_b",
        )
        intent = authorized.receipt.intent
        save(
            "authorized_b.json",
            {
                "action_id": authorized.receipt.action_id,
                "work_id": authorized.receipt.work_id,
                "attempt_id": authorized.receipt.attempt_id,
                "result_sha256": authorized.receipt.result_sha256,
                "expected_revision": authorized.receipt.expected_revision,
                "intent": intent.payload(),
                "confirmation": authorized.receipt.confirmation.payload(),
            },
        )
        await asyncio.to_thread(
            HELPER.mutate,
            settings("case"),
            folder() / "supplier.sqlite3",
            str(load("case.json")["task_id"]),
        )
        assert HELPER.supplier_truth(folder() / "supplier.sqlite3")["applied_calls"] == 1
        STAGE = "lease_and_clarification"
        grant = await bundle.execution.find_issue(command_id=target("e_new")["issue_command_id"])
        assert grant is not None and time.time_ns() // 1_000_000 > grant.lease_until_ms
        late = await refresh(bundle, "e_old", "e_old")
        current = await refresh(bundle, "e_new", "e_new")
        assert late.reason == "historical_lease_expired" and late.current_attempt_number == 2
        assert current.classification == "current"
        missing = RefreshBundle(case_mode="unavailable")
        try:
            assert (await refresh(missing, "g", "g_missing")).classification == "unavailable"
        finally:
            await missing.close()
        clarified = await refresh(bundle, "g", "g_current")
        assert (clarified.classification, clarified.reason) == ("current", "clarification")
        delivered = await service.delivery.deliver_once(target("d")["work_id"])
        assert delivered.snapshot.receipt is not None
        save("known_d.json", {"receipt": asdict(delivered.snapshot.receipt)})
        STAGE = "late_invalidation"
        await work.cancel(work_id=target("b")["work_id"], command_id="refresh_late_work_cancel")
        invalid = await refresh(bundle, "b", "b_cancel")
        assert (
            invalid.reason == "work_cancelled"
            and invalid.observation is not None
            and invalid.observation.execution_status == "result_recorded"
        )
        known = await service.delivery.inspect(target("b")["work_id"])
        assert (
            known.snapshot.receipt is not None
            and asdict(known.snapshot.receipt) == load("known_b.json")["delivery"]
        )
        await managed.cancel(
            task_id=str(load("case.json")["task_id"]), command_id="refresh_late_case_cancel"
        )
        assert (await refresh(bundle, "g", "g_cancel")).reason == "case_cancelled"
        stale = RefreshBundle(case_mode="stale")
        try:
            retained = await refresh(stale, "g", "g_stale")
            assert (
                retained.reason == "case_cancelled"
                and retained.observation is not None
                and retained.observation.case_cancelled is False
            )
        finally:
            await stale.close()
        unavailable = RefreshBundle(case_mode="unavailable")
        try:
            retained = await refresh(unavailable, "g", "g_outage")
            assert (
                retained.reason == "case_cancelled"
                and retained.observation is not None
                and retained.observation.case_status == "unavailable"
            )
        finally:
            await unavailable.close()
        deadline = int(target("f")["deadline_at_ms"])
        cutoff = time.monotonic() + 12
        while time.time_ns() // 1_000_000 <= deadline:
            assert time.monotonic() < cutoff
            await asyncio.sleep(0.01)
        expired = await refresh(bundle, "f", "f")
        assert expired.reason == "deadline_expired_local_as_of"
        original_command = await bundle.metadata.command(command_id=command("before"))
        assert original_command is not None
        assert original_command.canonical() == str(load("first_refresh.json")["body"]).encode()
    finally:
        await authorizer.close()
        await asyncio.gather(bundle.close(), service.close(), managed.close(), work.close())
    return {
        "status": "passed",
        "cases": [CASES[3], CASES[4], CASES[5], CASES[6], CASES[7], CASES[8], CASES[9]],
    }


async def hide_mode() -> dict[str, object]:
    bundle = RefreshBundle()
    row = target("c" if MODE == "hide-after" else "a")
    try:
        before = await EXAMPLE.inspect_result(
            bundle.metadata, work_id=row["work_id"], attempt_id=row["attempt_id"]
        )
        tomb = await EXAMPLE.hide_result(
            bundle.metadata, work_id=row["work_id"], attempt_id=row["attempt_id"]
        )
        if MODE in {"hide-before", "hide-after"}:
            raise AssertionError("missing_kill")
        assert (
            await bundle.metadata.hide_display(work_id=row["work_id"], attempt_id=row["attempt_id"])
            == tomb
        )
        assert (
            await bundle.metadata.display(work_id=row["work_id"], attempt_id=row["attempt_id"])
            == tomb
        )
        after = await bundle.metadata.inspect(work_id=row["work_id"], attempt_id=row["attempt_id"])
        assert before.projection.canonical() == after.projection.canonical()
        assert (
            before.latest is not None
            and after.latest is not None
            and before.latest.canonical() == after.latest.canonical()
        )
        save("hidden_a.json", {"body": tomb.canonical().decode()})
        return {"status": "passed", "cases": [CASES[13]]}
    finally:
        await bundle.close()


async def progress() -> dict[str, object]:
    bundle = RefreshBundle()
    service = Bundle()
    try:
        c = target("c")
        tomb = await bundle.metadata.display(work_id=c["work_id"], attempt_id=c["attempt_id"])
        assert type(tomb) is DisplayTombstone
        saved = (await service.delivery.inspect(c["work_id"])).snapshot
        assert saved.possible and saved.receipt is None and saved.intent is not None
        assert saved.intent.delivery_id == load("possible_c.json")["delivery_id"]
        result = await service.processor.process_once(limit=8)
        assert any(
            o.sequence == tomb.event.sequence and o.state == "unknown" for o in result.outcomes
        )
        # The hidden unresolved event was inspected; later D's exact known receipt progressed.
        event_d = next(
            e
            for e in (await service.feed.read(limit=8)).events
            if e.work_id == target("d")["work_id"]
        )
        ack_d = await service.metadata.acknowledgement(event_id=event_d.event_id)
        assert (
            ack_d is not None
            and ack_d.receipt is not None
            and asdict(ack_d.receipt) == load("known_d.json")["receipt"]
        )
        assert await service.metadata.acknowledgement(event_id=tomb.event.event_id) is None
        await service.processor.process_once(limit=1)
        point = await service.metadata.checkpoint()
        assert (point.terminal_watermark, point.terminal_count, point.scan_after) == (2, 7, 3)
        assert (await service.delivery.inspect(c["work_id"])).state == "unknown"
        save("hidden_c.json", {"body": tomb.canonical().decode()})
    finally:
        await asyncio.gather(bundle.close(), service.close())
    return {"status": "passed", "cases": [CASES[14]]}


def restore() -> dict[str, object]:
    before = table_rows(ALL_TABLES)
    assert all(before[name] for name in ALL_TABLES)
    save(
        "populated_v3.json",
        {"rows": before, "scope": "quiescent_exact_captured_profile_not_stale_branch"},
    )
    value = settings("projection", owner=True)
    with closing(value.connect(application_name="continuity-test")) as c:
        marker = c.execute(
            "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
            [value.schema],
        ).fetchone()
        assert marker == {
            "owner": "continuity_migrator",
            "marker": "delegation-result-projection-v3",
        }
        c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(value.schema)))
    install_projection_schema(
        value,
        binding=ProjectionBinding(source(), WorkScope(SCOPE.tenant_id, SCOPE.account_id)),
        limits=ProjectionLimits(9),
    )
    upgrade_projection_schema_v2(value, policy=policy())
    upgrade_projection_schema_v3(value, policy=REFRESH_POLICY)
    with closing(value.connect(application_name="continuity-test")) as c, c.transaction():
        c.execute(
            sql.SQL("TRUNCATE {} ").format(
                sql.SQL(",").join(sql.Identifier(value.schema, t) for t in ALL_TABLES)
            )
        )
        for name in ALL_TABLES:
            entries = before[name]
            assert type(entries) is list
            for raw in entries:
                c.execute(
                    sql.SQL(
                        "INSERT INTO {} SELECT * FROM json_populate_record(NULL::{},%s::json)"
                    ).format(
                        sql.Identifier(value.schema, name), sql.Identifier(value.schema, name)
                    ),
                    [raw],
                )
    assert table_rows(ALL_TABLES) == before
    upgrade_projection_schema_v3(value, policy=REFRESH_POLICY)
    assert table_rows(ALL_TABLES) == before
    return {
        "status": "passed",
        "cases": [CASES[2]],
        "populated_tables": 8,
        "profile_rows_restored": True,
    }


async def verify() -> dict[str, object]:
    global STAGE
    bundle = RefreshBundle()
    service = Bundle()
    try:
        STAGE = "restored_facts"
        first = await refresh(bundle, "b", "before", 0)
        assert first.canonical() == str(load("first_refresh.json")["body"]).encode()
        c = target("c")
        for label, saved_file in (("a", "hidden_a.json"), ("c", "hidden_c.json")):
            item = target(label)
            tombstone = await bundle.metadata.display(
                work_id=item["work_id"], attempt_id=item["attempt_id"]
            )
            assert type(tombstone) is DisplayTombstone
            assert tombstone.canonical() == str(load(saved_file)["body"]).encode()
        known = await service.delivery.inspect(target("b")["work_id"])
        assert (
            known.snapshot.receipt is not None
            and asdict(known.snapshot.receipt) == load("known_b.json")["delivery"]
        )
        original_ack = await service.metadata.acknowledgement(event_id=first.event.event_id)
        assert (
            original_ack is not None
            and original_ack.canonical() == str(load("known_b.json")["ack"]).encode()
        )
        latest_g = (
            await bundle.metadata.inspect(
                work_id=target("g")["work_id"], attempt_id=target("g")["attempt_id"]
            )
        ).latest
        assert latest_g is not None and latest_g.reason == "case_cancelled"
        STAGE = "scope_and_source_negatives"
        registrations, token = directory(foreign=True)
        try:
            open_applicability_client(
                settings=settings("projection"),
                directory=registrations,
                token=token,
                source_id=source(),
                policy=REFRESH_POLICY,
            )
        except ProjectionError as error:
            assert str(error.code) == "unauthorized"
        else:
            raise AssertionError("foreign_projection_opened")
        registrations, token = directory()
        try:
            open_applicability_client(
                settings=settings("projection"),
                directory=registrations,
                token=token,
                source_id=str(uuid4()),
                policy=REFRESH_POLICY,
            )
        except ProjectionError as error:
            assert str(error.code) == "source_mismatch"
        else:
            raise AssertionError("foreign_source_opened")
        before = table_rows(("refresh_control", "applicability_refreshes", "applicability_heads"))
        try:
            await bundle.refresher.refresh(
                work_id=c["work_id"],
                attempt_id=str(uuid4()),
                command_id=command("scope"),
                expected_revision=0,
            )
        except ProjectionError as error:
            assert error.code == "not_found"
        else:
            raise AssertionError("wrong_attempt_refreshed")
        from continuity_lab.work_api import WorkError

        with patch.object(bundle.feed, "read", side_effect=WorkError("storage_unavailable")):
            try:
                await refresh(bundle, "d", "source", 0)
            except ProjectionError as source_error:
                assert source_error.code == "storage_unavailable"
            else:
                raise AssertionError("source_unavailable_refreshed")
        assert (
            table_rows(("refresh_control", "applicability_refreshes", "applicability_heads"))
            == before
        )
        STAGE = "retained_capacity"
        capped = RefreshBundle(cap=True)
        try:
            original = await refresh(capped, "b", "cap", 0)
            row = target("b")
            await capped.metadata.hide_display(work_id=row["work_id"], attempt_id=row["attempt_id"])
            assert (await refresh(capped, "b", "cap", 0)).canonical() == original.canonical()
            try:
                await refresh(capped, "b", "cap_over", 1)
            except ProjectionError as error:
                assert str(error.code) == "capacity"
            else:
                raise AssertionError("prune_reclaimed_identity_capacity")
        finally:
            await capped.close()
        STAGE = "v3_old_writer"
        work = open_work_client(settings=settings(), directory=registrations, token=token)
        execution = open_execution_client(settings=settings(), directory=registrations, token=token)
        value = request(7)
        try:
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
                    command_id="applicability_after_restore",
                )
            ).attempt
            wire = replace(
                value, attempt=Attempt("attempt_" + UUID(grant.attempt_id).hex, grant.number)
            )
            result = await execution.complete(attempt=grant, body=policy_result(wire))
            entries = originals()
            entries.append(
                {
                    "label": "h",
                    "work_id": grant.record.work_id,
                    "attempt_id": grant.attempt_id,
                    "issue_command_id": grant.command_id,
                    "tenant_id": SCOPE.tenant_id,
                    "account_id": SCOPE.account_id,
                    "result_sha256": result.sha256,
                    "request_sha256": grant.record.payload.sha256,
                    "delegation_id": value.delegation_id,
                    "deadline_at_ms": str(value.deadline_at_ms),
                    "disposition": result.disposition,
                    "number": str(grant.number),
                }
            )
            save("original9.json", {"result": entries[-1]})
            p = projector(bundle.control)
            try:
                projected = await p.project_once(limit=1)
                assert len(projected.rows) == 1 and projected.after.sequence == 9
            finally:
                await p.close()
            view = await refresh(bundle, "h", "after_restore", 0)
            assert view.classification == "invalidated" and view.reason == "case_cancelled"
            await service.processor.process_once(limit=8)
            current = await service.metadata.checkpoint()
            assert (
                current.projected_through == 9
                and current.terminal_count == 8
                and current.terminal_watermark == 2
            )
            assert (
                await service.metadata.acknowledgement(
                    event_id=parse_tombstone(
                        str(load("hidden_c.json")["body"]).encode()
                    ).event.event_id
                )
                is None
            )
        finally:
            await asyncio.gather(work.close(), execution.close())
        # Original accepted input still deduplicates after display hiding and populated restore.
        work = open_work_client(settings=settings(), directory=registrations, token=token)
        try:
            row = target("a")
            old_issue = await bundle.execution.find_issue(command_id=row["issue_command_id"])
            assert old_issue is not None
            replay = await work.submit(
                idempotency_key=old_issue.record.idempotency_key, payload=old_issue.record.payload
            )
            assert not replay.created and replay.record.work_id == row["work_id"]
        finally:
            await work.close()
    finally:
        await asyncio.gather(bundle.close(), service.close())
    return {
        "status": "passed",
        "cases": [CASES[15], CASES[16]],
        "source_results": 9,
        "projected_results": 9,
    }


def owner_check() -> dict[str, object]:
    global STAGE
    value = settings("projection", owner=True)
    proof = load("authorized_b.json")
    proof_intent = proof["intent"]
    proof_confirmation = proof["confirmation"]
    assert type(proof_intent) is dict and type(proof_confirmation) is dict
    ps, ws, cs = (
        sql.Identifier(value.schema),
        sql.Identifier(settings(owner=True).schema),
        sql.Identifier(settings("case", owner=True).schema),
    )
    receipt_truth = {}
    STAGE = "owner_projection_source"
    with closing(value.connect(application_name="continuity-test")) as c:
        rows = c.execute(
            sql.SQL("""SELECT p.*,e.event_id::text AS source_event_id,e.work_id::text AS source_work_id,e.attempt_id::text AS source_attempt_id,e.tenant_id,e.account_id,i.command_id,w.sha256 AS request_sha,r.sha256 AS result_sha,r.body AS result_body
        FROM {}.projected_results p JOIN {}.result_feed_events e ON e.sequence=p.event_sequence
        JOIN {}.issued_attempts i ON i.attempt_id=e.attempt_id AND i.work_id=e.work_id AND i.tenant_id=e.tenant_id AND i.account_id=e.account_id
        JOIN {}.accepted_work w ON w.work_id=i.work_id JOIN {}.attempt_results r ON r.attempt_id=i.attempt_id ORDER BY p.event_sequence""").format(
                ps, ws, ws, ws, ws
            )
        ).fetchall()
        assert len(rows) == len(originals()) == 9
        before = load("old_v2.json")["projected_results"]
        assert type(before) is list
        original_bodies = {
            int(json.loads(raw)["event_sequence"]): str(json.loads(raw)["body_json"])
            for raw in before
        }
        for index, r in enumerate(rows):
            original = originals()[index]
            p = parse_projected(r["body_json"].encode())
            assert p.event.source_id == source()
            assert p.event.event_id == r["source_event_id"]
            assert p.event.work_id == r["source_work_id"] == original["work_id"]
            assert p.event.attempt_id == r["source_attempt_id"] == original["attempt_id"]
            assert p.event.issue_command_id == r["command_id"] == original["issue_command_id"]
            assert p.request_sha256 == r["request_sha"] == original["request_sha256"]
            assert (
                p.event.result_sha256
                == r["result_sha"]
                == original["result_sha256"]
                == hashlib.sha256(bytes(r["result_body"])).hexdigest()
            )
            assert (r["tenant_id"], r["account_id"]) == (SCOPE.tenant_id, SCOPE.account_id)
            if index < 8:
                assert r["body_json"] == original_bodies[p.event.sequence]
        refreshes = c.execute(
            sql.SQL(
                "SELECT * FROM {}.applicability_refreshes ORDER BY event_sequence,revision"
            ).format(ps)
        ).fetchall()
        headrows = c.execute(sql.SQL("SELECT * FROM {}.applicability_heads").format(ps)).fetchall()
        assert refreshes and len(headrows) <= 9
        for r in refreshes:
            saved = parse_refresh(r["body_json"].encode())
            projected = parse_projected(rows[saved.event.sequence - 1]["body_json"].encode())
            assert (
                saved.event == projected.event and saved.request_sha256 == projected.request_sha256
            )
            assert saved.projected_sha256 == rows[saved.event.sequence - 1]["body_sha256"]
            assert saved.policy_sha256 == REFRESH_POLICY.sha256
            assert saved.command_id == str(r["command_id"]) and saved.revision == r["revision"]
            assert hashlib.sha256(r["body_json"].encode()).hexdigest() == r["body_sha256"]
        controlrow = c.execute(
            sql.SQL("SELECT command_count,policy_sha256 FROM {}.refresh_control").format(ps)
        ).fetchone()
        assert controlrow == {
            "command_count": len(refreshes),
            "policy_sha256": REFRESH_POLICY.sha256,
        }
        for h in headrows:
            matches = [r for r in refreshes if r["event_sequence"] == h["event_sequence"]]
            assert len(matches) == h["revision"]
            if matches:
                assert str(h["latest_command_id"]) == str(matches[-1]["command_id"])
            if h["tombstone_json"] is not None:
                tomb = parse_tombstone(h["tombstone_json"].encode())
                p = parse_projected(rows[tomb.event.sequence - 1]["body_json"].encode())
                assert tomb.event == p.event and tomb.request_sha256 == p.request_sha256
                assert tomb.projected_sha256 == rows[tomb.event.sequence - 1]["body_sha256"]
                assert (
                    hashlib.sha256(h["tombstone_json"].encode()).hexdigest()
                    == h["tombstone_sha256"]
                )
        acks = c.execute(
            sql.SQL("SELECT * FROM {}.processing_acks ORDER BY event_sequence").format(ps)
        ).fetchall()
        assert [r["event_sequence"] for r in acks] == [1, 2, 4, 5, 6, 7, 8, 9]
        for a in acks:
            acknowledged = parse_ack(a["body_json"].encode())
            p = parse_projected(rows[acknowledged.event.sequence - 1]["body_json"].encode())
            assert acknowledged.event == p.event and acknowledged.request_sha256 == p.request_sha256
            assert (
                acknowledged.projected_sha256
                == rows[acknowledged.event.sequence - 1]["body_sha256"]
            )
            assert acknowledged.policy_sha256 == policy().sha256
            assert hashlib.sha256(a["body_json"].encode()).hexdigest() == a["body_sha256"]
            if acknowledged.receipt is not None:
                receipt_truth[acknowledged.receipt.delivery_id] = asdict(acknowledged.receipt)
        assert len(receipt_truth) == 2
        assert (
            next(r["body_json"] for r in acks if r["event_sequence"] == 1)
            == load("known_b.json")["ack"]
        )
        controlrow = c.execute(
            sql.SQL(
                "SELECT terminal_watermark,terminal_count,scan_after FROM {}.processing_control"
            ).format(ps)
        ).fetchone()
        assert controlrow == {"terminal_watermark": 2, "terminal_count": 8, "scan_after": 3}
        action_rows = c.execute(sql.SQL("SELECT * FROM {}.result_actions").format(ws)).fetchall()
        assert len(action_rows) == 1
        guard_action = action_rows[0]
        assert (
            str(guard_action["action_id"]) == proof["action_id"]
            and str(guard_action["work_id"]) == proof["work_id"]
        )
        assert (
            str(guard_action["attempt_id"]) == proof["attempt_id"]
            and guard_action["result_sha256"] == proof["result_sha256"]
        )
        assert (
            guard_action["expected_revision"] == 4
            and guard_action["case_schema"] == settings("case", owner=True).schema
        )
        assert (guard_action["case_actor_id"], guard_action["case_scope_id"]) == (
            HELPER.ACTOR.actor_id,
            HELPER.ACTOR.scope_id,
        )
        assert (
            str(guard_action["case_task_id"]) == load("case.json")["task_id"]
            and str(guard_action["case_id"]) == load("case.json")["case_id"]
        )
        assert json.loads(guard_action["confirmation_json"]) == proof["confirmation"]
        assert json.loads(guard_action["intent_json"]) == proof["intent"]
        for table, n in (
            ("result_delivery_intents", 3),
            ("result_delivery_possible", 3),
            ("result_delivery_receipts", 2),
        ):
            assert c.execute(
                sql.SQL("SELECT count(*) AS n FROM {}.{}").format(ws, sql.Identifier(table))
            ).fetchone() == {"n": n}
        deliveries = c.execute(
            sql.SQL(
                "SELECT d.delivery_id::text,d.work_id::text,d.attempt_id::text,d.result_sha256,d.receiver_id::text,d.recipient_id,r.receipt_id::text,r.accepted_at_ms,a.body,a.sha256 FROM {}.result_delivery_intents d JOIN {}.result_delivery_receipts r USING(delivery_id) JOIN {}.attempt_results a USING(attempt_id)"
            ).format(ws, ws, ws)
        ).fetchall()
        assert len(deliveries) == 2
        for r in deliveries:
            assert r["result_sha256"] == r["sha256"] == hashlib.sha256(bytes(r["body"])).hexdigest()
            assert {
                k: r[k]
                for k in (
                    "delivery_id",
                    "receipt_id",
                    "receiver_id",
                    "recipient_id",
                    "result_sha256",
                    "accepted_at_ms",
                )
            } == receipt_truth[r["delivery_id"]]
        STAGE = "owner_case_effect"
        effect = c.execute(
            sql.SQL(
                "SELECT i.intent_id,i.task_id,i.effect_id,i.revision,i.payload_json,e.state,e.dispatch_count,c.payload_json AS confirmation,c.actor_id,c.scope_id,q.payload_json AS quote FROM {}.action_intents i JOIN {}.mutation_effects e USING(intent_id) JOIN {}.confirmations c USING(confirmation_id) JOIN {}.quotes q USING(quote_id)"
            ).format(cs, cs, cs, cs)
        ).fetchall()
        assert len(effect) == 1
        e = effect[0]
        assert (
            e["state"] == "succeeded"
            and e["dispatch_count"] == 1
            and str(e["intent_id"]) == str(guard_action["intent_id"])
        )
        assert e["revision"] == 4 and e["effect_id"] == proof_intent["effect_id"]
        assert (
            e["task_id"] == load("case.json")["task_id"]
            and json.loads(e["payload_json"]) == proof["intent"]
        )
        assert (
            json.loads(e["confirmation"]) == proof["confirmation"]
            and json.loads(e["quote"]) == proof_confirmation["quote"]
        )
        assert (e["actor_id"], e["scope_id"]) == (HELPER.ACTOR.actor_id, HELPER.ACTOR.scope_id)
    STAGE = "owner_receiver"
    with closing(
        sqlite3.connect((folder() / "receiver.sqlite3").as_uri() + "?mode=ro", uri=True)
    ) as c:
        received = c.execute(
            "SELECT delivery_id,intent_json,receipt_json FROM result_receipts"
        ).fetchall()
        assert len(received) == 2
        for delivery_id, intent_raw, receipt_raw in received:
            intent, receipt = json.loads(intent_raw), json.loads(receipt_raw)
            original_delivery = next(r for r in deliveries if r["delivery_id"] == delivery_id)
            assert receipt == receipt_truth[delivery_id]
            assert intent["scope"] == {"tenant_id": SCOPE.tenant_id, "account_id": SCOPE.account_id}
            assert (
                intent["work_id"] == original_delivery["work_id"]
                and intent["attempt_id"] == original_delivery["attempt_id"]
            )
            assert base64.b64decode(intent["body"], validate=True) == bytes(
                original_delivery["body"]
            )
            assert all(
                intent[k] == receipt[k]
                for k in ("delivery_id", "receiver_id", "recipient_id", "result_sha256")
            )
    truth = HELPER.supplier_truth(folder() / "supplier.sqlite3")
    assert truth["applied_calls"] == 1 and len(truth["mutation_receipts"]) == 1
    assert truth["mutation_receipts"][0]["effect_id"] == proof_intent["effect_id"]
    assert truth["mutation_receipts"][0]["scope_id"] == HELPER.ACTOR.scope_id
    assert truth["bookings"] == [[HELPER.ACTOR.scope_id, "DEMO-BK-001", "2030-12-10", 1]]
    return {"status": "passed", "cases": [CASES[17]], "exact_reconciliation": True}


def cleanup() -> dict[str, object]:
    for kind, cap, markers in [
        (
            "projection",
            False,
            {
                "delegation-result-projection-v1",
                "delegation-result-projection-v2",
                "delegation-result-projection-v3",
            },
        ),
        (
            "projection",
            True,
            {
                "delegation-result-projection-v1",
                "delegation-result-projection-v2",
                "delegation-result-projection-v3",
            },
        ),
        (
            "work",
            False,
            {
                "continuity-readonly-work-v1",
                "continuity-readonly-work-v2",
                "continuity-readonly-work-v3",
                "continuity-readonly-work-v4",
            },
        ),
    ]:
        value = settings(kind, owner=True, cap=cap)
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
    return {"status": "passed", "cleanup_complete": True}


def main() -> int:
    global MODE, STAGE
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=sorted(MODES))
    MODE = parser.parse_args().mode
    try:
        required = COMMON | {
            "P3_REFRESH_PG_PORT",
            "P3_REFRESH_OWNER_PASSWORD" if MODE in OWNER_MODES else "P3_REFRESH_RUNTIME_PASSWORD",
        }
        if MODE not in OWNER_MODES:
            required.add("P3_REFRESH_TOKEN")
        if MODE in {
            "upgrade-crash",
            "refresh-before",
            "refresh-after",
            "hide-before",
            "hide-after",
            "race-a",
        }:
            required.add("P3_REFRESH_BARRIER")
        assert required <= set(os.environ) and not set(os.environ) - required - BASE
        STAGE = MODE
        if MODE == "install":
            report = install()
        elif MODE == "seed":
            report = asyncio.run(seed())
        elif MODE in {"upgrade-crash", "upgrade"}:
            report = upgrade()
        elif MODE in {"refresh-before", "resume", "refresh-after", "replay", "race-a", "race-b"}:
            report = asyncio.run(refresh_mode())
        elif MODE == "locks":
            report = locks()
        elif MODE == "classify":
            report = asyncio.run(classify())
        elif MODE in {"hide-before", "hide-resume", "hide-after"}:
            report = asyncio.run(hide_mode())
        elif MODE == "progress":
            report = asyncio.run(progress())
        elif MODE == "restore":
            report = restore()
        elif MODE == "verify":
            report = asyncio.run(verify())
        elif MODE == "owner-check":
            report = owner_check()
        else:
            report = cleanup()
        print(json.dumps(report))
        return 0
    except Exception as error:  # noqa: BLE001 - allowlisted category/code only, never exception text
        category = (
            "work"
            if isinstance(error, WorkError)
            else "projection"
            if isinstance(error, ProjectionError)
            else "completion"
            if isinstance(error, CompletionError)
            else "assertion"
            if isinstance(error, AssertionError)
            else "unexpected"
        )
        safe_code = "unexpected"
        if isinstance(error, (WorkError, ProjectionError, CompletionError)):
            safe_code = str(error.code)
        location = 0
        trace = error.__traceback__
        while trace is not None:
            if trace.tb_frame.f_code.co_filename == __file__:
                location = trace.tb_lineno
            trace = trace.tb_next
        builtin = (
            type(error).__name__
            if type(error)
            in {
                AssertionError,
                FileExistsError,
                KeyError,
                TypeError,
                ValueError,
                AttributeError,
                TimeoutError,
            }
            else "boundary"
        )
        print(
            json.dumps(
                {
                    "status": "failed",
                    "code": STAGE,
                    "category": category,
                    "reason": safe_code,
                    "fixture_line": location,
                    "exception_type": builtin,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
