"""Reconcile the fresh walkthrough with its three durable stores and two ledgers."""

import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from psycopg import sql

from delegation_reliability.channel_policy_contracts import channel_policy_key
from services.channel_policy_demo.owner_config import read_owner_profile

DATA = Path("/app/.local")


def verify() -> dict[str, object]:
    profile = read_owner_profile(DATA / "showcase/owner-profile.json")
    channel = sql.Identifier(profile.database.channel_schema)
    work = sql.Identifier(profile.database.work_schema)
    route = profile.route
    scope = (route.scope.tenant_id, route.scope.account_id)

    with profile.work_settings().connect() as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        rows = connection.execute(
            sql.SQL("""
                SELECT inbox.provider, inbox.receipt_id, processing.operation_key,
                       accepted.idempotency_key, accepted.work_id, result.attempt_id,
                       receipt.delivery_id, receiver.case_id, receiver.conversation_id
                  FROM {channel}.inbox AS inbox
                  JOIN {channel}.processing_intents AS processing USING (receipt_id)
                  JOIN {work}.accepted_work AS accepted
                    ON accepted.work_id = processing.external_receipt_id
                   AND accepted.tenant_id = inbox.tenant_id
                   AND accepted.account_id = inbox.account_id
                  JOIN {work}.attempt_results AS result USING (work_id)
                  JOIN {work}.result_delivery_intents AS intent
                    ON intent.attempt_id = result.attempt_id
                   AND intent.result_sha256 = result.sha256
                  JOIN {work}.result_delivery_receipts AS receipt USING (delivery_id)
                  JOIN {channel}.result_receipts AS receiver
                    ON receiver.delivery_id = receipt.delivery_id
                   AND receiver.attempt_id = result.attempt_id
                   AND receiver.work_id = accepted.work_id
                   AND receiver.result_sha256 = result.sha256
                 WHERE inbox.tenant_id = %s AND inbox.account_id = %s
                   AND processing.state = 'dispatched'
                   AND result.disposition = 'eligible_at_commit'
                 ORDER BY inbox.receipt_id
            """).format(channel=channel, work=work),
            scope,
        ).fetchall()
        inbox_count = connection.execute(
            sql.SQL("SELECT count(*) AS count FROM {}.inbox").format(channel)
        ).fetchone()
        rooms = connection.execute(
            sql.SQL("""
                SELECT room_id, case_id, revoked_at IS NOT NULL AS revoked
                  FROM {}.native_bindings
                 WHERE tenant_id = %s AND account_id = %s ORDER BY room_id
            """).format(channel),
            scope,
        ).fetchall()

    if (
        inbox_count != {"count": 3}
        or Counter(row["provider"] for row in rows) != {"fake_sms": 1, "livekit": 2}
        or any(
            row["idempotency_key"] != channel_policy_key(str(row["operation_key"]))
            or row["case_id"] != route.case_id
            or row["conversation_id"] != route.conversation_id
            for row in rows
        )
        or any(len({row[field] for row in rows}) != 3 for field in ("work_id", "delivery_id"))
        or len({row["room_id"] for row in rooms}) != 2
        or any(not row["revoked"] or row["case_id"] != route.case_id for row in rooms)
    ):
        raise ValueError("expected three delivered inputs and two closed rooms for one case")

    supplier = DATA / "booking/supplier.sqlite3"
    receiver = DATA / "booking/completion.sqlite3"
    with closing(sqlite3.connect(supplier.as_uri() + "?mode=ro", uri=True)) as ledger:
        effects = ledger.execute(
            "SELECT effect_id FROM mutation_receipts WHERE scope_id = ?",
            ("demo-traveller",),
        ).fetchall()
    with closing(sqlite3.connect(receiver.as_uri() + "?mode=ro", uri=True)) as ledger:
        receipts = ledger.execute("SELECT event_id FROM completion_receipts").fetchall()
    if len(effects) != 1 or len(receipts) != 1:
        raise ValueError("expected one independent supplier effect and completion receipt")

    identities = json.dumps([rows, rooms, effects, receipts], default=str, sort_keys=True)
    return {
        "case_preserved": True,
        "closed_rooms": 2,
        "distinct_inputs": 3,
        "delegated_results_delivered": 3,
        "supplier_effects": 1,
        "completion_receipts": 1,
        "identity_digest": hashlib.sha256(identities.encode()).hexdigest(),
    }


if __name__ == "__main__":
    try:
        print(json.dumps(verify(), sort_keys=True))
    except Exception:  # noqa: BLE001 - the verifier opens private profile settings
        raise SystemExit(
            "Demo state verification failed. Complete both fresh walkthroughs."
        ) from None
