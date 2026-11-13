"""Core delegation boundaries; real SDK baseline/native exports resolve on demand."""

from importlib import import_module as _import_module
from typing import TYPE_CHECKING

from .action_adapter import (
    ActionBinding,
    DelegationAuthorization,
    DelegationAuthorizer,
    ExactManagedCaseAuthority,
)
from .applicability_api import ApplicabilityClient, open_applicability_client
from .applicability_models import (
    ApplicabilityRefresh,
    ApplicabilityView,
    DisplayTombstone,
    InvalidationEvidence,
    RefreshPolicy,
)
from .applicability_refresher import ApplicabilityRefresher
from .case_adapter import CaseBinding, ManagedCaseAuthority
from .completion import (
    ChannelPolicyDeliveryClient,
    ChannelPolicyResultReadPort,
    CompletionError,
    DelegationDeliveryClient,
    DelegationResultReadPort,
    FixedPolicyDeliveryClient,
    FixedPolicyResultReadPort,
)
from .completion_processor import CompletionProcessor, ProcessingDeliveryPort
from .coordinator import (
    CaseAuthorityPort,
    CaseSnapshot,
    CoordinatorError,
    DelegationCoordinator,
    DelegationSubmission,
    DelegationView,
    DeliveryObservation,
    ResultDeliveryPort,
)
from .delivery_contract import DelegationDelivery, DeliveryBinding, ResultReceiverPort
from .document import DocumentSpecialistClient, DocumentSpecialistHttpClient
from .document_contracts import (
    DOCUMENT_CAPABILITY,
    DOCUMENT_FIELDS,
    DocumentContext,
    DocumentEvidence,
    DocumentField,
    DocumentFields,
    DocumentRegion,
    DocumentRequest,
    DocumentResult,
    encode_document_request,
    encode_document_result,
    match_document_result,
    parse_document_request,
    parse_document_result,
    produce_document_request,
)
from .http_client import (
    AttemptObservation,
    SpecialistClient,
    SpecialistEndpoint,
    SpecialistHttpError,
    SpecialistResultObservation,
    parse_observation,
)
from .models import (
    BaselineCleanupError,
    BaselineError,
    BaselineInputError,
    BaselineInvariantError,
    BaselineMode,
    BaselineObservation,
    BaselineTimeout,
    PolicyInput,
    PolicyResult,
    evaluate_policy,
)
from .processing_api import ProcessingClient, open_processing_client
from .processing_models import (
    CompletionPolicy,
    ProcessingAcknowledgement,
    ProcessingCheckpoint,
    ProcessingOutcome,
    ProcessingStep,
)
from .projection_api import (
    ProjectedResult,
    ProjectionBatch,
    ProjectionBinding,
    ProjectionCheckpoint,
    ProjectionClient,
    ProjectionError,
    ProjectionLimits,
    open_projection_client,
)
from .projection_models import ApplicabilityObservation
from .projector import ProjectionProjector
from .runner import (
    DelegationExecutionView,
    DelegationRun,
    DelegationRunError,
    DelegationRunner,
    SpecialistInvocationPort,
)

__all__ = [
    "DOCUMENT_CAPABILITY",
    "DOCUMENT_FIELDS",
    "ActionBinding",
    "ApplicabilityClient",
    "ApplicabilityObservation",
    "ApplicabilityRefresh",
    "ApplicabilityRefresher",
    "ApplicabilityView",
    "AttemptObservation",
    "BaselineCleanupError",
    "BaselineError",
    "BaselineInputError",
    "BaselineInvariantError",
    "BaselineMode",
    "BaselineObservation",
    "BaselineTimeout",
    "CaseAuthorityPort",
    "CaseBinding",
    "CaseSnapshot",
    "CompletionError",
    "CompletionPolicy",
    "CompletionProcessor",
    "CoordinatorError",
    "DelegationAuthorization",
    "DelegationAuthorizer",
    "DelegationCoordinator",
    "DelegationDelivery",
    "DelegationDeliveryClient",
    "DelegationExecutionView",
    "DelegationResultReadPort",
    "DelegationRun",
    "DelegationRunError",
    "DelegationRunner",
    "DelegationSubmission",
    "DelegationView",
    "DeliveryBinding",
    "DeliveryObservation",
    "DisplayTombstone",
    "DocumentContext",
    "DocumentEvidence",
    "DocumentField",
    "DocumentFields",
    "DocumentRegion",
    "DocumentRequest",
    "DocumentResult",
    "DocumentSpecialistClient",
    "DocumentSpecialistHttpClient",
    "ExactManagedCaseAuthority",
    "FixedPolicyDeliveryClient",
    "FixedPolicyResultReadPort",
    "InvalidationEvidence",
    "ManagedCaseAuthority",
    "PolicyInput",
    "PolicyResult",
    "ProcessingAcknowledgement",
    "ProcessingCheckpoint",
    "ProcessingClient",
    "ProcessingDeliveryPort",
    "ProcessingOutcome",
    "ProcessingStep",
    "ProjectedResult",
    "ProjectionBatch",
    "ProjectionBinding",
    "ProjectionCheckpoint",
    "ProjectionClient",
    "ProjectionError",
    "ProjectionLimits",
    "ProjectionProjector",
    "RefreshPolicy",
    "ResultDeliveryPort",
    "ResultReceiverPort",
    "SpecialistClient",
    "SpecialistEndpoint",
    "SpecialistHttpError",
    "SpecialistInvocationPort",
    "SpecialistResultObservation",
    "encode_document_request",
    "encode_document_result",
    "evaluate_policy",
    "match_document_result",
    "open_applicability_client",
    "open_processing_client",
    "open_projection_client",
    "parse_document_request",
    "parse_document_result",
    "parse_observation",
    "produce_document_request",
    "run_baseline",
]

