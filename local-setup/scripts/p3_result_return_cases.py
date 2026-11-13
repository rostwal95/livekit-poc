"""Source public-port delivery consumer; parent owns PostgreSQL and the P2 host.

The specialist is an explicit local scripted port, not HTTP or model inference.
Three real P1 results exercise two P2 deliveries and one outdated-delivery denial.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from typing import Any, Protocol, TypeVar, cast
from uuid import UUID

import aiohttp

from continuity_lab.case_control_api import BookingChange, open_case_control_client
from continuity_lab.delivery_api import (
    DeliveryIntent,
    DeliveryReceipt,
    DeliverySnapshot,
    open_delivery_client,
)
from continuity_lab.execution_api import open_execution_client
from continuity_lab.postgres_api import AuthenticatedActor, open_postgres_client
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
    CaseBinding,
    CompletionError,
    DelegationRunError,
    DeliveryBinding,
    FixedPolicyCoordinator,
    FixedPolicyDeliveryClient,
    FixedPolicyResultObservation,
    FixedPolicyRunner,
    ManagedCaseAuthority,
)
from delegation_reliability.contracts import EvidenceRef, Scope, canonical
from delegation_reliability.fixed_policy import verify_fixed_policy_facts
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    FixedPolicyResult,
    encode_fixed_policy_request,
    encode_fixed_policy_result,
    parse_fixed_policy_result,
    produce_fixed_policy_request,
)
from delegation_reliability.security import EvidenceRecord


def _receiver_module() -> Any:
    """Load this one adjacent application helper under -I; installed products stay installed."""
    name = "p3_result_return_receiver_helper"
    retained = sys.modules.get(name)
    if retained is not None:
        return retained
    path = Path(__file__).resolve().with_name("p3_channel_receiver.py")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ChannelResultReceiver = _receiver_module().ChannelResultReceiver

BASE = {"PATH", "LANG", "CI", "NO_COLOR", "__CF_USER_TEXT_ENCODING"}
ENVIRONMENT = {
    "P3_RESULT_DIRECTORY",
    "P3_RESULT_PG_PORT",
    "P3_RESULT_RUNTIME_PASSWORD",
    "P3_RESULT_WORK_TOKEN",
    "P3_RESULT_CASE_TOKEN",
    "P3_RESULT_PUBLISHER_TOKEN",
    "P3_RESULT_NATIVE_B_BEARER",
}
STAGE, LABEL = "configuration", None


def read(path: Path, maximum: int = 32768) -> dict[str, Any]:
    info = path.lstat()
    assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
    assert info.st_uid == os.geteuid() and info.st_nlink == 1 and 0 < info.st_size <= maximum
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        raw = stream.read(maximum + 1)
        opened = os.fstat(stream.fileno())
    assert (opened.st_dev, opened.st_ino, opened.st_size) == (info.st_dev, info.st_ino, len(raw))
    value = json.loads(raw)
    assert type(value) is dict
    return cast(dict[str, Any], value)


def publish(path: Path, value: object) -> None:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    assert 0 < len(raw) <= 131072
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)


def uuid(value: object) -> str:
    assert type(value) is str and str(UUID(value)) == value and UUID(value).version == 4
    return value


def run_command(label: str, owner_id: str) -> str:
    """Give the immutable fixture owner a distinct valid command identity."""
    assert label in {"original", "stale", "current"}
    return "return_" + label + "_" + UUID(uuid(owner_id)).hex


def configuration(directory: Path) -> dict[str, Any]:
    assert ENVIRONMENT <= os.environ.keys() and not set(os.environ) - ENVIRONMENT - BASE
    info = directory.lstat()
    assert (
        directory.is_absolute() and directory.resolve() == directory and not directory.is_symlink()
    )
    assert stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
    for key in ENVIRONMENT - {
        "P3_RESULT_DIRECTORY",
        "P3_RESULT_PG_PORT",
        "P3_RESULT_RUNTIME_PASSWORD",
    }:
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", os.environ[key])
    assert re.fullmatch(r"[1-9][0-9]{0,4}", os.environ["P3_RESULT_PG_PORT"])
    assert 1 <= int(os.environ["P3_RESULT_PG_PORT"]) <= 65535
    value = read(directory / "p3-return-config.json")
    assert (
        set(value)
        == {
            "schema_version",
            "scope",
            "case_id",
            "conversation_id",
            "recipient_id",
            "receiver_id",
            "receiver_port",
            "task_id",
            "authority_case_id",
            "case_schema",
            "work_schema",
            "supplier_path",
            "owners",
        }
        and type(value["schema_version"]) is int
        and value["schema_version"] == 1
    )
    assert type(value["receiver_port"]) is int and 1 <= value["receiver_port"] <= 65535
    for key in ("case_id", "conversation_id", "recipient_id"):
        assert re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value[key])
    assert set(value["scope"]) == {"tenant_id", "account_id"}
    for identifier in value["scope"].values():
        assert re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", identifier)
    assert re.fullmatch(r"p3_completion_[0-9a-f]{32}", value["case_schema"])
    assert re.fullmatch(r"p1_work_result_[0-9a-f]{32}", value["work_schema"])
    uuid(value["receiver_id"])
    assert set(value["owners"]) == {"original", "stale", "current"}
    for owner in value["owners"].values():
        uuid(owner)
    supplier = Path(value["supplier_path"])
    assert supplier.parent == directory and supplier.is_file() and not supplier.is_symlink()
    return value


class ScriptedPolicy:
    """Deterministic supplied port; production runner independently verifies facts."""

    def __init__(self, template: FixedPolicyResult) -> None:
        self.template = template
        self.invocations = 0
        self.closed = False

    async def invoke_observed(
        self, request: FixedPolicyRequest, *, evidence: tuple[EvidenceRecord, ...]
    ) -> FixedPolicyResultObservation:
        self.invocations += 1
        result = replace(
            self.template,
            scope=request.scope,
            delegation_id=request.delegation_id,
            case_id=request.case_id,
            request_revision=request.request_revision,
            attempt_id=request.attempt.attempt_id,
            input_fingerprint=request.input_fingerprint,
            completed_at_ms=time.time_ns() // 1_000_000,
        )
        now = time.time_ns() // 1_000_000
        state = verify_fixed_policy_facts(request, result, evidence, observed_at_ms=now)
        return FixedPolicyResultObservation(result, state, now)

    async def close(self) -> None:
        self.closed = True


class _Closeable(Protocol):
    async def close(self) -> None: ...


OwnerT = TypeVar("OwnerT", bound=_Closeable)


class OwnedResources:
    """Track construction before awaiting and transfer ownership only after construction succeeds."""

    def __init__(self) -> None:
        self.tiers: list[list[_Closeable]] = [[], [], []]
        self.startups: set[asyncio.Task[Any]] = set()
        self.close_observers: dict[int, asyncio.Task[None]] = {}
        self.cleanup_complete = False

    def add(self, value: OwnerT, tier: int) -> OwnerT:
        self.tiers[tier].append(value)
        return value

    async def startup(self, factory: Callable[[], OwnerT], tier: int) -> OwnerT:
        async def actual() -> OwnerT:
            value = await asyncio.to_thread(factory)
            return self.add(value, tier)

        task = asyncio.create_task(actual(), name="result-return-public-startup")
        self.startups.add(task)
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        # A cancelled caller leaves the actual startup and its late returned owner retained.
        return await asyncio.shield(task)

    def transfer(self, owner: OwnerT, children: tuple[_Closeable, ...], tier: int) -> OwnerT:
        assert all(any(child is existing for existing in self.tiers[tier]) for child in children)
        self.tiers[tier].append(owner)
        for child in children:
            self.tiers[tier] = [value for value in self.tiers[tier] if value is not child]
        return owner

    async def close_selected(self, values: tuple[_Closeable, ...]) -> bool:
        tasks: list[asyncio.Task[None]] = []
        for value in values:
            task = self.close_observers.get(id(value))
            if task is None or (task.done() and (task.cancelled() or task.exception() is not None)):
                task = asyncio.create_task(value.close(), name="result-return-close-observer")
                self.close_observers[id(value)] = task
            tasks.append(task)
        observed = await asyncio.gather(
            *(asyncio.shield(task) for task in tasks), return_exceptions=True
        )
        complete = True
        for value, outcome in zip(values, observed, strict=True):
            if isinstance(outcome, BaseException):
                complete = False
            else:
                for tier in self.tiers:
                    tier[:] = [retained for retained in tier if retained is not value]
        return complete

    async def close(self) -> bool:
        # The parent owns the finite process/cleanup deadline. Never abandon a running factory
        # and close readers underneath its late result. These public startup tasks stay owned.
        if self.startups:
            await asyncio.gather(
                *(asyncio.shield(task) for task in self.startups), return_exceptions=True
            )
        for tier in self.tiers:
            if not await self.close_selected(tuple(tier)):
                return False
        self.cleanup_complete = True
        return True

    def observation(self) -> dict[str, object]:
        return {
            "startup_tasks": len(self.startups),
            "startup_pending": sum(not task.done() for task in self.startups),
            "retained_tiers": [len(tier) for tier in self.tiers],
            "close_observers_pending": sum(
                not task.done() for task in self.close_observers.values()
            ),
            "cleanup_complete": self.cleanup_complete,
        }


def _closed(value: object, fields: set[str]) -> dict[str, Any]:
    assert type(value) is dict and set(value) == fields
    return cast(dict[str, Any], value)


def _instant(value: object) -> str:
    assert type(value) is str and re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", value
    )
    return value


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        assert key not in result
        result[key] = value
    return result


def _invalid_number(_: str) -> Any:
    raise ValueError("invalid_number")


def validate_native_view(
    config: dict[str, Any], value: object, intent: DeliveryIntent, receipt: DeliveryReceipt
) -> dict[str, Any]:
    envelope = _closed(value, {"schemaVersion", "status", "view"})
    assert type(envelope["schemaVersion"]) is int and envelope["schemaVersion"] == 1
    assert envelope["status"] == "known"
    view = _closed(envelope["view"], {"schemaVersion", "intent", "receipt", "case", "observed"})
    assert type(view["schemaVersion"]) is int and view["schemaVersion"] == 1
    assert view["intent"] == json.loads(intent.canonical())
    assert view["receipt"] == asdict(receipt)
    case = _closed(
        view["case"],
        {
            "schemaVersion",
            "source",
            "scope",
            "caseId",
            "conversationId",
            "revision",
            "request",
            "workflow",
            "intent",
            "mutation",
            "supplierResult",
            "sourceRevision",
        },
    )
    assert type(case["schemaVersion"]) is int and case["schemaVersion"] == 1
    assert case["source"] == "p1_public_v4" and case["revision"] == "2"
    assert case["scope"] == {
        "tenantId": config["scope"]["tenant_id"],
        "accountId": config["scope"]["account_id"],
    }
    assert (case["caseId"], case["conversationId"]) == (
        config["case_id"],
        config["conversation_id"],
    )
    assert type(case["sourceRevision"]) is str and re.fullmatch(
        r"[0-9a-f]{64}", case["sourceRevision"]
    )
    assert len(json.dumps(case, ensure_ascii=False, separators=(",", ":")).encode()) <= 4096
    observed = _closed(
        view["observed"], {"p2ObservedAt", "caseObservedAt", "disclosureAdmittedAt", "atomic"}
    )
    assert observed["atomic"] is False
    for key in ("p2ObservedAt", "caseObservedAt", "disclosureAdmittedAt"):
        _instant(observed[key])
    # The returned current-case facts are separate observations, not candidate/action authority.
    return view


async def native_read(
    config: dict[str, Any], intent: DeliveryIntent, receipt: DeliveryReceipt
) -> dict[str, Any]:
    async with (
        aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=3),
            trust_env=False,
            auto_decompress=False,
            cookie_jar=aiohttp.DummyCookieJar(),
        ) as session,
        session.post(
            f"http://127.0.0.1:{config['receiver_port']}/v1/p2-result-receiver/native-read",
            headers={"Authorization": "Bearer " + os.environ["P3_RESULT_NATIVE_B_BEARER"]},
            json={"schemaVersion": 1, "deliveryId": intent.delivery_id},
            allow_redirects=False,
            max_headers=32,
            max_line_size=2048,
            max_field_size=2048,
        ) as response,
    ):
        assert response.status == 200 and response.headers.getall("Cache-Control", []) == [
            "no-store"
        ]
        assert response.headers.getall("Content-Type", []) == ["application/json"]
        assert response.headers.getall("Connection", []) == ["close"]
        assert "Content-Encoding" not in response.headers
        lengths = response.headers.getall("Content-Length", [])
        assert len(lengths) == 1 and re.fullmatch(r"[1-9][0-9]{0,4}", lengths[0])
        assert 0 < int(lengths[0]) <= 32768 and "Transfer-Encoding" not in response.headers
        raw = await response.content.readexactly(int(lengths[0]))
        value = json.loads(raw, object_pairs_hook=_json_pairs, parse_constant=_invalid_number)
        return validate_native_view(config, value, intent, receipt)


def snapshot_wire(value: DeliverySnapshot) -> dict[str, object]:
    return {
        "intent": None if value.intent is None else json.loads(value.intent.canonical()),
        "possible": value.possible,
        "receipt": None if value.receipt is None else asdict(value.receipt),
    }


async def exercise(directory: Path, config: dict[str, Any]) -> dict[str, Any]:
    global STAGE, LABEL
    resources = OwnedResources()
    proofs: dict[str, Any] = {}
    remote_calls = 0
    primary: BaseException | None = None
    try:
        STAGE = "ports"
        source = read(directory / "p3-return-policy.json")
        scope = Scope(**config["scope"])
        records = tuple(
            EvidenceRecord(scope, EvidenceRef(**ref), body.encode())
            for ref, body in zip(
                source["producer_input"]["evidence"],
                (source["policy_body_utf8"], source["facts_body_utf8"]),
                strict=True,
            )
        )
        for record in records:
            assert hashlib.sha256(record.body).hexdigest() == record.reference.sha256
        work_scope = WorkScope(scope.tenant_id, scope.account_id)
        work_token = BearerToken(os.environ["P3_RESULT_WORK_TOKEN"])
        case_token = BearerToken(os.environ["P3_RESULT_CASE_TOKEN"])
        registrations = WorkDirectory(
            {work_token: WorkPrincipal("result_return_actor", work_scope)}
        )
        settings = {
            key: PostgresSettings(
                port=int(os.environ["P3_RESULT_PG_PORT"]),
                password=os.environ["P3_RESULT_RUNTIME_PASSWORD"],
                schema=config[key + "_schema"],
            )
            for key in ("case", "work")
        }
        actor = AuthenticatedActor("p3_completion_user", "p3_completion_scope")
        case_client = await resources.startup(
            lambda: open_postgres_client(
                actor=actor,
                token=case_token,
                settings=settings["case"],
                quote_database=Path(config["supplier_path"]),
            ),
            2,
        )
        controller = await resources.startup(
            lambda: open_case_control_client(
                actor=actor,
                token=case_token,
                settings=settings["case"],
                quote_database=Path(config["supplier_path"]),
            ),
            2,
        )
        authority = ManagedCaseAuthority(
            case_client,
            scope=scope,
            bindings=(
                CaseBinding(config["case_id"], config["task_id"], config["authority_case_id"]),
            ),
        )
        work_client = await resources.startup(
            lambda: open_work_client(
                settings=settings["work"], directory=registrations, token=work_token
            ),
            1,
        )
        coordinator = resources.transfer(
            FixedPolicyCoordinator(executions=work_client, scope=scope, case_authority=authority),
            (work_client,),
            1,
        )

        async def delivery_for(runner: FixedPolicyRunner) -> tuple[FixedPolicyDeliveryClient, Any]:
            port = await resources.startup(
                lambda: open_delivery_client(
                    settings=settings["work"], directory=registrations, token=work_token
                ),
                0,
            )
            receiver = resources.add(
                ChannelResultReceiver(
                    port=config["receiver_port"],
                    publisher_token=os.environ["P3_RESULT_PUBLISHER_TOKEN"],
                    receiver_id=config["receiver_id"],
                    scope=work_scope,
                    recipient_id=config["recipient_id"],
                ),
                0,
            )
            delivery = FixedPolicyDeliveryClient(
                results=runner,
                deliveries=port,
                receiver=receiver,
                scope=scope,
                evidence=records,
                bindings=(
                    DeliveryBinding(
                        config["case_id"], config["conversation_id"], config["recipient_id"]
                    ),
                ),
            )
            return resources.transfer(delivery, (port, receiver), 0), receiver

        assert (await controller.case(task_id=config["task_id"])).revision == 1
        stale_delivery: FixedPolicyDeliveryClient | None = None
        original_delivery: FixedPolicyDeliveryClient | None = None
        original_snapshot: DeliverySnapshot | None = None
        original_receiver: Any = None
        for label, revision in (("original", 1), ("stale", 1), ("current", 2)):
            LABEL = label
            if label == "current":
                STAGE = "revision"
                changed = await controller.revise(
                    task_id=config["task_id"],
                    expected_revision=1,
                    request=BookingChange("DEMO-BK-001", date(2030, 12, 12), True),
                )
                assert changed.revision == 2
                assert stale_delivery is not None
                try:
                    await stale_delivery.deliver_once(proofs["stale"]["work_id"])
                except CompletionError as error:
                    assert error.code == "not_eligible"
                    proofs["stale"]["new_delivery_error"] = error.code
                else:
                    raise AssertionError("outdated_result_delivered")
                stale = await stale_delivery.inspect(proofs["stale"]["work_id"])
                assert stale.state == "missing" and stale.snapshot.intent is None
                proofs["stale"]["delivery"] = {"state": stale.state, "intent": None}
                assert original_delivery is not None and original_snapshot is not None
                before = dict(original_receiver.metrics)
                retained = await original_delivery.deliver_once(proofs["original"]["work_id"])
                assert retained.snapshot == original_snapshot and not retained.receiver_invoked
                assert dict(original_receiver.metrics) == before
                proofs["original"]["historical_replay"] = {
                    "snapshot": snapshot_wire(retained.snapshot),
                    "receiver_invoked": retained.receiver_invoked,
                    "receiver_metrics_before": before,
                    "receiver_metrics_after": dict(original_receiver.metrics),
                }
                assert (
                    retained.snapshot.intent is not None and retained.snapshot.receipt is not None
                )
                STAGE = "native_read"
                proofs["original"]["return_view"] = await native_read(
                    config, retained.snapshot.intent, retained.snapshot.receipt
                )

            raw = json.loads(json.dumps(source["producer_input"]))
            raw.update(
                scope=config["scope"],
                delegation_id="return_" + label,
                case_id=config["case_id"],
                request_revision=revision,
                deadline_at_ms=time.time_ns() // 1_000_000 + 60_000,
                result_route={"conversation_id": config["conversation_id"]},
            )
            request = produce_fixed_policy_request(raw)
            STAGE = "submit"
            accepted = await coordinator.submit(request)
            assert accepted.created
            remote = resources.add(
                ScriptedPolicy(parse_fixed_policy_result(canonical(source["result"]))), 1
            )
            execution = await resources.startup(
                lambda: open_execution_client(
                    settings=settings["work"], directory=registrations, token=work_token
                ),
                1,
            )
            runner = resources.transfer(
                FixedPolicyRunner(
                    executions=execution,
                    scope=scope,
                    owner_id=config["owners"][label],
                    specialist=remote,
                    case_authority=authority,
                    evidence=records,
                ),
                (execution, remote),
                1,
            )
            work_id = accepted.view.record.work_id
            STAGE = "run"
            executed = await runner.run_once(work_id, run_command(label, config["owners"][label]))
            assert (
                executed.invoked
                and executed.recorded is not None
                and executed.view.result is not None
            )
            assert (
                executed.recorded.disposition == "eligible_at_commit"
                and executed.view.applicability == "candidate"
            )
            remote_calls += remote.invocations
            observed = executed.view.execution
            assert observed.current_attempt is not None
            proof: dict[str, Any] = {
                "work_id": work_id,
                "request_canonical": encode_fixed_policy_request(request).decode(),
                "result_canonical": encode_fixed_policy_result(executed.view.result).decode(),
                "issued": {
                    key: getattr(observed.current_attempt, key)
                    for key in (
                        "attempt_id",
                        "command_id",
                        "number",
                        "owner_id",
                        "epoch",
                        "issued_at_ms",
                        "lease_until_ms",
                    )
                },
                "recorded": {
                    "attempt_id": executed.recorded.attempt_id,
                    "sha256": executed.recorded.sha256,
                    "recorded_at_ms": executed.recorded.recorded_at_ms,
                    "disposition": executed.recorded.disposition,
                },
            }
            proofs[label] = proof
            publish(directory / f"p3-return-{label}-recorded.json", proof)
            if label == "stale":
                stale_delivery, _ = await delivery_for(runner)
                continue
            if label == "original":
                STAGE = "ack_loss"
                old_port = await resources.startup(
                    lambda: open_delivery_client(
                        settings=settings["work"], directory=registrations, token=work_token
                    ),
                    0,
                )
                old_receiver = resources.add(
                    ChannelResultReceiver(
                        port=config["receiver_port"],
                        publisher_token=os.environ["P3_RESULT_PUBLISHER_TOKEN"],
                        receiver_id=config["receiver_id"],
                        scope=work_scope,
                        recipient_id=config["recipient_id"],
                    ),
                    0,
                )
                plan = await old_port.prepare(
                    work_id=work_id,
                    attempt_id=observed.current_attempt.attempt_id,
                    result_sha256=executed.recorded.sha256,
                    receiver_id=config["receiver_id"],
                    recipient_id=config["recipient_id"],
                )
                started = await old_port.begin(intent=plan)
                assert started.created and started.intent == plan
                before_possible = await old_port.inspect(work_id=work_id)
                assert before_possible.possible and before_possible.receipt is None
                receiver_receipt = await old_receiver.accept(plan)
                still_possible = await old_port.inspect(work_id=work_id)
                assert still_possible == before_possible
                proof["ack_loss"] = {
                    "kind": "simulated_sender_ack_loss_no_process_kill",
                    "before_receiver": snapshot_wire(before_possible),
                    "after_receiver_before_record": snapshot_wire(still_possible),
                    "receiver_receipt": asdict(receiver_receipt),
                    "receiver_metrics": dict(old_receiver.metrics),
                }
                publish(directory / "p3-return-original-ack-loss.json", proof)
                assert await resources.close_selected((old_port, old_receiver))

            STAGE = "delivery"
            delivery, receiver = await delivery_for(runner)
            accepted_delivery = await delivery.deliver_once(work_id)
            assert accepted_delivery.state == "accepted"
            if label == "original":
                assert not accepted_delivery.receiver_invoked
                assert receiver.metrics["accepted"] == 0 and receiver.metrics["found"] == 1
            else:
                assert accepted_delivery.receiver_invoked
                assert receiver.metrics["accepted"] == 1 and receiver.metrics["found"] == 0
            assert (
                accepted_delivery.snapshot.intent is not None
                and accepted_delivery.snapshot.receipt is not None
            )
            again = await delivery.deliver_once(work_id)
            assert again.snapshot == accepted_delivery.snapshot and not again.receiver_invoked
            proof["delivery"] = {
                "state": accepted_delivery.state,
                "intent": json.loads(accepted_delivery.snapshot.intent.canonical()),
                "receipt": asdict(accepted_delivery.snapshot.receipt),
                "receiver_invoked": accepted_delivery.receiver_invoked,
                "receiver_metrics": dict(receiver.metrics),
            }
            if label == "original":
                original_delivery, original_snapshot, original_receiver = (
                    delivery,
                    accepted_delivery.snapshot,
                    receiver,
                )
                assert (
                    asdict(accepted_delivery.snapshot.receipt)
                    == proof["ack_loss"]["receiver_receipt"]
                )
            if label == "current":
                STAGE = "native_read"
                proof["return_view"] = await native_read(
                    config, accepted_delivery.snapshot.intent, accepted_delivery.snapshot.receipt
                )
            publish(directory / f"p3-return-{label}-delivery.json", proof)
        assert remote_calls == 3
    except BaseException as error:
        # Preserve the original cancellation/failure while all acquired owners are drained by tier.
        primary = error
        raise
    finally:
        complete = await resources.close()
        publish(
            directory / "p3-return-ownership.json", {"schema_version": 1, **resources.observation()}
        )
        if not complete and primary is None:
            raise RuntimeError("owned_cleanup_incomplete")
    return {
        "schema_version": 1,
        "status": "passed",
        "kind": "p3_result_return",
        "scripted_port_invocations": remote_calls,
        "provider_calls": False,
        "p2_notices": 2,
        "results": proofs,
        "cleanup_complete": resources.cleanup_complete,
    }


def main() -> int:
    directory = Path(os.environ["P3_RESULT_DIRECTORY"])
    try:
        config = configuration(directory)
        result = asyncio.run(exercise(directory, config))
        publish(directory / "p3-return-proof.json", result)
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "passed",
                    "results": 3,
                    "deliveries": 2,
                    "outdated_denied": 1,
                    "provider_calls": False,
                }
            )
        )
        return 0
    except Exception as error:  # noqa: BLE001 - fixed outer fixture failure vocabulary
        safe_code = (
            error.code
            if isinstance(error, (CompletionError, WorkError, DelegationRunError))
            else "consumer_failed"
        )
        publish(
            directory / "p3-return-failure.json",
            {
                "schema_version": 1,
                "status": "failed",
                "stage": STAGE,
                "case": LABEL,
                "code": safe_code,
            },
        )
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "failed",
                    "code": safe_code,
                    "stage": STAGE,
                    "case": LABEL,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
