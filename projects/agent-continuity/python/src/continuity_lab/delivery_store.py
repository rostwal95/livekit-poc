"""P1 result delivery bindings and observed receipts, without an outbox worker."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar
from uuid import uuid4

from psycopg import sql

from .delivery_models import (
    DeliveryIntent,
    DeliveryReceipt,
    DeliverySnapshot,
    DeliveryStart,
    match_receipt,
    result_digest,
)
from .execution_store import ExecutionStore
from .issued_models import AttemptResult
from .work_models import WorkError, WorkScope, work_identifier, work_uuid
from .work_schema import Connection
from .work_store import WorkStore

T = TypeVar("T")


class DeliveryStore:
    def __init__(self, work: WorkStore) -> None:
        self.work = work
        self.execution = ExecutionStore(work)

    def _table(self, name: str) -> sql.Identifier:
        return self.work._table(name)

    def _write(self, operation: str, run: Callable[[Connection, int], T]) -> T:
        return self.execution._write(operation, run)

    def _read(self, operation: str, run: Callable[[Connection, int], T]) -> T:
        return self.execution._read(operation, run)

    def _intent(
        self, connection: Connection, scope: WorkScope, work_id: str
    ) -> DeliveryIntent | None:
        row = connection.execute(
            sql.SQL(
                "SELECT d.delivery_id::text,d.work_id::text,d.attempt_id::text,d.result_sha256,d.receiver_id::text,d.recipient_id,d.prepared_at_ms,r.body,r.sha256 AS stored_sha256 FROM {} d JOIN {} r ON r.attempt_id=d.attempt_id WHERE d.tenant_id=%s AND d.account_id=%s AND d.work_id=%s::uuid"
            ).format(self._table("result_delivery_intents"), self._table("attempt_results")),
            [scope.tenant_id, scope.account_id, work_id],
        ).fetchone()
        if row is None:
            return None
        try:
            if row["result_sha256"] != row["stored_sha256"]:
                raise WorkError("schema_mismatch")
            return DeliveryIntent(
                row["delivery_id"],
                scope,
                row["work_id"],
                row["attempt_id"],
                row["result_sha256"],
                row["receiver_id"],
                row["recipient_id"],
                row["body"],
                row["prepared_at_ms"],
            )
        except (WorkError, KeyError, TypeError, ValueError):
            raise WorkError("schema_mismatch") from None

    def _exact(
        self, connection: Connection, scope: WorkScope, expected: DeliveryIntent
    ) -> DeliveryIntent:
        if expected.scope != scope:
            raise WorkError("unauthorized")
        actual = self._intent(connection, scope, expected.work_id)
        if actual is None:
            raise WorkError("not_found")
        if actual != expected:
            raise WorkError("identity_conflict")
        return actual

    def _eligible(
        self,
        connection: Connection,
        scope: WorkScope,
        work_id: str,
        attempt_id: str,
        digest: str,
        now: int,
    ) -> AttemptResult:
        record = self.work._get(connection, scope, work_id)
        if record.cancel_requested or record.payload.deadline_at_ms <= now:
            raise WorkError("expired")
        latest = self.execution._latest(connection, scope, work_id)
        result = self.execution._result(connection, scope, work_id, attempt_id)
        if (
            latest is None
            or latest.attempt_id != attempt_id
            or result is None
            or result.sha256 != digest
            or result.disposition != "eligible_at_commit"
        ):
            raise WorkError("identity_conflict")
        return result

    def prepare(
        self,
        scope: WorkScope,
        work_id: str,
        attempt_id: str,
        digest: str,
        receiver_id: str,
        recipient_id: str,
    ) -> DeliveryIntent:
        work_uuid(work_id)
        work_uuid(attempt_id)
        work_uuid(receiver_id)
        result_digest(digest)
        work_identifier(recipient_id)

        def prepare(connection: Connection, now: int) -> DeliveryIntent:
            original = self._intent(connection, scope, work_id)
            if original is not None:
                if (
                    original.attempt_id,
                    original.result_sha256,
                    original.receiver_id,
                    original.recipient_id,
                ) != (attempt_id, digest, receiver_id, recipient_id):
                    raise WorkError("identity_conflict")
                return original
            result = self._eligible(connection, scope, work_id, attempt_id, digest, now)
            intent = DeliveryIntent(
                str(uuid4()),
                scope,
                work_id,
                attempt_id,
                digest,
                receiver_id,
                recipient_id,
                result.body,
                now,
            )
            connection.execute(
                sql.SQL(
                    "INSERT INTO {} VALUES(%s::uuid,%s,%s,%s::uuid,%s::uuid,%s,%s::uuid,%s,%s)"
                ).format(self._table("result_delivery_intents")),
                [
                    intent.delivery_id,
                    scope.tenant_id,
                    scope.account_id,
                    work_id,
                    attempt_id,
                    digest,
                    receiver_id,
                    recipient_id,
                    now,
                ],
            )
            return intent

        return self._write("delivery_prepare", prepare)

    def _possible(self, connection: Connection, delivery_id: str) -> bool:
        return (
            connection.execute(
                sql.SQL("SELECT 1 FROM {} WHERE delivery_id=%s::uuid").format(
                    self._table("result_delivery_possible")
                ),
                [delivery_id],
            ).fetchone()
            is not None
        )

    def _receipt(self, connection: Connection, intent: DeliveryIntent) -> DeliveryReceipt | None:
        row = connection.execute(
            sql.SQL(
                "SELECT receipt_id::text,receiver_id::text,recipient_id,result_sha256,accepted_at_ms FROM {} WHERE delivery_id=%s::uuid"
            ).format(self._table("result_delivery_receipts")),
            [intent.delivery_id],
        ).fetchone()
        if row is None:
            return None
        try:
            value = DeliveryReceipt(
                intent.delivery_id,
                row["receipt_id"],
                row["receiver_id"],
                row["recipient_id"],
                row["result_sha256"],
                row["accepted_at_ms"],
            )
            match_receipt(intent, value)
            return value
        except (WorkError, KeyError, TypeError, ValueError):
            raise WorkError("schema_mismatch") from None

    def begin(self, scope: WorkScope, intent: DeliveryIntent) -> DeliveryStart:
        def begin(connection: Connection, now: int) -> DeliveryStart:
            actual = self._exact(connection, scope, intent)
            if self._possible(connection, actual.delivery_id):
                return DeliveryStart(actual, False)
            self._eligible(
                connection, scope, actual.work_id, actual.attempt_id, actual.result_sha256, now
            )
            connection.execute(
                sql.SQL("INSERT INTO {} VALUES(%s::uuid,%s)").format(
                    self._table("result_delivery_possible")
                ),
                [actual.delivery_id, now],
            )
            return DeliveryStart(actual, True)

        return self._write("delivery_begin", begin)

    def record_receipt(
        self, scope: WorkScope, intent: DeliveryIntent, receipt: DeliveryReceipt
    ) -> DeliveryReceipt:
        match_receipt(intent, receipt)

        def record(connection: Connection, now: int) -> DeliveryReceipt:
            actual = self._exact(connection, scope, intent)
            if not self._possible(connection, actual.delivery_id):
                raise WorkError("identity_conflict")
            previous = self._receipt(connection, actual)
            if previous is not None:
                if previous != receipt:
                    raise WorkError("identity_conflict")
                return previous
            duplicate = connection.execute(
                sql.SQL(
                    "SELECT delivery_id FROM {} WHERE receiver_id=%s::uuid AND receipt_id=%s::uuid"
                ).format(self._table("result_delivery_receipts")),
                [receipt.receiver_id, receipt.receipt_id],
            ).fetchone()
            if duplicate is not None:
                raise WorkError("identity_conflict")
            connection.execute(
                sql.SQL("INSERT INTO {} VALUES(%s::uuid,%s::uuid,%s::uuid,%s,%s,%s,%s)").format(
                    self._table("result_delivery_receipts")
                ),
                [
                    receipt.delivery_id,
                    receipt.receipt_id,
                    receipt.receiver_id,
                    receipt.recipient_id,
                    receipt.result_sha256,
                    receipt.accepted_at_ms,
                    now,
                ],
            )
            return receipt

        return self._write("delivery_receipt", record)

    def inspect(self, scope: WorkScope, work_id: str) -> DeliverySnapshot:
        work_uuid(work_id)

        def inspect(connection: Connection, _: int) -> DeliverySnapshot:
            self.work._get(connection, scope, work_id)
            intent = self._intent(connection, scope, work_id)
            if intent is None:
                return DeliverySnapshot(None, False, None)
            return DeliverySnapshot(
                intent,
                self._possible(connection, intent.delivery_id),
                self._receipt(connection, intent),
            )

        return self._read("delivery_inspect", inspect)
