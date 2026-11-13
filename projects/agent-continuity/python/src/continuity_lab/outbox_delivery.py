"""One bounded completion delivery under the shared cooperative worker slot."""

import logging
from collections.abc import Callable

from .case_models import utc_instant, uuid_identity
from .completion_sink import CompletionSinkPort, CompletionSinkUnavailable, SinkReceipt
from .effect_models import DeliverySnapshot
from .execution_models import ExecutionCapacityExceeded, InvalidStoredState
from .postgres_effects import PostgresEffects

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


def _event(event: str, code: str = "ok") -> None:
    try:
        LOGGER.info(event, extra={"event": event, "code": code})
    except Exception:  # noqa: BLE001 - observation failure cannot alter accepted delivery
        return


class CompletionDeliveryWorker:
    """Retry one stable event at a fixed receiver; never modify business truth.

    Sink acceptance is outside the PostgreSQL transaction. A stopped delivery
    can be retried under the same event/receiver, including after sink success.
    The receiver's retained deduplication receipt establishes logical uniqueness.
    """

    def __init__(
        self,
        effects: PostgresEffects,
        sink: CompletionSinkPort,
        *,
        failpoint: Callable[[str], None] | None = None,
    ) -> None:
        self.effects, self.sink, self.failpoint = effects, sink, failpoint

    def run_one(self, *, scope_id: str, task_id: str) -> DeliverySnapshot | None:
        with self.effects.worker_slot():
            target_id = uuid_identity(self.sink.receiver_id)
            claim = self.effects.claim_delivery(
                scope_id=scope_id, task_id=task_id, target_id=target_id
            )
            if claim is None:
                return self.effects.delivery_for_scope(scope_id=scope_id, task_id=task_id)
            try:
                receipt = self.sink.accept(claim.event)
            except (CompletionSinkUnavailable, ExecutionCapacityExceeded):
                _event("completion_sink_unavailable", "dependency_unavailable")
                return self.effects.finish_delivery(claim, delivered=False)
            if (
                type(receipt) is not SinkReceipt
                or receipt.event_id != claim.event.event_id
                or type(receipt.created) is not bool
            ):
                raise InvalidStoredState("Completion receiver returned invalid acknowledgement")
            utc_instant(receipt.received_at)
            if self.failpoint is not None:
                self.failpoint("outbox.after_sink_success")
            value = self.effects.finish_delivery(claim, delivered=True)
            _event("completion_delivery_observed")
            return value
