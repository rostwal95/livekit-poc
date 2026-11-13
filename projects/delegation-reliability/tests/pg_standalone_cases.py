"""Explicit installed consumer and separately labelled owner/worker test tooling.

Runtime application modes import only declared installed public P1/P3 surfaces.
The existing case helper is loaded lazily only for synthetic owner/bootstrap,
leased-worker execution and independent verification. No credential file,
provider, environment-selected module or second execution authority is used.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import stat
import sys
import time
from collections.abc import Mapping
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Protocol, cast
from uuid import uuid4

from continuity_lab.action_api import (
    ActionClient,
    ActionError,
    ActionPort,
    ActionReceipt,
    Confirmation,
    open_action_client,
)
from continuity_lab.case_control_api import (
    BookingChange,
    CaseControlClient,
    open_case_control_client,
)
from continuity_lab.delivery_api import (
    DeliveryIntent,
    DeliveryReceipt,
    open_delivery_client,
)
from continuity_lab.execution_api import (
    AttemptResult,
    ExecutionClient,
    ExecutionObservation,
    ExecutionPort,
    Issuance,
    IssuedAttempt,
    open_execution_client,
)
from continuity_lab.postgres_api import (
    AuthenticatedActor,
    InvalidConfirmation,
    open_postgres_client,
    parse_confirmation_payload,
)
from continuity_lab.receiver_api import ReceiverBinding, ResultReceiver, open_result_receiver
from continuity_lab.result_feed_api import open_result_feed_client
from continuity_lab.work_api import (
    BearerToken,
    PostgresSettings,
    WorkDirectory,
    WorkError,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from delegation_reliability import (
    ActionBinding,
    ApplicabilityRefresher,
    CompletionError,
    CompletionPolicy,
    CompletionProcessor,
    CoordinatorError,
    DelegationAuthorizer,
    DelegationCoordinator,
    DelegationDeliveryClient,
    DelegationRunError,
    DeliveryBinding,
    ExactManagedCaseAuthority,
    ProjectionError,
    ProjectionProjector,
    SpecialistClient,
    SpecialistEndpoint,
    SpecialistInvocationPort,
    SpecialistResultObservation,
    open_applicability_client,
    open_processing_client,
    open_projection_client,
)
from delegation_reliability.contracts import (
    CAPABILITY,
    ContractError,
    DelegationRequest,
    Scope,
    canonical,
    encode_request,
    parse_request,
    produce_request,
)
from delegation_reliability.security import EvidenceRecord

if TYPE_CHECKING:
    from psycopg.sql import Composed

ROOT = Path(__file__).resolve().parents[3]
SCOPE = Scope("tenant_standalone", "account_standalone")
ACTOR = AuthenticatedActor("p3_completion_user", "p3_completion_scope")
POLICY = canonical({"minimum_notice_days": 7, "policy_version": "policy_v1"})
RECIPIENT = "recipient_standalone"
LOGICAL_CASE = "case_standalone"
CONVERSATION = "conversation_standalone"
COMMAND = "standalone_execution"
CONFIRMATION_COMMAND = "standalone_exact_confirmation"
MODES = (
    "install",
    "seed",
    "complete",
    "effect",
    "metadata",
    "negative",
    "replay",
    "cancel",
    "verify",
    "cleanup",
)
CASES = {
    "install": (),
    "seed": (),
    "effect": (),
    "cleanup": (),
    "complete": ("actual_run_completion_useful_result",),
    "metadata": ("public_projection_processing_refresh_progress",),
    "negative": (
        "equal_acceptance_changed_payload_scope_isolation",
        "separate_exact_confirmation_original_guarded_intent",
        "read_only_inspection_zero_new_calls",
    ),
    "replay": ("owned_completion_ACK_crash_fresh_original_replay",),
    "cancel": ("later_cancel_preserves_original_facts_without_new_permission",),
    "verify": ("independent_SQL_receiver_supplier_identity_cleanup",),
}
CALLS = (
    "issue_write",
    "complete_write",
    "authorize_write",
    "invoke",
    "receiver_accept",
    "supplier_apply",
)
FIXTURE_STAGES = frozenset(
    [
        "configuration",
        "install",
        "seed",
        "complete",
        "effect",
        "metadata",
        "negative",
        "replay",
        "cancel",
        "verify",
        "cleanup",
        "verify_counts",
        "verify_source",
        "verify_projection",
        "verify_ack",
        "verify_refresh",
        "verify_delivery",
        "verify_action",
        "verify_effect",
        "verify_business",
        "verify_receiver",
        "verify_supplier",
        "verify_peer",
        "verify_inventory",
    ]
)
SAFE_CODES = frozenset(
    [
        "acknowledgement_unknown",
        "capacity",
        "case_cancelled",
        "case_changed",
        "case_state_unavailable",
        "checkpoint_conflict",
        "cleanup_incomplete",
        "closed",
        "deadline_exceeded",
        "deadline_expired",
        "evidence_mismatch",
        "expired",
        "fixture_failed",
        "identity_conflict",
        "intent_committed",
        "internal_error",
        "invalid_confirmation",
        "invalid_contract",
        "invalid_input",
        "invalid_json",
        "invalid_result",
        "invalid_source_state",
        "invalid_stored_state",
        "not_eligible",
        "not_found",
        "quote_expired",
        "request_aborted",
        "result_mismatch",
        "schema_mismatch",
        "source_mismatch",
        "stale_revision",
        "storage_unavailable",
        "transport_unknown",
        "unauthorized",
        "unknown_attempt",
        "unknown_capability",
        "unsupported_facts",
        "unsupported_version",
    ]
)
MODE = "unselected"
STAGE = "configuration"
CLEANUP_FAILED = False


class Closable(Protocol):
    async def close(self) -> None: ...


class Application(Closable, Protocol):
    coordinators: tuple[DelegationCoordinator, DelegationCoordinator]
    runner: Any
    delivery: DelegationDeliveryClient
    authorizer: DelegationAuthorizer
    case_client: CaseControlClient

    @property
    def pending_count(self) -> int: ...
    @property
    def cleanup_complete(self) -> bool: ...
    async def complete(
        self,
        request: DelegationRequest,
        *,
        confirmation: Confirmation,
        execution_command_id: str,
        confirmation_command_id: str,
    ) -> Any: ...
    async def inspect(self, work_id: str) -> Any: ...


class CaseFixture(Protocol):
    ACTOR: AuthenticatedActor
    REQUEST: BookingChange
    ALTERNATE: BookingChange

    def install(self, settings: PostgresSettings, supplier: Path) -> dict[str, object]: ...
    def inquire(
        self, settings: PostgresSettings, supplier: Path, task_id: str
    ) -> dict[str, object]: ...
    def mutate(
        self, settings: PostgresSettings, supplier: Path, task_id: str
    ) -> dict[str, object]: ...
    def supplier_truth(self, supplier: Path) -> dict[str, object]: ...
    def cleanup(self, settings: PostgresSettings) -> None: ...


def stage(name: str) -> None:
    global STAGE
    if name not in FIXTURE_STAGES:
        raise ValueError("invalid_fixture_stage")
    STAGE = name


def folder() -> Path:
    path = Path(os.environ["P3_STANDALONE_DIRECTORY"])
    info = path.lstat()
    if (
        not path.is_absolute()
        or path.resolve() != path
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_uid != os.geteuid()
    ):
        raise ValueError("invalid_fixture_directory")
    return path


def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid_fixture_file")
        result[key] = value
    return result


def load(name: str) -> dict[str, Any]:
    if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}\.json", name) is None:
        raise ValueError("invalid_fixture_file")
    path = folder() / name
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or not 1 <= info.st_size <= 32768
    ):
        raise ValueError("invalid_fixture_file")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        raw = stream.read(32769)
    if len(raw) > 32768:
        raise ValueError("invalid_fixture_file")
    value = json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_fixture_file")),
    )
    if type(value) is not dict:
        raise ValueError("invalid_fixture_file")
    return cast(dict[str, Any], value)


def save(name: str, value: object) -> None:
    if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}\.json", name) is None:
        raise ValueError("invalid_fixture_file")
    raw = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        + "\n"
    ).encode()
    if not 1 <= len(raw) <= 32768:
        raise ValueError("fixture_file_limit")
    with os.fdopen(
        os.open(folder() / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(raw)


def settings(kind: str = "work") -> PostgresSettings:
    owner = MODE in {"install", "verify", "cleanup"}
    key = {"work": "WORK_SCHEMA", "case": "CASE_SCHEMA", "projection": "SCHEMA"}[kind]
    return PostgresSettings(
        host="127.0.0.1",
        port=int(os.environ["P3_STANDALONE_PG_PORT"]),
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ["P3_STANDALONE_" + ("OWNER_PASSWORD" if owner else "RUNTIME_PASSWORD")],
        schema=os.environ["P3_STANDALONE_" + key],
    )


def directory(foreign: bool = False) -> tuple[WorkDirectory, BearerToken]:
    token = BearerToken("Z" * 43 if foreign else os.environ["P3_STANDALONE_WORK_TOKEN"])
    scope = WorkScope(SCOPE.tenant_id, "foreign_account" if foreign else SCOPE.account_id)
    return WorkDirectory(
        {token: WorkPrincipal("standalone_foreign" if foreign else "standalone_application", scope)}
    ), token


def case_token() -> BearerToken:
    return BearerToken(os.environ["P3_STANDALONE_CASE_TOKEN"])


def helper() -> CaseFixture:
    if MODE not in {"install", "seed", "effect", "verify", "cleanup"}:
        raise ValueError("owner_helper_forbidden_in_public_consumer")
    spec = importlib.util.spec_from_file_location(
        "p3_standalone_case_tooling", ROOT / "local-setup/scripts/p3_case_fixture.py"
    )
    if spec is None or spec.loader is None:
        raise ValueError("missing_owner_tooling")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = cast(CaseFixture, cast(object, module))
    if value.ACTOR != ACTOR:
        raise ValueError("invalid_owner_mapping")
    return value


def application_module(name: str) -> ModuleType:
    path = ROOT / "projects/delegation-reliability/examples" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError("missing_public_application")
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def action_binding() -> ActionBinding:
    value = load("case.json")
    return ActionBinding(
        case_id=LOGICAL_CASE,
        task_id=str(value["task_id"]),
        authority_case_id=str(value["case_id"]),
        authority_actor_id=ACTOR.actor_id,
        authority_scope_id=ACTOR.scope_id,
        case_schema=settings("case").schema,
    )


def evidence() -> tuple[EvidenceRecord, ...]:
    request = parse_request(canonical(load("request.json")))
    return (EvidenceRecord(SCOPE, request.evidence[0], POLICY),)


def policy() -> CompletionPolicy:
    return CompletionPolicy(
        str(load("identity.json")["receiver_id"]),
        (DeliveryBinding(LOGICAL_CASE, CONVERSATION, RECIPIENT),),
    )


def confirmation() -> Confirmation:
    value = load("operator-confirmation.json")
    if value.get("explicit") is not True:
        raise ValueError("missing_exact_operator_confirmation")
    return parse_confirmation_payload(
        canonical(value["quote"]).decode(), explicit=value["explicit"]
    )


class Counters:
    def __init__(self) -> None:
        self.values = dict.fromkeys(CALLS, 0)

    def add(self, name: str) -> None:
        if name not in self.values or self.values[name] >= 4:
            raise ValueError("fixture_call_limit")
        self.values[name] += 1
        save(
            f"call_{MODE}_{name}_{self.values[name]}.json",
            {"mode": MODE, "call": name, "number": self.values[name]},
        )


class CountedExecution:
    def __init__(self, actual: ExecutionClient, calls: Counters) -> None:
        self.actual, self.calls = actual, calls

    @property
    def scope(self) -> WorkScope:
        return self.actual.scope

    @property
    def pending_count(self) -> int:
        return self.actual.pending_count

    async def issue(self, *, work_id: str, owner_id: str, command_id: str) -> Issuance:
        self.calls.add("issue_write")
        return await self.actual.issue(work_id=work_id, owner_id=owner_id, command_id=command_id)

    async def complete(self, *, attempt: IssuedAttempt, body: bytes) -> AttemptResult:
        self.calls.add("complete_write")
        return await self.actual.complete(attempt=attempt, body=body)

    async def find_issue(self, *, command_id: str) -> IssuedAttempt | None:
        return await self.actual.find_issue(command_id=command_id)

    async def result(self, *, work_id: str, attempt_id: str) -> AttemptResult | None:
        return await self.actual.result(work_id=work_id, attempt_id=attempt_id)

    async def observe(self, *, work_id: str) -> ExecutionObservation:
        return await self.actual.observe(work_id=work_id)

    async def close(self) -> None:
        await self.actual.close()


class CountedActions:
    def __init__(self, actual: ActionClient, calls: Counters) -> None:
        self.actual, self.calls = actual, calls

    @property
    def scope(self) -> WorkScope:
        return self.actual.scope

    @property
    def case_actor_id(self) -> str:
        return self.actual.case_actor_id

    @property
    def case_scope_id(self) -> str:
        return self.actual.case_scope_id

    @property
    def case_schema(self) -> str:
        return self.actual.case_schema

    @property
    def pending_count(self) -> int:
        return self.actual.pending_count

    def metrics(self) -> Mapping[str, int]:
        return self.actual.metrics()

    async def authorize(
        self,
        *,
        work_id: str,
        attempt_id: str,
        result_sha256: str,
        expected_revision: int,
        confirmation: Confirmation,
        command_id: str,
    ) -> ActionReceipt:
        self.calls.add("authorize_write")
        return await self.actual.authorize(
            work_id=work_id,
            attempt_id=attempt_id,
            result_sha256=result_sha256,
            expected_revision=expected_revision,
            confirmation=confirmation,
            command_id=command_id,
        )

    async def find_action(self, *, command_id: str) -> ActionReceipt | None:
        return await self.actual.find_action(command_id=command_id)

    async def action(self, *, work_id: str) -> ActionReceipt | None:
        return await self.actual.action(work_id=work_id)

    async def close(self) -> None:
        await self.actual.close()


class CountedSpecialist:
    def __init__(self, actual: SpecialistInvocationPort, calls: Counters) -> None:
        self.actual, self.calls = actual, calls

    async def invoke_observed(self, request: DelegationRequest) -> SpecialistResultObservation:
        self.calls.add("invoke")
        return await self.actual.invoke_observed(request)

    async def close(self) -> None:
        await self.actual.close()


class CountedReceiver(ResultReceiver):
    def __init__(self, actual: ResultReceiver, calls: Counters) -> None:
        self.actual, self.calls = actual, calls

    @property
    def receiver_id(self) -> str:
        return self.actual.receiver_id

    @property
    def pending_count(self) -> int:
        return self.actual.pending_count

    def metrics(self) -> Mapping[str, int]:
        return self.actual.metrics()

    async def accept(self, intent: DeliveryIntent) -> DeliveryReceipt:
        self.calls.add("receiver_accept")
        return await self.actual.accept(intent)

    async def find(self, intent: DeliveryIntent) -> DeliveryReceipt | None:
        return await self.actual.find(intent)

    async def close(self) -> None:
        await self.actual.close()


async def application(calls: Counters) -> Application:
    application_module("policy_completion")
    example = application_module("standalone_policy")
    registry, token = directory()
    endpoint = load("specialist-endpoint.json")
    if (
        set(endpoint) != {"schema_version", "host", "port", "node_version"}
        or endpoint["host"] != "127.0.0.1"
        or type(endpoint["port"]) is not int
        or endpoint["node_version"] != "24.22.2"
        or type(endpoint["schema_version"]) is not int
        or endpoint["schema_version"] != 1
        or not 1 <= endpoint["port"] <= 65535
    ):
        raise ValueError("invalid_specialist_endpoint")
    owned: list[Closable] = []

    def opened(factory: Any, *args: Any, **kwargs: Any) -> Any:
        client = factory(*args, **kwargs)
        owned.append(client)
        return client

    try:
        control = opened(
            open_case_control_client,
            actor=ACTOR,
            token=case_token(),
            settings=settings("case"),
            quote_database=folder() / "supplier.sqlite3",
        )
        execution: ExecutionPort = CountedExecution(
            opened(open_execution_client, settings=settings(), directory=registry, token=token),
            calls,
        )
        specialist: SpecialistInvocationPort = CountedSpecialist(
            SpecialistClient(
                SpecialistEndpoint(endpoint["port"]),
                "Bearer " + os.environ["P3_STANDALONE_SPECIALIST_TOKEN"],
            ),
            calls,
        )
        owned.append(specialist)
        receiver = CountedReceiver(
            opened(
                open_result_receiver,
                folder() / "receiver.sqlite3",
                receiver_id=policy().receiver_id,
                bindings=(
                    ReceiverBinding(WorkScope(SCOPE.tenant_id, SCOPE.account_id), RECIPIENT),
                ),
            ),
            calls,
        )
        actions: ActionPort = CountedActions(
            opened(
                open_action_client,
                settings=settings(),
                directory=registry,
                token=token,
                case_settings=settings("case"),
                case_actor=ACTOR,
                case_token=case_token(),
            ),
            calls,
        )
        return cast(
            Application,
            example.configure_standalone(
                scope=SCOPE,
                owner_id=str(load("identity.json")["owner_id"]),
                work_clients=(
                    opened(open_work_client, settings=settings(), directory=registry, token=token),
                    opened(open_work_client, settings=settings(), directory=registry, token=token),
                ),
                execution=execution,
                specialist=specialist,
                case_client=control,
                deliveries=opened(
                    open_delivery_client, settings=settings(), directory=registry, token=token
                ),
                receiver=receiver,
                actions=actions,
                evidence=evidence(),
                action_bindings=(action_binding(),),
                delivery_bindings=policy().bindings,
            ),
        )
    except BaseException:
        await close_preserving(*owned)
        raise


async def close_preserving(*owners: Closable) -> None:
    global CLEANUP_FAILED
    primary = sys.exc_info()[1]
    first: BaseException | None = None
    for owner in owners:
        try:
            await owner.close()
        except BaseException as error:  # noqa: BLE001 - attempt independent owners; preserve first error without reflecting messages.
            CLEANUP_FAILED = True
            if first is None:
                first = error
    if primary is None and first is not None:
        raise first


def reply() -> dict[str, object]:
    if CLEANUP_FAILED:
        raise ValueError("fixture_cleanup_incomplete")
    return {"schema_version": 1, "mode": MODE, "status": "passed", "cases": list(CASES[MODE])}


def hashed(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def source_id() -> str:
    return str(load("identity.json")["source_id"])


def action_payload(value: ActionReceipt) -> dict[str, Any]:
    return {
        "action_id": value.action_id,
        "work_id": value.work_id,
        "attempt_id": value.attempt_id,
        "result_sha256": value.result_sha256,
        "case_schema": value.case_schema,
        "case_scope_id": value.case_scope_id,
        "case_actor_id": value.case_actor_id,
        "case_task_id": value.case_task_id,
        "case_id": value.case_id,
        "expected_revision": value.expected_revision,
        "command_id": value.command_id,
        "confirmation": value.confirmation.payload(),
        "intent": value.intent.payload(),
        "committed_at_ms": value.committed_at_ms,
    }


def install() -> dict[str, object]:
    from psycopg import sql

    from continuity_lab.receiver_api import initialize_result_receiver
    from continuity_lab.work_admin import (
        ExecutionLimits,
        WorkLimits,
        install_work_schema,
        upgrade_work_schema_v2,
        upgrade_work_schema_v3,
        upgrade_work_schema_v4,
    )
    from delegation_reliability import ProjectionBinding, ProjectionLimits, RefreshPolicy
    from delegation_reliability.projection_admin import (
        install_projection_schema,
        upgrade_projection_schema_v2,
        upgrade_projection_schema_v3,
    )

    stage("install")
    save(
        "owned.json",
        {
            "marker": "p3-standalone-fixture-v1",
            "work": settings().schema,
            "case": settings("case").schema,
            "projection": settings("projection").schema,
        },
    )
    install_work_schema(settings(), limits=WorkLimits(4, 4))
    upgrade_work_schema_v2(settings(), limits=ExecutionLimits(2, 2, 5000))
    upgrade_work_schema_v3(settings())
    upgrade_work_schema_v4(settings())
    helper().install(settings("case"), folder() / "supplier.sqlite3")
    receiver_id = initialize_result_receiver(folder() / "receiver.sqlite3")
    with closing(settings().connect(application_name="continuity-test")) as connection:
        row = connection.execute(
            sql.SQL("SELECT source_id::text FROM {}.result_feed_source WHERE singleton").format(
                sql.Identifier(settings().schema)
            )
        ).fetchone()
        assert row is not None
    save(
        "identity.json",
        {
            "source_id": row["source_id"],
            "receiver_id": receiver_id,
            "owner_id": str(uuid4()),
            "refresh_first": str(uuid4()),
            "refresh_second": str(uuid4()),
        },
    )
    install_projection_schema(
        settings("projection"),
        binding=ProjectionBinding(source_id(), WorkScope(SCOPE.tenant_id, SCOPE.account_id)),
        limits=ProjectionLimits(4),
    )
    upgrade_projection_schema_v2(settings("projection"), policy=policy())
    upgrade_projection_schema_v3(settings("projection"), policy=RefreshPolicy(4, 2))
    return reply()


async def seed() -> dict[str, object]:
    stage("seed")
    client = open_postgres_client(
        actor=ACTOR,
        token=case_token(),
        settings=settings("case"),
        quote_database=folder() / "supplier.sqlite3",
    )
    control = open_case_control_client(
        actor=ACTOR,
        token=case_token(),
        settings=settings("case"),
        quote_database=folder() / "supplier.sqlite3",
    )
    try:
        fixture = helper()
        accepted = await client.submit(
            idempotency_key="standalone_real_case", request=fixture.REQUEST
        )
        save("case.json", {"task_id": accepted.task_id, "case_id": accepted.case_id})
        await asyncio.to_thread(
            fixture.inquire, settings("case"), folder() / "supplier.sqlite3", accepted.task_id
        )
        await control.revise(
            task_id=accepted.task_id, expected_revision=0, request=fixture.ALTERNATE
        )
        await control.revise(task_id=accepted.task_id, expected_revision=1, request=fixture.REQUEST)
        quote = await client.prepare_quote(
            task_id=accepted.task_id, expected_revision=2, command_id="standalone_quote"
        )
        # Explicit synthetic operator input, separate from all specialist output.
        save("operator-confirmation.json", {"quote": quote.quote.payload(), "explicit": True})
        request = produce_request(
            {
                "schema_version": 1,
                "kind": "delegation.request",
                "capability": CAPABILITY,
                "input_schema_version": 1,
                "scope": asdict(SCOPE),
                "delegation_id": "delegation_standalone",
                "case_id": LOGICAL_CASE,
                "request_revision": 2,
                "context_snapshot": {
                    "policy_version": "policy_v1",
                    "policy_source_id": "policy_demo",
                    "days_before_arrival": 14,
                    "note": "Explicit standalone installed consumer.",
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
                "deadline_at_ms": time.time_ns() // 1000000 + 60000,
                "result_route": {"conversation_id": CONVERSATION},
                "attempt": {"attempt_id": "attempt_proposed", "number": 1},
            }
        )
        save("request.json", json.loads(encode_request(request)))
    finally:
        await close_preserving(client, control)
    return reply()


async def inspect_summary(app: Application, summary: Any) -> dict[str, Any]:
    inspected = await app.inspect(summary.work_id)
    result = inspected.execution.execution.result
    assert result is not None and inspected.action is not None
    delivery = inspected.delivery.snapshot
    assert delivery is not None and delivery.receipt is not None
    saved = {
        **asdict(summary),
        "attempt_id": result.attempt_id,
        "delivery_id": delivery.receipt.delivery_id,
        "receipt_id": delivery.receipt.receipt_id,
        "receiver_id": delivery.receipt.receiver_id,
        "intent_id": inspected.action.intent.intent_id,
        "effect_id": inspected.action.intent.effect_id,
    }
    return saved


async def complete() -> None:
    stage("complete")
    calls = Counters()
    app = await application(calls)
    try:
        summary = await app.complete(
            parse_request(canonical(load("request.json"))),
            confirmation=confirmation(),
            execution_command_id=COMMAND,
            confirmation_command_id=CONFIRMATION_COMMAND,
        )
        assert (
            summary.created_acceptances == 1
            and summary.invoked
            and summary.delivery_state == "accepted"
        )
        save("first.json", await inspect_summary(app, summary))
        inspected = await app.inspect(summary.work_id)
        assert inspected.action is not None
        save("action.json", action_payload(inspected.action))
        assert calls.values == {
            "issue_write": 1,
            "complete_write": 1,
            "authorize_write": 1,
            "invoke": 1,
            "receiver_accept": 1,
            "supplier_apply": 0,
        }
        save("first-calls.json", calls.values)
    finally:
        await close_preserving(app)
    assert app.pending_count == 0 and app.cleanup_complete
    save("first-cleanup.json", {"pending": 0, "cleanup_complete": True})
    path = Path(os.environ["P3_STANDALONE_BARRIER"])
    assert path == folder() / "completion_returned.reached"
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
    ) as stream:
        stream.write(f"{os.getpid()}\n".encode())
    await asyncio.Event().wait()


def effect() -> dict[str, object]:
    stage("effect")
    calls = Counters()
    calls.add("supplier_apply")
    saved = helper().mutate(
        settings("case"), folder() / "supplier.sqlite3", str(load("case.json")["task_id"])
    )
    assert saved["status"] == "passed" and saved["effect_state"] == "succeeded"
    save("effect.json", saved)
    return reply()


def metadata_clients(app: Application) -> tuple[Any, Any, Any]:
    from delegation_reliability import RefreshPolicy

    reg, token = directory()
    authority = ExactManagedCaseAuthority(
        app.case_client, scope=SCOPE, bindings=(action_binding(),)
    )
    projector = ProjectionProjector(
        events=open_result_feed_client(settings=settings(), directory=reg, token=token),
        executions=open_execution_client(settings=settings(), directory=reg, token=token),
        projections=open_projection_client(
            settings=settings("projection"), directory=reg, token=token, source_id=source_id()
        ),
        scope=SCOPE,
        evidence=evidence(),
        case_authority=authority,
    )
    processor = CompletionProcessor(
        processing=open_processing_client(
            settings=settings("projection"),
            directory=reg,
            token=token,
            source_id=source_id(),
            policy=policy(),
        ),
        source=open_result_feed_client(settings=settings(), directory=reg, token=token),
        delivery=app.delivery,
        results=app.runner,
        scope=SCOPE,
        evidence=evidence(),
    )
    refresher = ApplicabilityRefresher(
        events=open_result_feed_client(settings=settings(), directory=reg, token=token),
        executions=open_execution_client(settings=settings(), directory=reg, token=token),
        applicability=open_applicability_client(
            settings=settings("projection"),
            directory=reg,
            token=token,
            source_id=source_id(),
            policy=RefreshPolicy(4, 2),
        ),
        scope=SCOPE,
        evidence=evidence(),
        case_authority=authority,
    )
    return projector, processor, refresher


async def metadata() -> dict[str, object]:
    from delegation_reliability import RefreshPolicy

    stage("metadata")
    app = await application(Counters())
    projector, processor, refresher = metadata_clients(app)
    reg, token = directory()
    projection = open_projection_client(
        settings=settings("projection"), directory=reg, token=token, source_id=source_id()
    )
    processing = open_processing_client(
        settings=settings("projection"),
        directory=reg,
        token=token,
        source_id=source_id(),
        policy=policy(),
    )
    display = open_applicability_client(
        settings=settings("projection"),
        directory=reg,
        token=token,
        source_id=source_id(),
        policy=RefreshPolicy(4, 2),
    )
    try:
        first = load("first.json")
        batch = await application_module("result_projection").project_results(projector, limit=1)
        assert batch.after.sequence == 1
        inspected = await application_module("result_projection").inspect_projected(
            projection, work_id=first["work_id"], attempt_id=first["attempt_id"]
        )
        assert inspected.result is not None and inspected.checkpoint.sequence == 1
        event_id = inspected.result.event.event_id
        step = await application_module("result_processing").process_results(processor, limit=1)
        assert step.after.terminal_watermark == step.after.terminal_count == 1
        ack = await application_module("result_processing").inspect_ack(
            processing, event_id=event_id
        )
        assert ack is not None and ack.decision == "receiver_accepted" and ack.receipt is not None
        refresh = await application_module("result_applicability").refresh_result(
            refresher,
            work_id=first["work_id"],
            attempt_id=first["attempt_id"],
            command_id=load("identity.json")["refresh_first"],
            expected_revision=0,
        )
        assert refresh.classification == "current" and refresh.reason == "candidate"
        tomb = await application_module("result_applicability").hide_result(
            display, work_id=first["work_id"], attempt_id=first["attempt_id"]
        )
        view = await application_module("result_applicability").inspect_result(
            display, work_id=first["work_id"], attempt_id=first["attempt_id"]
        )
        assert view.latest == refresh and view.tombstone == tomb
        save("projection.json", json.loads(inspected.result.canonical()))
        save("ack.json", json.loads(ack.canonical()))
        save("refresh-first.json", json.loads(refresh.canonical()))
        save("tombstone.json", json.loads(tomb.canonical()))
    finally:
        await close_preserving(
            projector, processor, refresher, projection, processing, display, app
        )
    return reply()


async def negative() -> dict[str, object]:
    stage("negative")
    calls = Counters()
    app = await application(calls)
    try:
        request = parse_request(canonical(load("request.json")))
        changed = json.loads(encode_request(request))
        changed.pop("input_fingerprint")
        changed["context_snapshot"]["days_before_arrival"] = 15
        try:
            await app.coordinators[0].submit(produce_request(changed))
            raise AssertionError("expected_conflict")
        except CoordinatorError as error:
            assert error.code == "identity_conflict"
        foreign = json.loads(encode_request(request))
        foreign.pop("input_fingerprint")
        foreign["scope"]["account_id"] = "foreign_account"
        try:
            await app.coordinators[0].submit(produce_request(foreign))
            raise AssertionError("expected_scope_rejection")
        except CoordinatorError as error:
            assert error.code == "unauthorized"
        registry, token = directory(True)
        reader = open_work_client(settings=settings(), directory=registry, token=token)
        try:
            try:
                await reader.get(work_id=load("first.json")["work_id"])
                raise AssertionError("foreign_disclosure")
            except WorkError as error:
                assert error.code == "not_found"
        finally:
            await close_preserving(reader)
        missing = json.loads(encode_request(request))
        missing.pop("input_fingerprint")
        missing["delegation_id"] = "delegation_missing_confirmation"
        try:
            await app.complete(
                produce_request(missing),
                confirmation=cast(Confirmation, None),
                execution_command_id=COMMAND,
                confirmation_command_id=CONFIRMATION_COMMAND,
            )
            raise AssertionError("expected_missing_confirmation")
        except InvalidConfirmation:
            pass
        exact = confirmation()
        payload = exact.quote.payload()
        payload["amount_minor"] = exact.quote.amount_minor + 1
        altered = parse_confirmation_payload(canonical(payload).decode(), explicit=True)
        # Actual authority write with a valid changed confirmation, original command.
        registry, token = directory()
        writer = open_action_client(
            settings=settings(),
            directory=registry,
            token=token,
            case_settings=settings("case"),
            case_actor=ACTOR,
            case_token=case_token(),
        )
        try:
            try:
                await writer.authorize(
                    work_id=load("first.json")["work_id"],
                    attempt_id=load("first.json")["attempt_id"],
                    result_sha256=load("first.json")["result_sha256"],
                    expected_revision=2,
                    confirmation=altered,
                    command_id=CONFIRMATION_COMMAND,
                )
                raise AssertionError("expected_changed_confirmation_conflict")
            except ActionError as confirmation_error:
                assert confirmation_error.code == "identity_conflict"
        finally:
            await close_preserving(writer)
        inspected = await app.inspect(load("first.json")["work_id"])
        assert inspected.action is not None and action_payload(inspected.action) == load(
            "action.json"
        )
        assert calls.values == dict.fromkeys(CALLS, 0)
        save(
            "negative.json",
            {
                "changed_payload": "identity_conflict",
                "foreign_scope": "unauthorized",
                "foreign_read": "not_found",
                "missing_confirmation": "invalid_confirmation",
                "changed_confirmation": "identity_conflict",
                "read_only_call_counts": calls.values,
            },
        )
    finally:
        await close_preserving(app)
    return reply()


async def inspect_metadata_original(first: dict[str, Any]) -> None:
    from delegation_reliability import RefreshPolicy

    registry, token = directory()
    projection = open_projection_client(
        settings=settings("projection"), directory=registry, token=token, source_id=source_id()
    )
    processing = open_processing_client(
        settings=settings("projection"),
        directory=registry,
        token=token,
        source_id=source_id(),
        policy=policy(),
    )
    display = open_applicability_client(
        settings=settings("projection"),
        directory=registry,
        token=token,
        source_id=source_id(),
        policy=RefreshPolicy(4, 2),
    )
    try:
        result = await application_module("result_projection").inspect_projected(
            projection, work_id=first["work_id"], attempt_id=first["attempt_id"]
        )
        assert (
            result.result is not None
            and json.loads(result.result.canonical()) == load("projection.json")
            and result.checkpoint.sequence == 1
        )
        ack = await application_module("result_processing").inspect_ack(
            processing, event_id=result.result.event.event_id
        )
        view = await application_module("result_applicability").inspect_result(
            display, work_id=first["work_id"], attempt_id=first["attempt_id"]
        )
        assert ack is not None and json.loads(ack.canonical()) == load("ack.json")
        assert (
            view.latest is not None
            and view.tombstone is not None
            and json.loads(view.latest.canonical()) == load("refresh-first.json")
            and json.loads(view.tombstone.canonical()) == load("tombstone.json")
        )
    finally:
        await close_preserving(projection, processing, display)


async def replay() -> dict[str, object]:
    stage("replay")
    app = await application(calls := Counters())
    try:
        summary = await app.complete(
            parse_request(canonical(load("request.json"))),
            confirmation=confirmation(),
            execution_command_id=COMMAND,
            confirmation_command_id=CONFIRMATION_COMMAND,
        )
        result = await inspect_summary(app, summary)
        expected = {**load("first.json"), "created_acceptances": 0, "invoked": False}
        assert result == expected and calls.values == dict.fromkeys(CALLS, 0)
        inspected = await app.inspect(summary.work_id)
        assert inspected.action is not None and action_payload(inspected.action) == load(
            "action.json"
        )
        await inspect_metadata_original(load("first.json"))
        save("replay.json", result)
        save("replay-calls.json", calls.values)
    finally:
        await close_preserving(app)
    assert app.pending_count == 0 and app.cleanup_complete
    save("replay-cleanup.json", {"pending": 0, "cleanup_complete": True})
    return reply()


async def cancel() -> dict[str, object]:
    from delegation_reliability import RefreshPolicy

    stage("cancel")
    app = await application(calls := Counters())
    registry, token = directory()
    work = open_work_client(settings=settings(), directory=registry, token=token)
    _projector, _processor, refresher = metadata_clients(app)
    display = open_applicability_client(
        settings=settings("projection"),
        directory=registry,
        token=token,
        source_id=source_id(),
        policy=RefreshPolicy(4, 2),
    )
    processing = open_processing_client(
        settings=settings("projection"),
        directory=registry,
        token=token,
        source_id=source_id(),
        policy=policy(),
    )
    try:
        first = load("first.json")
        await work.cancel(work_id=first["work_id"], command_id="standalone_cancel")
        inspected = await app.inspect(first["work_id"])
        assert inspected.action is not None and action_payload(inspected.action) == load(
            "action.json"
        )
        assert (
            inspected.delivery.snapshot is not None
            and inspected.delivery.snapshot.receipt is not None
            and inspected.delivery.snapshot.receipt.receipt_id == first["receipt_id"]
        )
        result = await application_module("result_applicability").refresh_result(
            refresher,
            work_id=first["work_id"],
            attempt_id=first["attempt_id"],
            command_id=load("identity.json")["refresh_second"],
            expected_revision=1,
        )
        assert result.classification == "invalidated" and result.reason == "work_cancelled"
        view = await display.inspect(work_id=first["work_id"], attempt_id=first["attempt_id"])
        original = await display.command(command_id=load("identity.json")["refresh_first"])
        ack = await processing.acknowledgement(event_id=view.projection.event.event_id)
        assert original is not None and json.loads(original.canonical()) == load(
            "refresh-first.json"
        )
        assert view.tombstone is not None and json.loads(view.tombstone.canonical()) == load(
            "tombstone.json"
        )
        assert ack is not None and json.loads(ack.canonical()) == load("ack.json")
        assert calls.values == dict.fromkeys(CALLS, 0)
        save("refresh-second.json", json.loads(result.canonical()))
        save(
            "after-cancel.json",
            {
                "action_id": inspected.action.action_id,
                "receipt_id": inspected.delivery.snapshot.receipt.receipt_id,
                "refresh_classification": result.classification,
                "refresh_reason": result.reason,
                "as_of_kind": result.kind,
                "original_facts_preserved": True,
                "new_call_counts": calls.values,
            },
        )
    finally:
        await close_preserving(work, _projector, _processor, refresher, display, processing, app)
    return reply()


def inventory_digest(records: list[dict[str, Any]]) -> str:
    assert 1 <= len(records) <= 64
    output = hashlib.sha256(b"p3-standalone-inventory-v1\0")
    total = 0
    for record in records:
        raw = json.dumps(
            record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
        total += len(raw)
        assert len(raw) <= 4096 and total <= 65536
        output.update(len(raw).to_bytes(4, "big"))
        output.update(raw)
    return output.hexdigest()


def source_query(schema: str) -> Composed:
    """Owner evidence query; P1 derives cancellation from scoped command rows."""
    from psycopg import sql

    name = sql.Identifier(schema)
    return sql.SQL(
        "SELECT w.*,r.attempt_id,r.body AS result_body,r.sha256 AS result_sha256,r.recorded_at_ms,r.disposition,f.event_id,f.sequence,a.command_id,a.owner_id,a.number,a.epoch,EXISTS(SELECT 1 FROM {}.cancellation_commands c WHERE c.tenant_id=w.tenant_id AND c.account_id=w.account_id AND c.work_id=w.work_id) AS cancel_requested FROM {}.accepted_work w JOIN {}.attempt_results r USING(tenant_id,account_id,work_id) JOIN {}.issued_attempts a USING(tenant_id,account_id,work_id,attempt_id) JOIN {}.result_feed_events f USING(tenant_id,account_id,work_id,attempt_id)"
    ).format(name, name, name, name, name)


def verify() -> dict[str, object]:
    from uuid import UUID

    from psycopg import sql

    from delegation_reliability.applicability_models import parse_refresh, parse_tombstone
    from delegation_reliability.contracts import parse_result
    from delegation_reliability.processing_models import parse_ack
    from delegation_reliability.projection_models import parse_projected

    stage("verify_counts")
    first, action = load("first.json"), load("action.json")
    ws, cs, ps = (sql.Identifier(settings(kind).schema) for kind in ("work", "case", "projection"))
    with closing(settings().connect(application_name="continuity-test")) as connection:

        def count(schema: Any, table: str) -> int:
            row = connection.execute(
                sql.SQL("SELECT count(*) AS n FROM {}.{}").format(schema, sql.Identifier(table))
            ).fetchone()
            assert row is not None
            return int(row["n"])

        work_counts = {
            t: count(ws, t)
            for t in (
                "accepted_work",
                "issued_attempts",
                "attempt_results",
                "result_feed_events",
                "result_delivery_intents",
                "result_delivery_possible",
                "result_delivery_receipts",
                "result_actions",
            )
        }
        assert work_counts == dict.fromkeys(work_counts, 1)
        assert count(ws, "cancellation_commands") == 1
        assert all(
            count(cs, t) == 1
            for t in (
                "action_intents",
                "confirmations",
                "mutation_effects",
                "business_outcomes",
                "completion_events",
                "completion_deliveries",
            )
        )
        assert count(ps, "projected_results") == count(ps, "processing_acks") == 1
        assert count(ps, "applicability_refreshes") == 2
        stage("verify_source")
        row = connection.execute(source_query(settings().schema)).fetchone()
        assert row is not None and row["cancel_requested"] is True
        request = parse_request(bytes(row["body"]))
        result = parse_result(bytes(row["result_body"]))
        assert row["tenant_id"] == SCOPE.tenant_id and row["account_id"] == SCOPE.account_id
        assert bytes(row["body"]) == canonical(load("request.json"))
        assert (
            row["sha256"]
            == hashlib.sha256(bytes(row["body"])).hexdigest()
            == first["accepted_input_sha256"]
        )
        assert (
            row["result_sha256"]
            == hashlib.sha256(bytes(row["result_body"])).hexdigest()
            == first["result_sha256"]
        )
        assert (
            str(row["work_id"]) == first["work_id"]
            and str(row["attempt_id"]) == first["attempt_id"]
        )
        assert (
            row["command_id"] == COMMAND
            and str(row["owner_id"]) == load("identity.json")["owner_id"]
        )
        assert row["number"] == row["epoch"] == 1 and row["disposition"] == "eligible_at_commit"
        assert (
            result.attempt_id == "attempt_" + UUID(first["attempt_id"]).hex
            and result.input_fingerprint == request.input_fingerprint
        )
        stage("verify_projection")
        projection_row = connection.execute(
            sql.SQL("SELECT * FROM {}.projected_results").format(ps)
        ).fetchone()
        ack_row = connection.execute(
            sql.SQL("SELECT * FROM {}.processing_acks").format(ps)
        ).fetchone()
        assert projection_row is not None and ack_row is not None
        projected = parse_projected(projection_row["body_json"].encode())
        stage("verify_ack")
        ack = parse_ack(ack_row["body_json"].encode())
        assert json.loads(projected.canonical()) == load("projection.json") and json.loads(
            ack.canonical()
        ) == load("ack.json")
        assert (
            projected.event == ack.event
            and projected.event.work_id == first["work_id"]
            and projected.event.attempt_id == first["attempt_id"]
        )
        assert (
            projected.event.source_id == source_id()
            and projected.event.event_id == str(row["event_id"])
            and projected.event.sequence == 1
        )
        assert (
            projected.event.scope == WorkScope(SCOPE.tenant_id, SCOPE.account_id)
            and projected.event.result_sha256 == first["result_sha256"]
        )
        assert (
            ack.request_sha256 == projected.request_sha256 == row["sha256"]
            and ack.projected_sha256 == hashlib.sha256(projected.canonical()).hexdigest()
        )
        assert ack.receipt is not None and ack.receipt.receipt_id == first["receipt_id"]
        control = connection.execute(
            sql.SQL(
                "SELECT terminal_watermark,terminal_count FROM {}.processing_control WHERE singleton"
            ).format(ps)
        ).fetchone()
        assert control == {"terminal_watermark": 1, "terminal_count": 1}
        stage("verify_refresh")
        for name in ("refresh-first.json", "refresh-second.json"):
            refresh = parse_refresh(canonical(load(name)))
            stored = connection.execute(
                sql.SQL(
                    "SELECT body_json FROM {}.applicability_refreshes WHERE command_id=%s::uuid"
                ).format(ps),
                (refresh.command_id,),
            ).fetchone()
            assert stored is not None and json.loads(stored["body_json"]) == load(name)
            assert (
                refresh.event == projected.event
                and refresh.request_sha256 == projected.request_sha256
                and refresh.projected_sha256 == ack.projected_sha256
            )
        head = connection.execute(
            sql.SQL("SELECT * FROM {}.applicability_heads").format(ps)
        ).fetchone()
        assert head is not None and head["revision"] == 2 and head["tombstone_json"] is not None
        tomb = parse_tombstone(head["tombstone_json"].encode())
        assert (
            json.loads(tomb.canonical()) == load("tombstone.json") and tomb.event == projected.event
        )
        stage("verify_delivery")
        delivered = connection.execute(
            sql.SQL(
                "SELECT i.*,r.receipt_id::text,r.accepted_at_ms FROM {}.result_delivery_intents i JOIN {}.result_delivery_receipts r USING(delivery_id)"
            ).format(ws, ws)
        ).fetchone()
        assert delivered is not None
        assert (
            str(delivered["work_id"]) == first["work_id"]
            and str(delivered["attempt_id"]) == first["attempt_id"]
            and delivered["result_sha256"] == first["result_sha256"]
        )
        assert (
            delivered["receipt_id"] == ack.receipt.receipt_id
            and str(delivered["delivery_id"]) == ack.receipt.delivery_id
            and str(delivered["receiver_id"]) == ack.receipt.receiver_id
            and delivered["recipient_id"] == RECIPIENT
            and delivered["accepted_at_ms"] == ack.receipt.accepted_at_ms
        )
        stage("verify_action")
        guard = connection.execute(sql.SQL("SELECT * FROM {}.result_actions").format(ws)).fetchone()
        assert (
            guard is not None
            and str(guard["action_id"]) == action["action_id"] == first["action_id"]
        )
        for key in (
            "work_id",
            "attempt_id",
            "result_sha256",
            "case_schema",
            "case_scope_id",
            "case_actor_id",
            "case_task_id",
            "case_id",
            "expected_revision",
            "command_id",
            "committed_at_ms",
        ):
            assert str(guard[key]) == str(action[key])
        assert (
            json.loads(guard["confirmation_json"])
            == action["confirmation"]
            == confirmation().payload()
            and json.loads(guard["intent_json"]) == action["intent"]
        )
        stage("verify_effect")
        joined = connection.execute(
            sql.SQL(
                "SELECT i.*,c.payload_json AS confirmation_payload,c.actor_id AS confirmation_actor,c.scope_id AS confirmation_scope,e.state AS effect_state,e.result_json,e.dispatch_count FROM {}.action_intents i JOIN {}.confirmations c USING(confirmation_id,task_id) JOIN {}.mutation_effects e USING(intent_id,task_id) WHERE i.intent_id=%s"
            ).format(cs, cs, cs),
            (str(guard["intent_id"]),),
        ).fetchone()
        assert (
            joined is not None
            and json.loads(joined["payload_json"]) == action["intent"]
            and json.loads(joined["confirmation_payload"]) == action["confirmation"]
        )
        assert (
            joined["confirmation_actor"] == ACTOR.actor_id
            and joined["confirmation_scope"] == ACTOR.scope_id
            and joined["effect_state"] == "succeeded"
            and joined["dispatch_count"] == 1
        )
        stage("verify_business")
        business = connection.execute(
            sql.SQL(
                "SELECT o.payload_json AS outcome_json,e.event_id,e.payload_json AS event_json,d.state,d.attempts,d.target_id FROM {}.business_outcomes o JOIN {}.completion_events e USING(task_id) JOIN {}.completion_deliveries d USING(event_id)"
            ).format(cs, cs, cs)
        ).fetchone()
        assert (
            business is not None
            and business["state"] == "pending"
            and business["attempts"] == 0
            and business["target_id"] is None
        )
        outcome, event = json.loads(business["outcome_json"]), json.loads(business["event_json"])
        assert (
            event["outcome"] == outcome
            and outcome["effect_id"] == joined["effect_id"]
            and outcome["state"] == "succeeded"
            and outcome["task_id"] == load("case.json")["task_id"]
        )
    stage("verify_receiver")
    with closing(
        sqlite3.connect((folder() / "receiver.sqlite3").as_uri() + "?mode=ro", uri=True)
    ) as database:
        receipts = database.execute(
            "SELECT intent_json,receipt_json FROM result_receipts"
        ).fetchall()
        assert len(receipts) == 1
        intent, receipt = map(json.loads, receipts[0])
        assert receipt == asdict(ack.receipt) and intent["scope"] == asdict(SCOPE)
        assert (
            intent["work_id"] == first["work_id"]
            and intent["attempt_id"] == first["attempt_id"]
            and intent["result_sha256"] == first["result_sha256"]
        )
        assert (
            intent["delivery_id"] == receipt["delivery_id"] == first["delivery_id"]
            and intent["receiver_id"] == receipt["receiver_id"]
            and intent["recipient_id"] == receipt["recipient_id"] == RECIPIENT
        )
        assert (
            hashlib.sha256(base64.b64decode(intent["body"], validate=True)).hexdigest()
            == first["result_sha256"]
        )
    stage("verify_supplier")
    truth = cast(dict[str, Any], helper().supplier_truth(folder() / "supplier.sqlite3"))
    with closing(
        sqlite3.connect((folder() / "supplier.sqlite3").as_uri() + "?mode=ro", uri=True)
    ) as database:
        apply_calls = database.execute("SELECT count(*) FROM apply_calls").fetchone()[0]
    assert apply_calls == truth["applied_calls"] == len(truth["mutation_receipts"]) == 1 and truth[
        "bookings"
    ] == [
        [
            ACTOR.scope_id,
            confirmation().quote.booking_reference,
            confirmation().quote.new_check_in.isoformat(),
            1,
        ]
    ]
    supplier = truth["mutation_receipts"][0]
    assert (
        supplier["effect_id"] == joined["effect_id"] == first["effect_id"]
        and supplier["scope_id"] == ACTOR.scope_id
        and supplier["result"] == json.loads(joined["result_json"])
    )
    stage("verify_peer")
    peer = load("standalone-service.json")
    from dataclasses import replace

    transport = replace(
        request, attempt=replace(request.attempt, attempt_id=result.attempt_id, number=1)
    )
    assert (
        peer["request_sha256"] == hashlib.sha256(encode_request(transport)).hexdigest()
        and peer["wire_attempt_id"] == result.attempt_id
        and peer["scope"] == asdict(SCOPE)
    )
    assert (
        peer["invoked"] == peer["strict_completed"] == 1
        and peer["active"] == peer["requests"] == peer["sockets"] == 0
    )
    assert (
        sum(1 for _ in folder().glob("call_complete_receiver_accept_*.json"))
        == sum(1 for _ in folder().glob("call_complete_invoke_*.json"))
        == 1
    )
    assert not (folder() / "specialist-duplicate-invoke.json").exists()
    for mode in ("metadata", "negative", "replay", "cancel"):
        assert not list(folder().glob(f"call_{mode}_*.json"))
    stage("verify_inventory")
    counts = dict.fromkeys(
        (
            "accepted",
            "action_receipts",
            "attempts",
            "business_outcomes",
            "case_intents",
            "confirmations",
            "delivery_intents",
            "delivery_receipts",
            "display_tombstones",
            "events",
            "mutation_effects",
            "processing_acks",
            "projected_results",
            "results",
            "supplier_apply_calls",
            "supplier_receipts",
        ),
        1,
    )
    counts["refresh_commands"] = 2
    metadata = {
        "source_id": source_id(),
        "event_id": projected.event.event_id,
        "projection_sha256": hashlib.sha256(projected.canonical()).hexdigest(),
        "processing_ack_sha256": hashlib.sha256(ack.canonical()).hexdigest(),
        "first_refresh_sha256": hashed(load("refresh-first.json")),
        "second_refresh_sha256": hashed(load("refresh-second.json")),
        "display_tombstone_sha256": hashed(load("tombstone.json")),
        "terminal_watermark": 1,
        "terminal_count": 1,
    }
    identity = {
        "scope": asdict(SCOPE),
        "work_id": first["work_id"],
        "delegation_id": request.delegation_id,
        "request_sha256": row["sha256"],
        "wire_request_sha256": hashlib.sha256(encode_request(transport)).hexdigest(),
        "input_fingerprint": request.input_fingerprint,
        "attempt_id": first["attempt_id"],
        "issue_command_id": COMMAND,
        "owner_id": str(row["owner_id"]),
        "result_sha256": first["result_sha256"],
        "source_id": source_id(),
        "event_id": projected.event.event_id,
        "case_task_id": action["case_task_id"],
        "case_id": action["case_id"],
        "case_revision": 2,
        "quote_sha256": hashed(confirmation().quote.payload()),
        "confirmation_sha256": hashed(confirmation().payload()),
        "action_id": first["action_id"],
        "intent_id": first["intent_id"],
        "effect_id": first["effect_id"],
        "supplier_result_sha256": hashed(supplier["result"]),
        "delivery_id": first["delivery_id"],
        "receiver_id": first["receiver_id"],
        "recipient_id": RECIPIENT,
        "receipt_id": first["receipt_id"],
        "processing_ack_sha256": metadata["processing_ack_sha256"],
    }
    inventory = [
        {"kind": "counts", **counts},
        {"kind": "identity", **identity},
        {"kind": "metadata", **metadata},
    ]
    save(
        "standalone-authority.json",
        {
            "schema_version": 1,
            "status": "passed",
            "counts": counts,
            "identity": identity,
            "metadata": metadata,
            "inventory_sha256": inventory_digest(inventory),
        },
    )
    save(
        "standalone-replay.json",
        {
            "schema_version": 1,
            "status": "passed",
            "first": first,
            "replay": load("replay.json"),
            "after_cancel": load("after-cancel.json"),
            "new_call_counts": load("replay-calls.json"),
            "cleanup": {
                "first": load("first-cleanup.json"),
                "replay": load("replay-cleanup.json"),
                "public_pending": 0,
            },
        },
    )
    return reply()


def cleanup() -> dict[str, object]:
    from psycopg import sql

    owned = load("owned.json")
    assert owned == {
        "marker": "p3-standalone-fixture-v1",
        "work": settings().schema,
        "case": settings("case").schema,
        "projection": settings("projection").schema,
    }
    first: BaseException | None = None
    try:
        helper().cleanup(settings("case"))
    except BaseException as error:  # noqa: BLE001 - attempt all independent cleanup; preserve primary.
        first = error
    for kind, pattern, markers in (
        (
            "work",
            r"p1_work_standalone_[0-9a-f]{32}",
            {"continuity-readonly-work-v" + str(x) for x in range(1, 5)},
        ),
        (
            "projection",
            r"p3_projection_standalone_[0-9a-f]{32}",
            {"delegation-result-projection-v" + str(x) for x in range(1, 4)},
        ),
    ):
        try:
            value = settings(kind)
            assert re.fullmatch(pattern, value.schema)
            with closing(value.connect(application_name="continuity-test")) as connection:
                row = connection.execute(
                    "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                    (value.schema,),
                ).fetchone()
                if row is not None:
                    assert row["owner"] == "continuity_migrator" and row["marker"] in markers
                    connection.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(value.schema))
                    )
                assert (
                    connection.execute(
                        "SELECT 1 FROM pg_namespace WHERE nspname=%s", (value.schema,)
                    ).fetchone()
                    is None
                )
        except BaseException as error:  # noqa: BLE001 - attempt all independent cleanup; preserve primary.
            if first is None:
                first = error
    if first is not None:
        raise first
    return reply()


def main() -> None:
    global MODE
    os.umask(0o077)
    assert len(sys.argv) == 2 and sys.argv[1] in MODES
    MODE = sys.argv[1]
    try:
        function = {
            "install": install,
            "seed": seed,
            "complete": complete,
            "effect": effect,
            "metadata": metadata,
            "negative": negative,
            "replay": replay,
            "cancel": cancel,
            "verify": verify,
            "cleanup": cleanup,
        }[MODE]
        value = function()
        if asyncio.iscoroutine(value):
            value = asyncio.run(value)
        print(json.dumps(value, separators=(",", ":")))
    except Exception as error:  # noqa: BLE001 - no raw exception text or private values.
        code = (
            cast(Any, error).code
            if type(error)
            in (
                WorkError,
                ActionError,
                CoordinatorError,
                CompletionError,
                DelegationRunError,
                ProjectionError,
                ContractError,
                InvalidConfirmation,
            )
            else "fixture_failed"
        )
        if type(code) is not str or code not in SAFE_CODES:
            code = "fixture_failed"
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "failed",
                    "mode": MODE,
                    "stage": STAGE,
                    "code": code,
                    "cleanup_failed": CLEANUP_FAILED,
                },
                separators=(",", ":"),
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
