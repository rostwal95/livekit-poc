"""Actual public P1/P3 recovery composition; no second execution owner.

Only the separately loaded explicit case fixture bootstraps/leases P1 workers.
Early execution preflights are synthetic and never cross into the real completion
account. All persisted source/result/delivery/action decisions use public clients.
"""

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
import stat
import time
from collections.abc import Mapping
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast
from unittest.mock import patch
from uuid import UUID, uuid4

from psycopg import Connection, sql

from continuity_lab.action_api import ActionReceipt, Confirmation, open_action_client
from continuity_lab.case_control_api import open_case_control_client
from continuity_lab.delivery_api import DeliveryIntent, DeliveryReceipt, open_delivery_client
from continuity_lab.execution_api import (
    AttemptResult,
    ExecutionClient,
    ExecutionLimits,
    ExecutionObservation,
    Issuance,
    IssuedAttempt,
    open_execution_client,
)
from continuity_lab.postgres_api import open_postgres_client, parse_confirmation_payload
from continuity_lab.receiver_api import (
    ReceiverBinding,
    ResultReceiver,
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
    WorkLimits,
    WorkPrincipal,
    WorkScope,
    open_work_client,
)
from delegation_reliability import (
    ActionBinding,
    CaseSnapshot,
    CompletionError,
    CompletionPolicy,
    CompletionProcessor,
    DelegationAuthorizer,
    DelegationCoordinator,
    DelegationDeliveryClient,
    DelegationRunError,
    DelegationRunner,
    DeliveryBinding,
    ExactManagedCaseAuthority,
    ProjectionProjector,
    RefreshPolicy,
    SpecialistClient,
    SpecialistEndpoint,
)
from delegation_reliability.contracts import (
    CAPABILITY,
    DelegationRequest,
    Scope,
    canonical,
    encode_request,
    parse_request,
    parse_result,
    produce_request,
)
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