# Explicit v2 durable consumption; legacy facade defaults remain version 1.
from .fixed_policy_execution import (
    FixedPolicyCoordinator,
    FixedPolicyExecutionView,
    FixedPolicyInvocationPort,
    FixedPolicyResultObservation,
    FixedPolicyRun,
    FixedPolicyRunner,
    FixedPolicySubmission,
    FixedPolicyView,
)

__all__ += [
    "FixedPolicyCoordinator",
    "FixedPolicyExecutionView",
    "FixedPolicyInvocationPort",
    "FixedPolicyResultObservation",
    "FixedPolicyRun",
    "FixedPolicyRunner",
    "FixedPolicySubmission",
    "FixedPolicyView",
]

# Origin-bound v3 is explicit; the original specialist transport remains v2.
from .channel_policy_contracts import (
    ChannelPolicyOrigin,
    ChannelPolicyRequest,
    ChannelPolicyResult,
    channel_policy_key,
    encode_channel_policy_request,
    encode_channel_policy_result,
    match_channel_policy_result,
    parse_channel_policy_request,
    parse_channel_policy_result,
    produce_channel_policy_request,
    produce_channel_policy_result,
)
from .channel_policy_execution import (
    ChannelPolicyCoordinator,
    ChannelPolicyExecutionView,
    ChannelPolicyRun,
    ChannelPolicyRunner,
    ChannelPolicySubmission,
    ChannelPolicyView,
)

__all__ += [
    "ChannelPolicyCoordinator",
    "ChannelPolicyDeliveryClient",
    "ChannelPolicyExecutionView",
    "ChannelPolicyOrigin",
    "ChannelPolicyRequest",
    "ChannelPolicyResult",
    "ChannelPolicyResultReadPort",
    "ChannelPolicyRun",
    "ChannelPolicyRunner",
    "ChannelPolicySubmission",
    "ChannelPolicyView",
    "channel_policy_key",
    "encode_channel_policy_request",
    "encode_channel_policy_result",
    "match_channel_policy_result",
    "parse_channel_policy_request",
    "parse_channel_policy_result",
    "produce_channel_policy_request",
    "produce_channel_policy_result",
]

# Keep exact public types without importing the optional SDK on the core path.
if TYPE_CHECKING:
    from . import baseline as baseline
    from . import native_policy as native_policy
    from . import scripted as scripted
    from .baseline import run_baseline
    from .native_policy import (
        NativePolicyAgent,
        NativePolicyApplication,
        NativePolicyError,
        NativePolicyObservation,
        encode_native_policy_observation,
        parse_native_policy_observation,
    )

__all__ += [
    "NativePolicyAgent",
    "NativePolicyApplication",
    "NativePolicyError",
    "NativePolicyObservation",
    "encode_native_policy_observation",
    "parse_native_policy_observation",
]


# Preserve genuine objects and historical module attributes, not proxy callables.
_LAZY_EXPORTS: dict[str, tuple[str, str | None]] = {
    "run_baseline": (".baseline", "run_baseline"),
    "NativePolicyAgent": (".native_policy", "NativePolicyAgent"),
    "NativePolicyApplication": (".native_policy", "NativePolicyApplication"),
    "NativePolicyError": (".native_policy", "NativePolicyError"),
    "NativePolicyObservation": (".native_policy", "NativePolicyObservation"),
    "encode_native_policy_observation": (".native_policy", "encode_native_policy_observation"),
    "parse_native_policy_observation": (".native_policy", "parse_native_policy_observation"),
    "baseline": (".baseline", None),
    "native_policy": (".native_policy", None),
    "scripted": (".scripted", None),
}


def __getattr__(name: str) -> object:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    module = _import_module(module_name, __name__)
    value: object = module if attribute is None else getattr(module, attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | set(_LAZY_EXPORTS))
