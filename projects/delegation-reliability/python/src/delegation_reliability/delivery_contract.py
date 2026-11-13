"""First implemented result-delivery façade contract, without I/O or orchestration."""

from dataclasses import dataclass
from typing import Literal, Protocol

from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt, DeliverySnapshot

from .contracts import identifier


@dataclass(frozen=True, slots=True)
class DeliveryBinding:
    """Trusted immutable logical route; request JSON cannot choose a recipient."""

    case_id: str
    conversation_id: str
    recipient_id: str

    def __post_init__(self) -> None:
        identifier(self.case_id)
        identifier(self.conversation_id)
        identifier(self.recipient_id)


@dataclass(frozen=True, slots=True)
class DelegationDelivery:
    """Current sender/receiver observation, separate from result and human state."""

    snapshot: DeliverySnapshot
    state: Literal["missing", "prepared", "unknown", "accepted"]
    receiver_invoked: bool = False


class ResultReceiverPort(Protocol):
    """Configured receiver owns actual I/O and immutable receipt identity.

    A receipt accepts these exact result bytes; it never proves playback, human
    acknowledgement or authorization. ``find`` cannot initiate another send.
    Waiter timeout never releases actual operations; ``close`` retains them and
    reports incomplete cleanup until they have settled.
    """

    @property
    def receiver_id(self) -> str: ...

    async def accept(self, intent: DeliveryIntent) -> DeliveryReceipt: ...
    async def find(self, intent: DeliveryIntent) -> DeliveryReceipt | None: ...
    async def close(self) -> None: ...


class ResultDeliveryPort(Protocol):
    """Explicit bounded delivery/inspection keyed by accepted P1 work UUID."""

    async def deliver_once(self, work_id: str) -> DelegationDelivery: ...
    async def inspect(self, work_id: str) -> DelegationDelivery: ...
    async def close(self) -> None: ...