# FROZEN_PROTOCOL is generated verbatim from the reviewed protocol02, not loaded from private evidence at runtime.
CASE_NAMES = (
    "specialist_process_kill_retains_accepted_input",
    "original_issue_replay_never_reinvokes",
    "premature_new_command_waits_for_authority_lease",
    "explicit_new_command_recovers_useful_result",
    "coordinator_http_loss_remote_cleanup_observed",
    "fresh_coordinator_preserves_input_attempt_history",
    "concurrent_recovery_one_created_issue",
    "result_precommit_kill_rolls_back_result_and_event",
    "result_postcommit_kill_original_bytes_replayed",
    "possible_delivery_restart_remains_lookup_only_unknown",
    "later_current_work_progresses_around_unknown_gap",
    "receiver_commit_kill_original_receipt_reconciled",
    "fresh_processing_replay_preserves_original_ack",
    "action_commit_kill_exact_confirmation_original_receipt",
    "changed_completion_command_scope_rejected_without_effect",
    "independent_history_receiver_supplier_joins_and_cleanup",
    "coordinator_post_issue_crash_before_first_http",
)
MODE_ORDER = (
    "install",
    "issued-crash",
    "issued-replay",
    "race-a",
    "race-b",
    "race-locker",
    "race-verify",
    "specialist-loss",
    "specialist-resume",
    "coordinator-crash",
    "coordinator-resume",
    "result-before-crash",
    "result-before-resume",
    "result-after-crash",
    "result-after-resume",
    "delivery-begin-crash",
    "unknown-resume",
    "receiver-crash",
    "receiver-resume",
    "processing-replay",
    "action-crash",
    "action-resume",
    "conflicts",
    "owner-check",
    "cleanup",
)
OWNER_MODES = frozenset({"cleanup", "install", "owner-check", "race-locker"})
BASE_KEYS = (
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
)
MODE_KEYS = {
    "action-crash": frozenset(
        {
            "P3_RECOVERY_BARRIER",
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "action-resume": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "cleanup": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_OWNER_PASSWORD",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "conflicts": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "coordinator-crash": frozenset(
        {
            "P3_RECOVERY_BARRIER",
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "coordinator-resume": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "delivery-begin-crash": frozenset(
        {
            "P3_RECOVERY_BARRIER",
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "install": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_OWNER_PASSWORD",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "issued-crash": frozenset(
        {
            "P3_RECOVERY_BARRIER",
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "issued-replay": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "owner-check": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_OWNER_PASSWORD",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "processing-replay": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "race-a": frozenset(
        {
            "P3_RECOVERY_BARRIER",
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "race-b": frozenset(
        {
            "P3_RECOVERY_BARRIER",
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "race-locker": frozenset(
        {
            "P3_RECOVERY_BARRIER",
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_OWNER_PASSWORD",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "race-verify": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "receiver-crash": frozenset(
        {
            "P3_RECOVERY_BARRIER",
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "receiver-resume": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "result-after-crash": frozenset(
        {
            "P3_RECOVERY_BARRIER",
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "result-after-resume": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "result-before-crash": frozenset(
        {
            "P3_RECOVERY_BARRIER",
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "result-before-resume": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "specialist-loss": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "specialist-resume": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
    "unknown-resume": frozenset(
        {
            "P3_RECOVERY_CASE_SCHEMA",
            "P3_RECOVERY_COMPLETION_TOKEN",
            "P3_RECOVERY_DIRECTORY",
            "P3_RECOVERY_ENDPOINT_FILE",
            "P3_RECOVERY_EXECUTION_TOKEN",
            "P3_RECOVERY_NODE_TOKEN",
            "P3_RECOVERY_PG_PORT",
            "P3_RECOVERY_PROJECTION_SCHEMA",
            "P3_RECOVERY_RUNTIME_PASSWORD",
            "P3_RECOVERY_WORK_SCHEMA",
        }
    ),
}
RESPONSES = {
    "action-crash": None,
    "action-resume": {
        "cases": ["action_commit_kill_exact_confirmation_original_receipt"],
        "mode": "action-resume",
        "original_action_equal": True,
        "schema_version": 1,
        "status": "passed",
        "supplier_apply_calls": 1,
        "supplier_receipts": 1,
    },
    "cleanup": {
        "cases": [],
        "mode": "cleanup",
        "schema_version": 1,
        "schemas_removed": True,
        "status": "passed",
    },
    "conflicts": {
        "cases": ["changed_completion_command_scope_rejected_without_effect"],
        "completion_conflict": "identity_conflict",
        "confirmation_conflict": "identity_conflict",
        "extra_effects": 0,
        "foreign_result": "not_found",
        "known_after_later_cancel": True,
        "mode": "conflicts",
        "new_issue_after_result": "identity_conflict",
        "original_action_after_cancel_equal": True,
        "original_delivery_after_cancel_equal": True,
        "schema_version": 1,
        "status": "passed",
    },
    "coordinator-crash": None,
    "coordinator-resume": {
        "cases": [
            "coordinator_http_loss_remote_cleanup_observed",
            "fresh_coordinator_preserves_input_attempt_history",
        ],
        "mode": "coordinator-resume",
        "new_command_invoked": True,
        "old_command_invoked": False,
        "prior_remote_active": 0,
        "schema_version": 1,
        "status": "passed",
    },
    "delivery-begin-crash": None,
    "install": {
        "case_version": 4,
        "cases": [],
        "mode": "install",
        "projection_version": 3,
        "schema_version": 1,
        "scopes": 2,
        "status": "passed",
        "work_version": 4,
    },
    "issued-crash": None,
    "issued-replay": {
        "cases": [
            "coordinator_post_issue_crash_before_first_http",
            "premature_new_command_waits_for_authority_lease",
        ],
        "changed_owner_code": "identity_conflict",
        "mode": "issued-replay",
        "new_invocations": 0,
        "original_owner_replayed": True,
        "premature_code": "capacity",
        "schema_version": 1,
        "status": "passed",
    },
    "owner-check": {
        "accepted": 7,
        "acks": 1,
        "action_receipts": 1,
        "attempts": 11,
        "business_completions": 1,
        "cases": ["independent_history_receiver_supplier_joins_and_cleanup"],
        "delivery_intents": 2,
        "delivery_receipts": 1,
        "events": 7,
        "exact_reconciliation": True,
        "intents": 1,
        "mode": "owner-check",
        "projected": 2,
        "receiver_accept_calls": 1,
        "receiver_receipts": 1,
        "results": 7,
        "schema_version": 1,
        "status": "passed",
        "supplier_apply_calls": 1,
        "supplier_receipts": 1,
    },
    "processing-replay": {
        "cases": ["fresh_processing_replay_preserves_original_ack"],
        "fresh_direct_delivery_accept_calls": 0,
        "fresh_direct_delivery_receipt_equal": True,
        "mode": "processing-replay",
        "new_receiver_accept_calls": 0,
        "original_ack_equal": True,
        "schema_version": 1,
        "status": "passed",
        "unknown_gap_unacked": True,
    },
    "race-a": {"cases": [], "mode": "race-a", "schema_version": 1, "side": "a", "status": "passed"},
    "race-b": {"cases": [], "mode": "race-b", "schema_version": 1, "side": "b", "status": "passed"},
    "race-locker": {
        "authority_lease_expired": True,
        "blocked": True,
        "cases": [],
        "graphs": 1,
        "mode": "race-locker",
        "schema_version": 1,
        "status": "passed",
        "waiters": 2,
    },
    "race-verify": {
        "cases": [
            "explicit_new_command_recovers_useful_result",
            "concurrent_recovery_one_created_issue",
        ],
        "created_issues": 1,
        "mode": "race-verify",
        "new_invocations": 1,
        "schema_version": 1,
        "status": "passed",
    },
    "receiver-crash": None,
    "receiver-resume": {
        "cases": [
            "later_current_work_progresses_around_unknown_gap",
            "receiver_commit_kill_original_receipt_reconciled",
        ],
        "delivery_state": "accepted",
        "mode": "receiver-resume",
        "receiver_accept_calls": 1,
        "schema_version": 1,
        "status": "passed",
        "terminal_acks": 1,
        "unknown_gap_unacked": True,
    },
    "result-after-crash": None,
    "result-after-resume": {
        "cases": ["result_postcommit_kill_original_bytes_replayed"],
        "mode": "result-after-resume",
        "new_invocations": 0,
        "original_bytes_equal": True,
        "original_events": 1,
        "schema_version": 1,
        "status": "passed",
    },
    "result-before-crash": None,
    "result-before-resume": {
        "cases": ["result_precommit_kill_rolls_back_result_and_event"],
        "mode": "result-before-resume",
        "new_command_invoked": True,
        "rolled_back_events": 0,
        "rolled_back_results": 0,
        "schema_version": 1,
        "status": "passed",
    },
    "specialist-loss": {
        "accepted_preserved": True,
        "cases": ["specialist_process_kill_retains_accepted_input"],
        "mode": "specialist-loss",
        "observed_code": "transport_unknown",
        "schema_version": 1,
        "status": "passed",
    },
    "specialist-resume": {
        "cases": ["original_issue_replay_never_reinvokes"],
        "mode": "specialist-resume",
        "new_command_invoked": True,
        "old_command_invoked": False,
        "schema_version": 1,
        "status": "passed",
    },
    "unknown-resume": {
        "cases": ["possible_delivery_restart_remains_lookup_only_unknown"],
        "delivery_state": "unknown",
        "mode": "unknown-resume",
        "receiver_accept_calls": 0,
        "schema_version": 1,
        "status": "passed",
        "terminal_acks": 0,
    },
}
ROOT = Path(__file__).resolve().parents[3]
MODE = ""
DIAGNOSTIC_CODES = frozenset(
    [
        "acknowledgement_unknown",
        "capacity",
        "case_cancelled",
        "case_changed",
        "checkpoint_conflict",
        "cleanup_incomplete",
        "closed",
        "deadline_exceeded",
        "deadline_expired",
        "expired",
        "fixture_failed",
        "identity_conflict",
        "intent_committed",
        "internal_error",
        "invalid_confirmation",
        "invalid_input",
        "invalid_result",
        "invalid_source_state",
        "invalid_stored_state",
        "not_eligible",
        "not_found",
        "quote_expired",
        "request_aborted",
        "schema_mismatch",
        "source_mismatch",
        "stale_revision",
        "storage_unavailable",
        "transport_unknown",
        "unauthorized",
    ]
)
STAGE = "configuration"
DIAGNOSTICS: dict[str, Any] = {
    "queryVisibility": "unobserved",
    "cleanup_failure": False,
    "owned_backend_ids": [],
    "waiters": [],
}
RECOVERY = Scope("tenant_recovery", "execution")
COMPLETION = Scope("tenant_recovery", "completion")
POLICY = canonical({"minimum_notice_days": 7, "policy_version": "policy_v1"})
RECIPIENT = "recipient_recovery"
LABELS = ("i", "s", "c", "u", "v", "g", "m")
COMP = {"g", "m"}
BASE = set(BASE_KEYS)


def module(path: Path, name: str) -> ModuleType:
    import sys

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


HELPER = module(ROOT / "local-setup/scripts/p3_case_fixture.py", "p3_recovery_case_fixture")
EXAMPLE = module(
    ROOT / "projects/delegation-reliability/examples/policy_completion.py",
    "p3_recovery_public_example",
)


SUBSTAGES = frozenset(
    [
        "action_apply_supplier",
        "action_authorize",
        "action_construct",
        "action_inspect_example",
        "action_recover",
        "action_verify_supplier",
        "case_inquire",
        "case_revise_first",
        "case_revise_second",
        "case_submit",
        "conflict_action_replay",
        "conflict_cancel",
        "conflict_confirmation",
        "conflict_construct",
        "conflict_delivery_replay",
        "conflict_foreign_read",
        "conflict_issue",
        "conflict_result",
        "delivery_accept_input",
        "delivery_construct",
        "delivery_invoke",
        "delivery_process",
        "delivery_project",
        "delivery_seed",
        "owner_ack",
        "owner_action",
        "owner_body_c",
        "owner_body_g",
        "owner_body_i",
        "owner_body_m",
        "owner_body_s",
        "owner_body_u",
        "owner_body_v",
        "owner_business",
        "owner_case_counts",
        "owner_case_effect",
        "owner_control",
        "owner_counts",
        "owner_delivery",
        "owner_grants",
        "owner_identity_c",
        "owner_identity_g",
        "owner_identity_i",
        "owner_identity_m",
        "owner_identity_s",
        "owner_identity_u",
        "owner_identity_v",
        "owner_inventory",
        "owner_peer",
        "owner_projection",
        "owner_receiver",
        "owner_result_c",
        "owner_result_g",
        "owner_result_i",
        "owner_result_m",
        "owner_result_s",
        "owner_result_u",
        "owner_result_v",
        "owner_supplier",
        "processing_construct",
        "processing_direct_delivery",
        "processing_read_ack",
        "processing_step",
        "quote_prepare",
        "receiver_accept_input",
        "receiver_construct",
        "receiver_invoke",
        "receiver_process",
        "receiver_project",
        "receiver_quote",
        "receiver_read_ack",
        "receiver_read_delivery",
        "receiver_reconcile",
        "unknown_construct",
        "unknown_direct_delivery",
        "unknown_processing",
    ]
)


def observe_stage(value: str) -> None:
    global STAGE
    assert value in SUBSTAGES
    STAGE = value


class OwnedCloser(Protocol):
    async def close(self) -> None: ...


async def close_preserving(*owners: OwnedCloser) -> None:
    import sys

    primary = sys.exception()
    first: BaseException | None = None
    for owner in owners:
        try:
            await owner.close()
        except BaseException as error:  # noqa: BLE001 - attempt every owner and preserve active primary failure.
            DIAGNOSTICS["cleanup_failure"] = True
            if first is None:
                first = error
    if first is not None and primary is None:
        raise first


def folder() -> Path:
    p = Path(os.environ["P3_RECOVERY_DIRECTORY"])
    st = p.lstat()
    assert (
        stat.S_ISDIR(st.st_mode)
        and not p.is_symlink()
        and st.st_uid == os.geteuid()
        and stat.S_IMODE(st.st_mode) == 0o700
    )
    return p


def environment() -> None:
    required = set(MODE_KEYS[MODE])
    assert required <= set(os.environ) and not (set(os.environ) - required - BASE), (
        "unsafe_child_environment"
    )
    for key, pattern in [
        ("WORK_SCHEMA", r"p1_work_recovery_[0-9a-f]{32}"),
        ("CASE_SCHEMA", r"p3_completion_[0-9a-f]{32}"),
        ("PROJECTION_SCHEMA", r"p3_projection_recovery_[0-9a-f]{32}"),
    ]:
        assert re.fullmatch(pattern, os.environ["P3_RECOVERY_" + key])
    folder()


def settings(kind: str = "work") -> PostgresSettings:
    assert kind in {"work", "case", "projection"}
    owner = MODE in OWNER_MODES
    return PostgresSettings(
        port=int(os.environ["P3_RECOVERY_PG_PORT"]),
        schema=os.environ["P3_RECOVERY_" + kind.upper() + "_SCHEMA"],
        user="continuity_migrator" if owner else "livekit_lab",
        password=os.environ[
            "P3_RECOVERY_OWNER_PASSWORD" if owner else "P3_RECOVERY_RUNTIME_PASSWORD"
        ],
    )


def encoded(value: object, maximum: int = 32768) -> bytes:
    raw = (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode()
    assert 1 <= len(raw) <= maximum, "fixture_json_bound"
    return raw


def save(name: str, value: object) -> None:
    assert re.fullmatch(r"[a-z][a-z0-9_-]*\.json", name)
    raw = encoded(value)
    p = folder() / name
    if p.exists():
        assert load(name) == value, "changed_immutable_fixture"
        return
    fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(raw)


def load(name: str) -> dict[str, Any]:
    assert re.fullmatch(r"[a-z][a-z0-9_-]*\.json", name)
    p = folder() / name
    st = p.lstat()
    assert (
        stat.S_ISREG(st.st_mode)
        and not p.is_symlink()
        and st.st_nlink == 1
        and st.st_uid == os.geteuid()
        and stat.S_IMODE(st.st_mode) == 0o600
        and st.st_size <= 32768
    )
    with p.open("rb") as inp:
        raw = inp.read(32769)
    assert len(raw) <= 32768
    value = json.loads(raw)
    assert type(value) is dict
    return cast(dict[str, Any], value)


def marker(name: str) -> None:
    assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
    p = folder() / (name + ".reached")
    pending = p.with_name(p.name + "." + str(os.getpid()) + ".pending")
    fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write((str(os.getpid()) + "\n").encode())
            out.flush()
            os.fsync(out.fileno())
        os.link(pending, p, follow_symlinks=False)
    finally:
        pending.unlink(missing_ok=True)


def held(name: str) -> None:
    assert Path(os.environ["P3_RECOVERY_BARRIER"]) == folder() / (name + ".reached")
    marker(name)
    end = time.monotonic() + 15
    while not (folder() / (name + ".released")).exists():
        assert time.monotonic() < end, "parent_did_not_finish_barrier"
        time.sleep(0.002)
    assert (folder() / (name + ".released")).read_text() == str(os.getpid()) + "\n"


def hook(stage: str) -> None:
    wanted = {
        "issued-crash": ("issue.after_commit", "issue_commit"),
        "result-before-crash": ("complete.before_commit", "result_before"),
        "result-after-crash": ("complete.after_commit", "result_after"),
        "delivery-begin-crash": ("delivery_begin.after_commit", "delivery_begin"),
        "action-crash": ("authorize.after_commit", "action_commit"),
    }
    if MODE in wanted and stage == wanted[MODE][0]:
        held(wanted[MODE][1])


def scope(label: str) -> Scope:
    return COMPLETION if label in COMP else RECOVERY


def directory(completion: bool = False) -> tuple[WorkDirectory, BearerToken]:
    key = "P3_RECOVERY_COMPLETION_TOKEN" if completion else "P3_RECOVERY_EXECUTION_TOKEN"
    t = BearerToken(os.environ[key])
    s = COMPLETION if completion else RECOVERY
    return WorkDirectory(
        {t: WorkPrincipal("recovery_" + s.account_id, WorkScope(s.tenant_id, s.account_id))}
    ), t


def source() -> str:
    return str(load("source.json")["source_id"])


def supplier() -> Path:
    return folder() / "supplier.sqlite3"


def work(label: str) -> dict[str, Any]:
    return load("work_" + label + ".json")


def owner(label: str, number: int) -> str:
    return str(load("owners.json")[label + str(number)])


def command(label: str, number: int) -> str:
    return "recovery_" + label + "_" + str(number)


def grant_payload(v: IssuedAttempt) -> dict[str, object]:
    return {
        "work_id": v.record.work_id,
        "attempt_id": v.attempt_id,
        "command_id": v.command_id,
        "number": v.number,
        "owner_id": v.owner_id,
        "epoch": v.epoch,
        "issued_at_ms": v.issued_at_ms,
        "lease_until_ms": v.lease_until_ms,
    }


def make_request(label: str) -> DelegationRequest:
    assert label in LABELS
    s = scope(label)
    return produce_request(
        {
            "schema_version": 1,
            "kind": "delegation.request",
            "capability": CAPABILITY,
            "input_schema_version": 1,
            "scope": {"tenant_id": s.tenant_id, "account_id": s.account_id},
            "delegation_id": "delegation_recovery_" + label,
            "case_id": "case_completion" if label in COMP else "case_execution",
            "request_revision": 2,
            "context_snapshot": {
                "policy_version": "policy_v1",
                "policy_source_id": "policy_demo",
                "days_before_arrival": 14,
                "note": "Bounded explicit recovery fixture.",
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
            "result_route": {"conversation_id": "conversation_recovery"},
            "attempt": {"attempt_id": "attempt_proposed", "number": 1},
        }
    )


def evidence(s: Scope) -> tuple[EvidenceRecord, ...]:
    return (EvidenceRecord(s, make_request("m" if s == COMPLETION else "i").evidence[0], POLICY),)


class SyntheticCases:
    async def snapshot(self, *, case_id: str) -> CaseSnapshot:
        assert case_id == "case_execution"
        return CaseSnapshot(RECOVERY, case_id, 2, False)


def binding() -> ActionBinding:
    v = load("case.json")
    return ActionBinding(
        case_id="case_completion",
        task_id=str(v["task_id"]),
        authority_case_id=str(v["case_id"]),
        authority_actor_id=HELPER.ACTOR.actor_id,
        authority_scope_id=HELPER.ACTOR.scope_id,
        case_schema=settings("case").schema,
    )


def policy() -> CompletionPolicy:
    return CompletionPolicy(
        str(load("receiver.json")["receiver_id"]),
        (DeliveryBinding("case_completion", "conversation_recovery", RECIPIENT),),
    )


def clock() -> int:
    with closing(settings().connect(application_name="continuity-test")) as c:
        row = c.execute(
            "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
        ).fetchone()
        assert row is not None
        return int(row["now"])


async def expired(stamp: int) -> int:
    end = time.monotonic() + 6
    while True:
        observed = await asyncio.to_thread(clock)
        if observed >= stamp:
            return observed
        assert time.monotonic() < end, "lease_not_expired"
        await asyncio.sleep(0.005)


class CapturedExecution:
    def __init__(self, actual: ExecutionClient, label: str) -> None:
        self.actual, self.label = actual, label

    @property
    def scope(self) -> WorkScope:
        return self.actual.scope

    @property
    def pending_count(self) -> int:
        return self.actual.pending_count

    async def observe(self, *, work_id: str) -> ExecutionObservation:
        return await self.actual.observe(work_id=work_id)

    async def result(self, *, work_id: str, attempt_id: str) -> AttemptResult | None:
        return await self.actual.result(work_id=work_id, attempt_id=attempt_id)

    async def find_issue(self, *, command_id: str) -> IssuedAttempt | None:
        return await self.actual.find_issue(command_id=command_id)

    async def issue(self, *, work_id: str, owner_id: str, command_id: str) -> Issuance:
        if MODE in {"race-a", "race-b"}:
            await asyncio.to_thread(held, MODE.replace("-", "_") + "_ready")
            original_connect = PostgresSettings.connect

            def captured_connect(
                value: PostgresSettings, *, application_name: str = "continuity-runtime"
            ) -> Connection[dict[str, Any]]:
                connection = original_connect(value, application_name=application_name)
                try:
                    assert value.schema == settings().schema and value.user == "livekit_lab"
                    save(
                        MODE.replace("-", "_") + "_backend.json",
                        {
                            "role": MODE,
                            "process_pid": os.getpid(),
                            "backend_pid": connection.info.backend_pid,
                        },
                    )
                    return connection
                except BaseException:
                    connection.close()
                    raise

            with patch.object(PostgresSettings, "connect", captured_connect):
                return await self.actual.issue(
                    work_id=work_id, owner_id=owner_id, command_id=command_id
                )
        return await self.actual.issue(work_id=work_id, owner_id=owner_id, command_id=command_id)

    async def complete(self, *, attempt: IssuedAttempt, body: bytes) -> AttemptResult:
        save(
            "observed_" + self.label + "_" + str(attempt.number) + ".json",
            {"grant": grant_payload(attempt), "sha256": hashlib.sha256(body).hexdigest()},
        )
        return await self.actual.complete(attempt=attempt, body=body)

    async def close(self) -> None:
        await self.actual.close()


class InvocationTap:
    def __init__(self, actual: SpecialistClient) -> None:
        self.actual = actual

    async def invoke_observed(self, request: DelegationRequest) -> Any:
        if MODE == "coordinator-crash":
            marker("coordinator_http_started")
        return await self.actual.invoke_observed(request)

    async def close(self) -> None:
        await self.actual.close()


def record_receiver_call(intent: DeliveryIntent) -> None:
    value = {
        "delivery_id": intent.delivery_id,
        "work_id": intent.work_id,
        "attempt_id": intent.attempt_id,
        "result_sha256": intent.result_sha256,
    }
    raw = encoded(value, 1024)
    try:
        descriptor = os.open(
            folder() / "receiver_call.json",
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
        )
    except FileExistsError:
        try:
            duplicate = os.open(
                folder() / "receiver_call_duplicate.json",
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
            )
        except FileExistsError:
            pass
        else:
            with os.fdopen(duplicate, "wb") as output:
                output.write(raw)
        raise AssertionError("duplicate_receiver_entry") from None
    with os.fdopen(descriptor, "wb") as output:
        output.write(raw)


class ReturnedReceiver(ResultReceiver):
    """Test-only public receiver decorator; preserve actual accepted fact before crash."""

    def __init__(self, actual: ResultReceiver) -> None:
        self.actual = actual

    @property
    def receiver_id(self) -> str:
        return self.actual.receiver_id

    @property
    def pending_count(self) -> int:
        return self.actual.pending_count

    def metrics(self) -> Mapping[str, int]:
        return self.actual.metrics()

    async def accept(self, intent: DeliveryIntent) -> DeliveryReceipt:
        record_receiver_call(intent)
        receipt = await self.actual.accept(intent)
        if MODE == "receiver-crash":
            await asyncio.to_thread(held, "receiver_committed")
        return receipt

    async def find(self, intent: DeliveryIntent) -> DeliveryReceipt | None:
        return await self.actual.find(intent)

    async def close(self) -> None:
        await self.actual.close()


class Bundle:
    def __init__(self, label: str, number: int = 1) -> None:
        self.label, self.number = label, number
        self.scope = scope(label)
        reg, token = directory(label in COMP)
        self.control = (
            open_case_control_client(
                actor=HELPER.ACTOR,
                token=token,
                settings=settings("case"),
                quote_database=supplier(),
            )
            if label in COMP
            else None
        )
        self.cases = (
            ExactManagedCaseAuthority(self.control, scope=self.scope, bindings=(binding(),))
            if self.control is not None
            else SyntheticCases()
        )
        self.coordinator = DelegationCoordinator(
            executions=open_work_client(settings=settings(), directory=reg, token=token),
            scope=self.scope,
            case_authority=self.cases,
        )
        self.execution = open_execution_client(
            settings=settings(), directory=reg, token=token, harness_failpoint=hook
        )
        endpoint = load(Path(os.environ["P3_RECOVERY_ENDPOINT_FILE"]).name)
        assert endpoint["host"] == "127.0.0.1" and type(endpoint["port"]) is int
        self.runner = DelegationRunner(
            executions=CapturedExecution(self.execution, label),
            scope=self.scope,
            owner_id=owner(label, number),
            specialist=InvocationTap(
                SpecialistClient(
                    SpecialistEndpoint(endpoint["port"]),
                    "Bearer " + os.environ["P3_RECOVERY_NODE_TOKEN"],
                )
            ),
            case_authority=self.cases,
            evidence=evidence(self.scope),
            timeout_ms=10000,
        )
        self.delivery: DelegationDeliveryClient | None = None
        self.processor: CompletionProcessor | None = None
        self.authorizer: DelegationAuthorizer | None = None

    def delivered(self) -> DelegationDeliveryClient:
        assert self.label in COMP
        if self.delivery is None:
            reg, token = directory(True)
            self.delivery = DelegationDeliveryClient(
                results=self.runner,
                deliveries=open_delivery_client(
                    settings=settings(), directory=reg, token=token, harness_failpoint=hook
                ),
                receiver=ReturnedReceiver(
                    open_result_receiver(
                        folder() / "receiver.sqlite3",
                        receiver_id=policy().receiver_id,
                        bindings=(
                            ReceiverBinding(
                                WorkScope(COMPLETION.tenant_id, COMPLETION.account_id), RECIPIENT
                            ),
                        ),
                    )
                ),
                scope=COMPLETION,
                evidence=evidence(COMPLETION),
                bindings=policy().bindings,
                timeout_ms=10000,
            )
        return self.delivery

    def processed(self) -> CompletionProcessor:
        if self.processor is None:
            reg, token = directory(True)
            self.processor = CompletionProcessor(
                processing=open_processing_client(
                    settings=settings("projection"),
                    directory=reg,
                    token=token,
                    source_id=source(),
                    policy=policy(),
                ),
                source=open_result_feed_client(settings=settings(), directory=reg, token=token),
                delivery=self.delivered(),
                results=self.runner,
                scope=COMPLETION,
                evidence=evidence(COMPLETION),
                timeout_ms=10000,
            )
        return self.processor

    def authorized(self) -> DelegationAuthorizer:
        if self.authorizer is None:
            reg, token = directory(True)
            self.authorizer = DelegationAuthorizer(
                results=self.runner,
                actions=open_action_client(
                    settings=settings(),
                    directory=reg,
                    token=token,
                    case_settings=settings("case"),
                    case_actor=HELPER.ACTOR,
                    case_token=token,
                    harness_failpoint=hook,
                ),
                scope=COMPLETION,
                evidence=evidence(COMPLETION),
                bindings=(binding(),),
                timeout_ms=10000,
            )
        return self.authorizer

    async def close(self) -> None:
        first: BaseException | None = None
        owners = (
            self.processor if self.processor is not None else self.delivery,
            self.authorizer,
            self.runner,
            self.coordinator,
            self.control,
        )
        for value in owners:
            if value is not None:
                try:
                    await value.close()
                except BaseException as error:  # noqa: BLE001 - attempt all independent owners before rethrowing first failure.
                    if first is None:
                        first = error
        if first is not None:
            raise first


async def accept(b: Bundle, label: str) -> str:
    value = make_request(label)
    accepted = await b.coordinator.submit(value)
    save(
        "work_" + label + ".json",
        {
            "work_id": accepted.view.record.work_id,
            "request": json.loads(encode_request(value)),
            "request_sha256": accepted.view.record.payload.sha256,
        },
    )
    return accepted.view.record.work_id


async def grant(b: Bundle, label: str, number: int) -> IssuedAttempt:
    value = await b.execution.find_issue(command_id=command(label, number))
    assert value is not None and value.owner_id == owner(label, number)
    save("grant_" + label + "_" + str(number) + ".json", grant_payload(value))
    return value


async def result(b: Bundle, label: str, number: int) -> AttemptResult:
    g = await grant(b, label, number)
    v = await b.execution.result(work_id=g.record.work_id, attempt_id=g.attempt_id)
    assert v is not None and v.disposition == "eligible_at_commit"
    save(
        "result_" + label + ".json",
        {
            "work_id": v.work_id,
            "attempt_id": v.attempt_id,
            "sha256": v.sha256,
            "recorded_at_ms": v.recorded_at_ms,
            "disposition": v.disposition,
        },
    )
    return v


async def assert_accepted(b: Bundle, label: str) -> None:
    w = work(label)
    found = await b.coordinator.find(str(w["request"]["delegation_id"]))
    assert (
        found is not None
        and found.record.work_id == w["work_id"]
        and found.record.payload.sha256 == w["request_sha256"]
        and encode_request(found.request) == canonical(w["request"])
    )


def reply() -> dict[str, Any]:
    value = RESPONSES[MODE]
    assert value is not None
    return cast(dict[str, Any], value)


def install() -> dict[str, Any]:
    save(
        "owned.json",
        {
            "work": settings().schema,
            "case": settings("case").schema,
            "projection": settings("projection").schema,
            "fixture": "p3-recovery-fixture-v1",
        },
    )
    save("owners.json", {label + str(n): str(uuid4()) for label in LABELS for n in (1, 2)})
    install_work_schema(settings(), limits=WorkLimits(16, 16))
    upgrade_work_schema_v2(settings(), limits=ExecutionLimits(4, 3, 5000))
    upgrade_work_schema_v3(settings())
    upgrade_work_schema_v4(settings())
    HELPER.install(settings("case"), supplier())
    rid = initialize_result_receiver(folder() / "receiver.sqlite3")
    save("receiver.json", {"receiver_id": rid})
    with closing(settings().connect(application_name="continuity-test")) as c:
        row = c.execute(
            sql.SQL("SELECT source_id::text FROM {}.result_feed_source WHERE singleton").format(
                sql.Identifier(settings().schema)
            )
        ).fetchone()
        assert row is not None
    save("source.json", row)
    install_projection_schema(
        settings("projection"),
        binding=ProjectionBinding(source(), WorkScope(COMPLETION.tenant_id, COMPLETION.account_id)),
        limits=ProjectionLimits(16),
    )
    upgrade_projection_schema_v2(settings("projection"), policy=policy())
    upgrade_projection_schema_v3(settings("projection"), policy=RefreshPolicy(16, 2))
    return reply()


async def execution_crash(label: str) -> None:
    b = Bundle(label)
    try:
        wid = await accept(b, label)
        await b.runner.run_once(wid, command(label, 1))
        raise AssertionError("expected_owned_kill")
    finally:
        await close_preserving(b)


async def issued_replay() -> dict[str, Any]:
    b = Bundle("i")
    try:
        await assert_accepted(b, "i")
        g = await grant(b, "i", 1)
        assert await b.execution.result(work_id=g.record.work_id, attempt_id=g.attempt_id) is None
        assert (await b.runner.run_once(g.record.work_id, command("i", 1))).invoked is False
        for changed_owner, cmd, expected in [
            (str(uuid4()), command("i", 1), "identity_conflict"),
            (owner("i", 2), command("i", 2), "capacity"),
        ]:
            assert clock() < g.lease_until_ms, "premature_probe_lost_window"
            try:
                await b.execution.issue(
                    work_id=g.record.work_id, owner_id=changed_owner, command_id=cmd
                )
            except WorkError as error:
                assert error.code == expected
            else:
                raise AssertionError("ineligible_issuance_created")
        assert b.runner.metrics()["invoked"] == 0
        return reply()
    finally:
        await close_preserving(b)


async def race_writer(side: str) -> dict[str, Any]:
    b = Bundle("i", 2)
    try:
        run = await b.runner.run_once(str(work("i")["work_id"]), command("i", 2))
        save(
            "race_" + side + ".json",
            {
                "invoked": run.invoked,
                "attempt_id": run.view.execution.current_attempt.attempt_id
                if run.view.execution.current_attempt
                else None,
            },
        )
        return reply()
    finally:
        await close_preserving(b)


def race_locker() -> dict[str, Any]:
    global STAGE
    STAGE = "race_lease_wait"
    g = load("grant_i_1.json")
    end = time.monotonic() + 6
    with closing(settings().connect(application_name="continuity-test")) as c:
        while True:
            stamp = c.execute(
                "SELECT floor(extract(epoch FROM clock_timestamp())*1000)::bigint AS now"
            ).fetchone()
            assert stamp is not None
            if stamp["now"] >= g["lease_until_ms"]:
                break
            assert time.monotonic() < end, "old_lease_not_expired"
            time.sleep(0.005)
        STAGE = "race_owner_lock"
        with c.transaction():
            c.execute(
                sql.SQL("SELECT * FROM {}.admission WHERE singleton FOR UPDATE").format(
                    sql.Identifier(settings().schema)
                )
            )
            owner_pid = c.info.backend_pid
            marker("recovery_race")
            STAGE = "race_writer_bindings"
            deadline = time.monotonic() + 0.75
            while True:
                c.execute("SELECT pg_stat_clear_snapshot()")
                writers = []
                for side in ("a", "b"):
                    try:
                        writers.append(load("race_" + side + "_backend.json"))
                    except (FileNotFoundError, AssertionError, json.JSONDecodeError):
                        break
                matching = []
                if len(writers) == 2:
                    assert [w["role"] for w in writers] == ["race-a", "race-b"]
                    assert (
                        len({w["process_pid"] for w in writers})
                        == len({w["backend_pid"] for w in writers})
                        == 2
                    )
                    expected_pids = [w["backend_pid"] for w in writers]
                    DIAGNOSTICS["owned_backend_ids"] = expected_pids
                    STAGE = "race_blocker_observation"
                    waiters = c.execute(
                        "SELECT pid,query,pg_blocking_pids(pid) AS blockers FROM pg_stat_activity WHERE usename='livekit_lab' AND pid=ANY(%s)",
                        (expected_pids,),
                    ).fetchall()
                    expected_query = (
                        'SELECT record_count,cancel_count FROM "'
                        + settings().schema
                        + '"."admission" WHERE singleton FOR UPDATE'
                    )
                    DIAGNOSTICS["queryVisibility"] = (
                        "redacted"
                        if any(r["query"] == "<insufficient privilege>" for r in waiters)
                        else "visible"
                        if waiters
                        else "unobserved"
                    )
                    DIAGNOSTICS["waiters"] = [
                        {"pid": r["pid"], "blockers": r["blockers"]} for r in waiters
                    ]
                    STAGE = "race_blocker_chain"
                    matching = [{"pid": r["pid"], "blockers": r["blockers"]} for r in waiters]
                    if (
                        len(matching) == 2
                        and {r["pid"] for r in matching} == set(expected_pids)
                        and any(owner_pid in r["blockers"] for r in matching)
                        and any(set(expected_pids) & set(r["blockers"]) for r in matching)
                    ):
                        assert all(
                            set(r["blockers"]) <= {owner_pid, *expected_pids} for r in matching
                        )
                        STAGE = "race_query_identity"
                        assert all(
                            r["query"] in {expected_query, "<insufficient privilege>"}
                            for r in waiters
                        ), "wrong_owned_lock_query"
                        assert DIAGNOSTICS["queryVisibility"] in {"visible", "redacted"}
                        break
                assert time.monotonic() < deadline, "recovery_waiter_graph_missing"
                time.sleep(0.001)
            save(
                "recovery-lock.json",
                {
                    "schema_version": 1,
                    "status": "passed",
                    "owner_backend_pid": owner_pid,
                    "work_schema": settings().schema,
                    "query_visibility": DIAGNOSTICS["queryVisibility"],
                    "lock_target": "p1_work_admission",
                    "owned_writers": writers,
                    "work_id": g["work_id"],
                    "old_attempt_id": g["attempt_id"],
                    "old_lease_until_ms": g["lease_until_ms"],
                    "observed_db_clock_ms": stamp["now"],
                    "waiters": matching,
                    "graphs": 1,
                },
            )
    return reply()


async def race_verify() -> dict[str, Any]:
    b = Bundle("i", 2)
    try:
        a, z = load("race_a.json"), load("race_b.json")
        assert (
            type(a["invoked"]) is bool
            and type(z["invoked"]) is bool
            and int(a["invoked"]) + int(z["invoked"]) == 1
        )
        current = await grant(b, "i", 2)
        assert current.attempt_id == a["attempt_id"] == z["attempt_id"]
        await result(b, "i", 2)
        await assert_accepted(b, "i")
        return reply()
    finally:
        await close_preserving(b)


async def specialist_loss() -> dict[str, Any]:
    b = Bundle("s")
    try:
        wid = await accept(b, "s")
        try:
            await b.runner.run_once(wid, command("s", 1))
        except DelegationRunError as error:
            assert error.code == "transport_unknown"
        else:
            raise AssertionError("killed_specialist_returned")
        g = await grant(b, "s", 1)
        assert await b.execution.result(work_id=wid, attempt_id=g.attempt_id) is None
        await assert_accepted(b, "s")
        return reply()
    finally:
        await close_preserving(b)


async def resume(label: str) -> dict[str, Any]:
    old = Bundle(label)
    try:
        await assert_accepted(old, label)
        g = await grant(old, label, 1)
        assert await old.execution.result(work_id=g.record.work_id, attempt_id=g.attempt_id) is None
        assert (await old.runner.run_once(g.record.work_id, command(label, 1))).invoked is False
        if label == "c":
            end = time.monotonic() + 3
            while True:
                peer = load("recovery-peer-b.json")
                rows = [r for r in peer["records"] if r["label"] == "coordinator_loss"]
                if rows and rows[0]["outcome"] == "aborted" and peer["counters"]["active"] == 0:
                    break
                assert time.monotonic() < end, "remote_close_not_settled"
                await asyncio.sleep(0.01)
        await expired(g.lease_until_ms)
    finally:
        await close_preserving(old)
    fresh = Bundle(label, 2)
    try:
        assert (
            await fresh.runner.run_once(str(work(label)["work_id"]), command(label, 2))
        ).invoked is True
        await result(fresh, label, 2)
        return reply()
    finally:
        await close_preserving(fresh)


async def result_before_resume() -> dict[str, Any]:
    b = Bundle("u")
    try:
        g = await grant(b, "u", 1)
        assert await b.execution.result(work_id=g.record.work_id, attempt_id=g.attempt_id) is None
        reg, t = directory()
        feed = open_result_feed_client(settings=settings(), directory=reg, token=t)
        try:
            assert all(e.attempt_id != g.attempt_id for e in (await feed.read(limit=100)).events)
        finally:
            await close_preserving(feed)
    finally:
        await close_preserving(b)
    return await resume("u")


async def result_after_resume() -> dict[str, Any]:
    b = Bundle("v")
    try:
        v = await result(b, "v", 1)
        run = await b.runner.run_once(v.work_id, command("v", 1))
        assert run.invoked is False and run.view.execution.result == v
        reg, t = directory()
        feed = open_result_feed_client(settings=settings(), directory=reg, token=t)
        try:
            assert (
                len(
                    [e for e in (await feed.read(limit=100)).events if e.attempt_id == v.attempt_id]
                )
                == 1
            )
        finally:
            await close_preserving(feed)
        return reply()
    finally:
        await close_preserving(b)


async def seed_real_case() -> None:
    if (folder() / "case.json").exists():
        return
    _, t = directory(True)
    client = open_postgres_client(
        actor=HELPER.ACTOR, token=t, settings=settings("case"), quote_database=supplier()
    )
    ctl = open_case_control_client(
        actor=HELPER.ACTOR, token=t, settings=settings("case"), quote_database=supplier()
    )
    try:
        observe_stage("case_submit")
        v = await client.submit(idempotency_key="recovery_real_case", request=HELPER.REQUEST)
        save("case.json", {"task_id": v.task_id, "case_id": v.case_id})
        observe_stage("case_inquire")
        await asyncio.to_thread(HELPER.inquire, settings("case"), supplier(), v.task_id)
        observe_stage("case_revise_first")
        await ctl.revise(task_id=v.task_id, expected_revision=0, request=HELPER.ALTERNATE)
        observe_stage("case_revise_second")
        await ctl.revise(task_id=v.task_id, expected_revision=1, request=HELPER.REQUEST)
    finally:
        await close_preserving(client, ctl)


async def quote_current() -> None:
    _, t = directory(True)
    client = open_postgres_client(
        actor=HELPER.ACTOR, token=t, settings=settings("case"), quote_database=supplier()
    )
    try:
        observe_stage("quote_prepare")
        q = await client.prepare_quote(
            task_id=str(load("case.json")["task_id"]),
            expected_revision=2,
            command_id="recovery_exact_quote",
        )
        save("quote.json", {"quote": q.quote.payload()})
    finally:
        await close_preserving(client)


def confirmation() -> Confirmation:
    return parse_confirmation_payload(
        canonical(load("quote.json")["quote"]).decode(), explicit=True
    )


async def project(b: Bundle) -> None:
    reg, t = directory(True)
    p = ProjectionProjector(
        events=open_result_feed_client(settings=settings(), directory=reg, token=t),
        executions=open_execution_client(settings=settings(), directory=reg, token=t),
        projections=open_projection_client(
            settings=settings("projection"), directory=reg, token=t, source_id=source()
        ),
        scope=COMPLETION,
        evidence=evidence(COMPLETION),
        case_authority=b.cases,
        timeout_ms=10000,
    )
    try:
        await p.project_once(limit=8)
    finally:
        await close_preserving(p)


async def delivery_begin() -> None:
    observe_stage("delivery_seed")
    await seed_real_case()
    observe_stage("delivery_construct")
    b = Bundle("g")
    try:
        observe_stage("delivery_accept_input")
        wid = await accept(b, "g")
        observe_stage("delivery_invoke")
        assert (await b.runner.run_once(wid, command("g", 1))).invoked
        await result(b, "g", 1)
        observe_stage("delivery_project")
        await project(b)
        observe_stage("delivery_process")
        await b.processed().process_once(limit=8)
        raise AssertionError("delivery_begin_kill_missing")
    finally:
        await close_preserving(b)


async def unknown_resume() -> dict[str, Any]:
    observe_stage("unknown_construct")
    b = Bundle("g")
    try:
        observe_stage("unknown_processing")
        step = await b.processed().process_once(limit=8)
        assert len(step.outcomes) == 1 and step.outcomes[0].state == "unknown"
        observe_stage("unknown_direct_delivery")
        assert (await b.delivered().deliver_once(str(work("g")["work_id"]))).state == "unknown"
        assert not (folder() / "receiver_call.json").exists()
        return reply()
    finally:
        await close_preserving(b)


async def receiver_crash() -> None:
    observe_stage("receiver_quote")
    await quote_current()
    observe_stage("receiver_construct")
    b = Bundle("m")
    try:
        observe_stage("receiver_accept_input")
        wid = await accept(b, "m")
        observe_stage("receiver_invoke")
        assert (await b.runner.run_once(wid, command("m", 1))).invoked
        await result(b, "m", 1)
        observe_stage("receiver_project")
        await project(b)
        observe_stage("receiver_process")
        await b.processed().process_once(limit=8)
        raise AssertionError("receiver_commit_kill_missing")
    finally:
        await close_preserving(b)


async def ack_m(b: Bundle) -> Any:
    reg, t = directory(True)
    client = open_processing_client(
        settings=settings("projection"), directory=reg, token=t, source_id=source(), policy=policy()
    )
    try:
        feed = open_result_feed_client(settings=settings(), directory=reg, token=t)
        try:
            event = next(e for e in (await feed.read(limit=8)).events if e.sequence == 2)
            return await client.acknowledgement(event_id=event.event_id)
        finally:
            await close_preserving(feed)
    finally:
        await close_preserving(client)


async def receiver_resume() -> dict[str, Any]:
    b = Bundle("m")
    try:
        observe_stage("receiver_reconcile")
        step = await b.processed().process_once(limit=8)
        assert any(o.sequence == 2 and o.state == "acknowledged" for o in step.outcomes)
        observe_stage("receiver_read_ack")
        a = await ack_m(b)
        assert a is not None and a.receipt is not None
        save("ack_m.json", json.loads(a.canonical()))
        observe_stage("receiver_read_delivery")
        d = await b.delivered().inspect(str(work("m")["work_id"]))
        assert d.state == "accepted" and d.snapshot.receipt == a.receipt
        save("delivery_m.json", asdict(cast(DeliveryReceipt, d.snapshot.receipt)))
        return reply()
    finally:
        await close_preserving(b)


async def processing_replay() -> dict[str, Any]:
    observe_stage("processing_construct")
    b = Bundle("m")
    try:
        observe_stage("processing_read_ack")
        prior = await ack_m(b)
        assert prior is not None and json.loads(prior.canonical()) == load("ack_m.json")
        observe_stage("processing_direct_delivery")
        direct = await b.delivered().deliver_once(str(work("m")["work_id"]))
        assert (
            direct.state == "accepted"
            and direct.receiver_invoked is False
            and asdict(cast(DeliveryReceipt, direct.snapshot.receipt)) == load("delivery_m.json")
        )
        observe_stage("processing_step")
        step = await b.processed().process_once(limit=8)
        assert len(step.outcomes) == 1 and step.outcomes[0].state == "unknown"
        assert (await ack_m(b)) == prior
        return reply()
    finally:
        await close_preserving(b)


def action_payload(v: ActionReceipt) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            canonical(
                {
                    "action_id": v.action_id,
                    "scope": {"tenant_id": v.scope.tenant_id, "account_id": v.scope.account_id},
                    "work_id": v.work_id,
                    "attempt_id": v.attempt_id,
                    "result_sha256": v.result_sha256,
                    "case_schema": v.case_schema,
                    "case_scope_id": v.case_scope_id,
                    "case_actor_id": v.case_actor_id,
                    "case_task_id": v.case_task_id,
                    "case_id": v.case_id,
                    "expected_revision": v.expected_revision,
                    "command_id": v.command_id,
                    "confirmation": v.confirmation.payload(),
                    "intent": v.intent.payload(),
                    "committed_at_ms": v.committed_at_ms,
                }
            )
        ),
    )


async def action_crash() -> None:
    observe_stage("action_construct")
    b = Bundle("m")
    try:
        observe_stage("action_authorize")
        await b.authorized().authorize_once(
            str(work("m")["work_id"]), confirmation=confirmation(), command_id="recovery_action_m"
        )
        raise AssertionError("action_commit_kill_missing")
    finally:
        await close_preserving(b)


async def action_resume() -> dict[str, Any]:
    b = Bundle("m")
    try:
        observe_stage("action_recover")
        v = (
            await b.authorized().authorize_once(
                str(work("m")["work_id"]),
                confirmation=confirmation(),
                command_id="recovery_action_m",
            )
        ).receipt
        save("action_m.json", action_payload(v))
        observe_stage("action_apply_supplier")
        await asyncio.to_thread(
            HELPER.mutate, settings("case"), supplier(), str(load("case.json")["task_id"])
        )
        observe_stage("action_verify_supplier")
        truth = supplier_truth()
        assert (
            truth["all_apply_calls"] == truth["applied_calls"] == 1
            and len(truth["mutation_receipts"]) == 1
        )
        observe_stage("action_inspect_example")
        known = await EXAMPLE.inspect_accepted(
            str(work("m")["work_id"]),
            coordinator=b.coordinator,
            runner=b.runner,
            delivery=b.delivered(),
            authorizer=b.authorized(),
        )
        assert known.action == v and known.delivery.snapshot.receipt is not None
        assert asdict(known.delivery.snapshot.receipt) == load("delivery_m.json")
        return reply()
    finally:
        await close_preserving(b)


async def conflicts() -> dict[str, Any]:
    observe_stage("conflict_construct")
    b = Bundle("m")
    try:
        observe_stage("conflict_result")
        v = await result(b, "m", 1)
        g = await grant(b, "m", 1)
        try:
            await b.execution.complete(attempt=g, body=b"{}")
        except WorkError as error:
            assert error.code == "identity_conflict"
        else:
            raise AssertionError("changed_result_accepted")
        observe_stage("conflict_issue")
        try:
            await b.execution.issue(
                work_id=v.work_id,
                owner_id=str(uuid4()),
                command_id="recovery_forbidden_after_result",
            )
        except WorkError as error:
            assert error.code == "identity_conflict"
        else:
            raise AssertionError("new_issue_after_result_accepted")
        observe_stage("conflict_confirmation")
        q = confirmation()
        altered = Confirmation(replace(q.quote, amount_minor=q.quote.amount_minor + 1), True)
        try:
            await b.authorized().authorize_once(
                v.work_id, confirmation=altered, command_id="recovery_action_m"
            )
        except CompletionError as error:
            assert error.code == "identity_conflict"
        else:
            raise AssertionError("changed_confirmation_accepted")
        observe_stage("conflict_foreign_read")
        reg, t = directory(False)
        foreign = open_execution_client(settings=settings(), directory=reg, token=t)
        try:
            try:
                await foreign.observe(work_id=v.work_id)
            except WorkError as foreign_error:
                assert foreign_error.code == "not_found"
            else:
                raise AssertionError("foreign_result_disclosed")
        finally:
            await close_preserving(foreign)
        observe_stage("conflict_cancel")
        await b.coordinator.cancel(v.work_id, "recovery_later_cancel_m")
        observe_stage("conflict_action_replay")
        a = await b.authorized().authorize_once(
            v.work_id, confirmation=q, command_id="recovery_action_m"
        )
        assert action_payload(a.receipt) == load("action_m.json")
        observe_stage("conflict_delivery_replay")
        d = await b.delivered().deliver_once(v.work_id)
        assert (
            asdict(cast(DeliveryReceipt, d.snapshot.receipt)) == load("delivery_m.json")
            and not d.receiver_invoked
        )
        return reply()
    finally:
        await close_preserving(b)


# OWNER_PROOF_IMPLEMENTATION
def supplier_truth() -> dict[str, Any]:
    value = cast(dict[str, Any], HELPER.supplier_truth(supplier()))
    with closing(sqlite3.connect(supplier().as_uri() + "?mode=ro", uri=True)) as c:
        value["all_apply_calls"] = c.execute("SELECT count(*) FROM apply_calls").fetchone()[0]
    return value


def inventory_digest(records: list[dict[str, object]]) -> str:
    assert type(records) is list and 1 <= len(records) <= 64, "inventory_count"
    h = hashlib.sha256(b"p3-recovery-inventory-v1\x00")
    total = 0
    for row in records:
        assert type(row) is dict
        raw = canonical(row)
        assert 1 <= len(raw) <= 4096, "inventory_record_bound"
        total += len(raw)
        assert total <= 65536, "inventory_total_bound"
        h.update(len(raw).to_bytes(4, "big"))
        h.update(raw)
    return h.hexdigest()


def owner_check() -> dict[str, Any]:
    observe_stage("owner_counts")
    records: list[dict[str, object]] = []
    ws = sql.Identifier(settings().schema)
    ps = sql.Identifier(settings("projection").schema)
    cs = sql.Identifier(settings("case").schema)
    with closing(settings().connect(application_name="continuity-test")) as c:

        def count(table: str) -> int:
            row = c.execute(
                sql.SQL("SELECT count(*) AS n FROM {}.{}").format(ws, sql.Identifier(table))
            ).fetchone()
            assert row is not None
            return int(row["n"])

        counts = {
            name: count(name)
            for name in (
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
        assert counts == {
            "accepted_work": 7,
            "issued_attempts": 11,
            "attempt_results": 7,
            "result_feed_events": 7,
            "result_delivery_intents": 2,
            "result_delivery_possible": 2,
            "result_delivery_receipts": 1,
            "result_actions": 1,
        }
        observe_stage("owner_case_counts")
        case_counts = {}
        for table in (
            "action_intents",
            "confirmations",
            "mutation_effects",
            "business_outcomes",
            "completion_events",
            "completion_deliveries",
        ):
            total = c.execute(
                sql.SQL("SELECT count(*) AS n FROM {}.{}").format(cs, sql.Identifier(table))
            ).fetchone()
            assert total is not None
            case_counts[table] = total["n"]
        assert case_counts == {
            "action_intents": 1,
            "confirmations": 1,
            "mutation_effects": 1,
            "business_outcomes": 1,
            "completion_events": 1,
            "completion_deliveries": 1,
        }
        for label in LABELS:
            observe_stage("owner_body_" + label)
            original = work(label)
            saved = load("result_" + label + ".json")
            s = scope(label)
            row = c.execute(
                sql.SQL(
                    "SELECT w.*,r.attempt_id,r.body AS result_body,r.sha256 AS result_sha256,r.recorded_at_ms,r.disposition,f.event_id,f.sequence,a.command_id,a.owner_id,a.number,a.epoch,a.lease_until_ms FROM {}.accepted_work w JOIN {}.attempt_results r USING(tenant_id,account_id,work_id) JOIN {}.issued_attempts a USING(tenant_id,account_id,work_id,attempt_id) JOIN {}.result_feed_events f USING(tenant_id,account_id,work_id,attempt_id) WHERE w.work_id=%s::uuid"
                ).format(ws, ws, ws, ws),
                (original["work_id"],),
            ).fetchone()
            assert row is not None
            assert (
                row["tenant_id"] == s.tenant_id
                and row["account_id"] == s.account_id
                and row["sha256"]
                == original["request_sha256"]
                == hashlib.sha256(bytes(row["body"])).hexdigest()
                and bytes(row["body"]) == canonical(original["request"])
            )
            observe_stage("owner_result_" + label)
            req = parse_request(bytes(row["body"]))
            res = parse_result(bytes(row["result_body"]))
            assert (
                row["result_sha256"]
                == saved["sha256"]
                == hashlib.sha256(bytes(row["result_body"])).hexdigest()
                and str(row["attempt_id"]) == saved["attempt_id"]
                and row["disposition"] == "eligible_at_commit"
            )
            assert (
                res.input_fingerprint == req.input_fingerprint
                and res.case_id == req.case_id
                and res.request_revision == req.request_revision
                and res.scope == s
                and res.attempt_id == "attempt_" + UUID(str(row["attempt_id"])).hex
            )
            observe_stage("owner_identity_" + label)
            number = 1 if label in {"v", "g", "m"} else 2
            assert (
                row["number"] == row["epoch"] == number
                and row["command_id"] == command(label, number)
                and str(row["owner_id"]) == owner(label, number)
            )
            records.append(
                {
                    "kind": "result",
                    "label": label,
                    "scope": asdict(s),
                    "work_id": original["work_id"],
                    "request_sha256": row["sha256"],
                    "attempt_id": str(row["attempt_id"]),
                    "command_id": row["command_id"],
                    "owner_id": str(row["owner_id"]),
                    "number": row["number"],
                    "event_id": str(row["event_id"]),
                    "sequence": row["sequence"],
                    "result_sha256": row["result_sha256"],
                    "input_fingerprint": req.input_fingerprint,
                }
            )
        observe_stage("owner_grants")
        grants = c.execute(
            sql.SQL(
                "SELECT work_id::text,attempt_id::text,tenant_id,account_id,command_id,owner_id::text,number,epoch,issued_at_ms,lease_until_ms FROM {}.issued_attempts ORDER BY command_id"
            ).format(ws)
        ).fetchall()
        assert len(grants) == 11
        for g in grants:
            label = g["command_id"].split("_")[1]
            assert (
                label in LABELS
                and g["owner_id"] == owner(label, g["number"])
                and g["epoch"] == g["number"]
                and g["work_id"] == work(label)["work_id"]
            )
            records.append({"kind": "grant", **g})
        # Source observation is independently correlated to actual public server input.
        observe_stage("owner_peer")
        peer_records = []
        for generation in ("a", "b"):
            peer_records.extend(load("recovery-peer-" + generation + ".json")["records"])
        assert len(peer_records) == 10
        mapping = {
            "issued_recovery": ("i", 2),
            "specialist_loss": ("s", 1),
            "specialist_recovery": ("s", 2),
            "coordinator_loss": ("c", 1),
            "coordinator_recovery": ("c", 2),
            "result_precommit": ("u", 1),
            "result_precommit_recovery": ("u", 2),
            "result_postcommit": ("v", 1),
            "unknown_delivery": ("g", 1),
            "useful_current": ("m", 1),
        }
        for p in peer_records:
            label, number = mapping[p["label"]]
            r = work(label)
            g = next(x for x in grants if x["command_id"] == command(label, number))
            req = parse_request(canonical(r["request"]))
            transport = replace(
                req,
                attempt=replace(
                    req.attempt, attempt_id="attempt_" + UUID(g["attempt_id"]).hex, number=number
                ),
            )
            assert (
                p["scope"] == asdict(scope(label))
                and p["delegation_id"] == req.delegation_id
                and p["case_id"] == req.case_id
                and p["request_revision"] == req.request_revision
                and p["input_fingerprint"] == req.input_fingerprint
                and p["attempt_id"] == transport.attempt.attempt_id
                and p["request_sha256"] == hashlib.sha256(encode_request(transport)).hexdigest()
            )
            records.append(
                {
                    "kind": "invoke",
                    "label": p["label"],
                    "attempt_id": g["attempt_id"],
                    "request_sha256": p["request_sha256"],
                    "outcome": p["outcome"],
                }
            )
        observe_stage("owner_projection")
        projected = c.execute(
            sql.SQL("SELECT * FROM {}.projected_results ORDER BY event_sequence").format(ps)
        ).fetchall()
        assert len(projected) == 2
        for row in projected:
            p = parse_projected(row["body_json"].encode())
            assert (
                p.event.source_id == source()
                and p.event.scope == WorkScope(COMPLETION.tenant_id, COMPLETION.account_id)
                and hashlib.sha256(p.canonical()).hexdigest() == row["body_sha256"]
            )
            label = "g" if p.event.sequence == 1 else "m"
            r = load("result_" + label + ".json")
            assert (
                p.event.work_id == r["work_id"]
                and p.event.attempt_id == r["attempt_id"]
                and p.event.result_sha256 == r["sha256"]
                and p.request_sha256 == work(label)["request_sha256"]
            )
        observe_stage("owner_ack")
        acks = c.execute(sql.SQL("SELECT * FROM {}.processing_acks").format(ps)).fetchall()
        assert len(acks) == 1
        ack = parse_ack(acks[0]["body_json"].encode())
        assert (
            json.loads(ack.canonical()) == load("ack_m.json")
            and ack.event.sequence == 2
            and ack.event.work_id == work("m")["work_id"]
            and ack.receipt is not None
        )
        observe_stage("owner_control")
        control = c.execute(
            sql.SQL(
                "SELECT terminal_watermark,terminal_count,scan_after FROM {}.processing_control WHERE singleton"
            ).format(ps)
        ).fetchone()
        assert control == {"terminal_watermark": 0, "terminal_count": 1, "scan_after": 1}
        observe_stage("owner_delivery")
        receipts = c.execute(
            sql.SQL(
                "SELECT i.*,r.receipt_id::text,r.accepted_at_ms FROM {}.result_delivery_intents i JOIN {}.result_delivery_receipts r USING(delivery_id)"
            ).format(ws, ws)
        ).fetchall()
        assert len(receipts) == 1
        receipt = receipts[0]
        assert (
            str(receipt["delivery_id"]) == ack.receipt.delivery_id
            and receipt["receipt_id"] == ack.receipt.receipt_id
            and receipt["accepted_at_ms"] == ack.receipt.accepted_at_ms
            and str(receipt["work_id"]) == ack.event.work_id
            and str(receipt["attempt_id"]) == ack.event.attempt_id
            and receipt["result_sha256"] == ack.event.result_sha256
            and str(receipt["receiver_id"]) == policy().receiver_id
            and receipt["recipient_id"] == RECIPIENT
        )
        observe_stage("owner_action")
        receiver_accept_calls = len(tuple(folder().glob("receiver_call.json")))
        assert (
            receiver_accept_calls == 1 and not (folder() / "receiver_call_duplicate.json").exists()
        )
        assert load("receiver_call.json") == {
            "delivery_id": ack.receipt.delivery_id,
            "work_id": ack.event.work_id,
            "attempt_id": ack.event.attempt_id,
            "result_sha256": ack.event.result_sha256,
        }
        action = c.execute(sql.SQL("SELECT * FROM {}.result_actions").format(ws)).fetchone()
        assert action is not None
        saved = load("action_m.json")
        assert (
            str(action["action_id"]) == saved["action_id"]
            and str(action["work_id"]) == work("m")["work_id"]
            and str(action["attempt_id"]) == ack.event.attempt_id
            and action["result_sha256"] == ack.event.result_sha256
        )
        assert (
            action["case_schema"] == settings("case").schema
            and action["case_scope_id"] == HELPER.ACTOR.scope_id
            and action["case_actor_id"] == HELPER.ACTOR.actor_id
            and str(action["case_task_id"]) == load("case.json")["task_id"]
            and str(action["case_id"]) == load("case.json")["case_id"]
            and action["expected_revision"] == 2
        )
        assert (
            json.loads(action["confirmation_json"]) == saved["confirmation"]
            and json.loads(action["intent_json"]) == saved["intent"]
        )
        observe_stage("owner_case_effect")
        joined = c.execute(
            sql.SQL(
                "SELECT i.*,c.payload_json AS confirmation_payload,c.actor_id AS confirmation_actor,c.scope_id AS confirmation_scope,e.state AS effect_state,e.result_json,e.dispatch_count FROM {}.action_intents i JOIN {}.confirmations c USING(confirmation_id,task_id) JOIN {}.mutation_effects e USING(intent_id,task_id) WHERE i.intent_id=%s"
            ).format(cs, cs, cs),
            (str(action["intent_id"]),),
        ).fetchone()
        assert (
            joined is not None
            and json.loads(joined["payload_json"]) == saved["intent"]
            and json.loads(joined["confirmation_payload"]) == saved["confirmation"]
            and joined["effect_state"] == "succeeded"
            and joined["dispatch_count"] == 1
        )
        observe_stage("owner_supplier")
        truth = supplier_truth()
        assert (
            truth["all_apply_calls"] == truth["applied_calls"] == 1
            and len(truth["mutation_receipts"]) == 1
            and truth["bookings"][0][3] == 1
        )
        sr = truth["mutation_receipts"][0]
        assert (
            sr["effect_id"] == joined["effect_id"] == saved["intent"]["effect_id"]
            and sr["scope_id"] == HELPER.ACTOR.scope_id
            and sr["result"] == json.loads(joined["result_json"])
        )
        observe_stage("owner_business")
        completed = c.execute(
            sql.SQL(
                "SELECT o.payload_json AS outcome_json,e.event_id,e.payload_json AS event_json,d.state,d.attempts,d.target_id FROM {}.business_outcomes o JOIN {}.completion_events e USING(task_id) JOIN {}.completion_deliveries d USING(event_id) WHERE o.task_id=%s"
            ).format(cs, cs, cs),
            (load("case.json")["task_id"],),
        ).fetchone()
        assert (
            completed is not None
            and completed["state"] == "pending"
            and completed["attempts"] == 0
            and completed["target_id"] is None
        )
        outcome = json.loads(completed["outcome_json"])
        event = json.loads(completed["event_json"])
        assert (
            event["outcome"] == outcome
            and event["event_id"] == completed["event_id"]
            and outcome["task_id"] == load("case.json")["task_id"]
            and outcome["effect_id"] == joined["effect_id"]
            and outcome["state"] == "succeeded"
        )
        records.append(
            {
                "kind": "completion",
                "work_id": ack.event.work_id,
                "attempt_id": ack.event.attempt_id,
                "result_sha256": ack.event.result_sha256,
                "delivery_id": ack.receipt.delivery_id,
                "receipt_id": ack.receipt.receipt_id,
                "event_id": ack.event.event_id,
                "action_id": saved["action_id"],
                "intent_id": str(joined["intent_id"]),
                "effect_id": joined["effect_id"],
                "confirmation_sha256": hashlib.sha256(canonical(saved["confirmation"])).hexdigest(),
                "supplier_result_sha256": hashlib.sha256(canonical(sr["result"])).hexdigest(),
                "business_event_id": completed["event_id"],
            }
        )
    observe_stage("owner_receiver")
    with closing(
        sqlite3.connect((folder() / "receiver.sqlite3").as_uri() + "?mode=ro", uri=True)
    ) as receiver_db:
        sqlite_rows = receiver_db.execute(
            "SELECT intent_json,receipt_json FROM result_receipts"
        ).fetchall()
        assert len(sqlite_rows) == 1
        ri, rr = map(json.loads, sqlite_rows[0])
        assert (
            rr == load("delivery_m.json")
            and rr == asdict(ack.receipt)
            and ri["work_id"] == ack.event.work_id
            and ri["attempt_id"] == ack.event.attempt_id
            and ri["result_sha256"] == ack.event.result_sha256
            and ri["scope"]
            == {"tenant_id": COMPLETION.tenant_id, "account_id": COMPLETION.account_id}
        )
        assert (
            hashlib.sha256(base64.b64decode(ri["body"], validate=True)).hexdigest()
            == ack.event.result_sha256
        )
    observe_stage("owner_inventory")
    save(
        "recovery-authority.json",
        {
            "schema_version": 1,
            "status": "passed",
            "counts": {
                "accepted": 7,
                "attempts": 11,
                "results": 7,
                "events": 7,
                "projected": 2,
                "acks": 1,
                "delivery_intents": 2,
                "delivery_receipts": 1,
                "receiver_accept_calls": receiver_accept_calls,
                "receiver_receipts": 1,
                "action_receipts": 1,
                "intents": 1,
                "supplier_apply_calls": 1,
                "supplier_receipts": 1,
                "business_completions": 1,
            },
            "records": records,
            "inventory_sha256": inventory_digest(records),
            "gap": {
                "work_id": work("g")["work_id"],
                "sequence": 1,
                "delivery_state": "unknown",
                "acknowledged": False,
            },
            "processing": control,
            "exact_reconciliation": True,
        },
    )
    return reply()


def cleanup() -> dict[str, Any]:
    first: BaseException | None = None
    try:
        HELPER.cleanup(settings("case"))
    except BaseException as error:  # noqa: BLE001 - attempt all independent owners before rethrowing first failure.
        first = error
    for kind, prefix, markers in [
        (
            "work",
            "p1_work_recovery_",
            {
                "continuity-readonly-work-v1",
                "continuity-readonly-work-v2",
                "continuity-readonly-work-v3",
                "continuity-readonly-work-v4",
            },
        ),
        (
            "projection",
            "p3_projection_recovery_",
            {
                "delegation-result-projection-v1",
                "delegation-result-projection-v2",
                "delegation-result-projection-v3",
            },
        ),
    ]:
        try:
            s = settings(kind)
            assert s.schema.startswith(prefix)
            with closing(s.connect(application_name="continuity-test")) as c:
                row = c.execute(
                    "SELECT pg_get_userbyid(nspowner) AS owner,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                    [s.schema],
                ).fetchone()
                if row is not None:
                    assert row["owner"] == "continuity_migrator" and row["marker"] in markers
                    c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(s.schema)))
                assert (
                    c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", [s.schema]).fetchone()
                    is None
                )
        except BaseException as error:  # noqa: BLE001 - attempt all independent owners before rethrowing first failure.
            if first is None:
                first = error
    if first is not None:
        raise first
    return reply()


async def dispatch() -> dict[str, Any] | None:
    global STAGE
    STAGE = MODE
    if MODE == "install":
        return install()
    if MODE == "cleanup":
        return cleanup()
    if MODE == "owner-check":
        return owner_check()
    if MODE == "race-locker":
        return race_locker()
    if MODE == "issued-crash":
        await execution_crash("i")
    elif MODE == "issued-replay":
        return await issued_replay()
    elif MODE.startswith("race-") and MODE in {"race-a", "race-b"}:
        return await race_writer(MODE[-1])
    elif MODE == "race-verify":
        return await race_verify()
    elif MODE == "specialist-loss":
        return await specialist_loss()
    elif MODE == "specialist-resume":
        return await resume("s")
    elif MODE == "coordinator-crash":
        await execution_crash("c")
    elif MODE == "coordinator-resume":
        return await resume("c")
    elif MODE == "result-before-crash":
        await execution_crash("u")
    elif MODE == "result-before-resume":
        return await result_before_resume()
    elif MODE == "result-after-crash":
        await execution_crash("v")
    elif MODE == "result-after-resume":
        return await result_after_resume()
    elif MODE == "delivery-begin-crash":
        await delivery_begin()
    elif MODE == "unknown-resume":
        return await unknown_resume()
    elif MODE == "receiver-crash":
        await receiver_crash()
    elif MODE == "receiver-resume":
        return await receiver_resume()
    elif MODE == "processing-replay":
        return await processing_replay()
    elif MODE == "action-crash":
        await action_crash()
    elif MODE == "action-resume":
        return await action_resume()
    elif MODE == "conflicts":
        return await conflicts()
    else:
        raise AssertionError("unsupported_mode")
    return None


def failure_identity(error: Exception) -> tuple[str, str]:
    public_types = (
        (WorkError, "WorkError"),
        (DelegationRunError, "DelegationRunError"),
        (CompletionError, "CompletionError"),
        (ProjectionError, "ProjectionError"),
    )
    if type(error) is AssertionError:
        return "AssertionError", "fixture_failed"
    for cls, name in public_types:
        if type(error) is cls:
            value = vars(error).get("code")
            return name, value if type(
                value
            ) is str and value in DIAGNOSTIC_CODES else "fixture_failed"
    return "DependencyError", "fixture_failed"


def main() -> int:
    global MODE
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=MODE_ORDER)
    args = parser.parse_args()
    MODE = args.mode
    try:
        environment()
        value = asyncio.run(dispatch())
        assert value == RESPONSES[MODE] and value is not None
        assert DIAGNOSTICS["cleanup_failure"] is False, "owned_cleanup_failed"
        print(json.dumps(value, separators=(",", ":")))
        return 0
    except Exception as error:  # noqa: BLE001 - fixed, payload-free process report boundary.
        error_name, code = failure_identity(error)
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "failed",
                    "mode": MODE,
                    "stage": STAGE,
                    "diagnostics": DIAGNOSTICS,
                    "error_type": error_name,
                    "code": code,
                },
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
