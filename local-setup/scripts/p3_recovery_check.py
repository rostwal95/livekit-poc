"""Bounded explicit P3 process recovery qualification; no second execution owner."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p3_coordinator_check as core

from harness.process_control import (
    FileBarrier,
    OwnedProcess,
    ProcessControlError,
    ProcessExited,
    ProcessTimeout,
)

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
ROOT = Path(__file__).resolve().parents[2]
MODE = "local_synthetic_p3_recovery"
DEADLINE_SECONDS = 180.0
CLEANUP_SECONDS = 15.0
MAX_REPORT_BYTES = 32768
MAX_CAPTURE_BYTES = 131072
MAX_STREAM_BYTES = 2048
PROOF_FILES = ("recovery-authority.json", "recovery-peer.json", "recovery-lock.json")
MAX_PROOF_BYTES = 32768
GateError = core.GateError
BARRIERS = {
    "issued-crash": "issue_commit",
    "race-a": "race_a_ready",
    "race-b": "race_b_ready",
    "race-locker": "recovery_race",
    "coordinator-crash": "coordinator_http_started",
    "result-before-crash": "result_before",
    "result-after-crash": "result_after",
    "delivery-begin-crash": "delivery_begin",
    "receiver-crash": "receiver_committed",
    "action-crash": "action_commit",
}
KILLED = frozenset(n for n, r in RESPONSES.items() if r is None)
EXPECTED_COUNTS = {
    "accepted": 7,
    "acks": 1,
    "action_receipts": 1,
    "attempts": 11,
    "business_completions": 1,
    "delivery_intents": 2,
    "delivery_receipts": 1,
    "events": 7,
    "intents": 1,
    "projected": 2,
    "receiver_accept_calls": 1,
    "receiver_receipts": 1,
    "results": 7,
    "supplier_apply_calls": 1,
    "supplier_receipts": 1,
}
SUCCESS = {
    "autonomous_scheduler": False,
    "blocking_graphs_observed": 1,
    "case_results": [
        {
            "code": "ok",
            "name": "specialist_process_kill_retains_accepted_input",
            "status": "passed",
        },
        {"code": "ok", "name": "original_issue_replay_never_reinvokes", "status": "passed"},
        {
            "code": "ok",
            "name": "premature_new_command_waits_for_authority_lease",
            "status": "passed",
        },
        {"code": "ok", "name": "explicit_new_command_recovers_useful_result", "status": "passed"},
        {"code": "ok", "name": "coordinator_http_loss_remote_cleanup_observed", "status": "passed"},
        {
            "code": "ok",
            "name": "fresh_coordinator_preserves_input_attempt_history",
            "status": "passed",
        },
        {"code": "ok", "name": "concurrent_recovery_one_created_issue", "status": "passed"},
        {
            "code": "ok",
            "name": "result_precommit_kill_rolls_back_result_and_event",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "result_postcommit_kill_original_bytes_replayed",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "possible_delivery_restart_remains_lookup_only_unknown",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "later_current_work_progresses_around_unknown_gap",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "receiver_commit_kill_original_receipt_reconciled",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "fresh_processing_replay_preserves_original_ack",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "action_commit_kill_exact_confirmation_original_receipt",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "changed_completion_command_scope_rejected_without_effect",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "independent_history_receiver_supplier_joins_and_cleanup",
            "status": "passed",
        },
        {
            "code": "ok",
            "name": "coordinator_post_issue_crash_before_first_http",
            "status": "passed",
        },
    ],
    "child_terminations": 8,
    "cleanup_complete": True,
    "completion_case_authority": "actual_p1_case_v4_exact_confirmation",
    "early_case_authority": "synthetic_read_only_only",
    "errors": 0,
    "exactly_once_physical_computation_claimed": False,
    "failures": 0,
    "mode": "local_synthetic_p3_recovery",
    "passed": 17,
    "provider_calls": False,
    "schema_version": 1,
    "skipped": 0,
    "source_authority": "actual_p1_work_v4_existing_execution_completion",
    "status": "passed",
    "supplier_authority": "independent_synthetic_sqlite_actual_leased_worker",
    "tests": 17,
}


def exact_child(value: object, expected: object) -> bool:
    if type(value) is not type(expected):
        return False
    if type(expected) is dict and type(value) is dict:
        return value.keys() == expected.keys() and all(
            exact_child(value[k], v) for k, v in expected.items()
        )
    if type(expected) is list and type(value) is list:
        return len(value) == len(expected) and all(
            exact_child(a, b) for a, b in zip(value, expected, strict=True)
        )
    return value == expected


def decode(raw: bytes, maximum: int = MAX_REPORT_BYTES) -> dict[str, Any]:
    if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
        raise GateError("invalid_report")
    try:
        value = json.loads(
            raw.decode(),
            object_pairs_hook=core.unique_object,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, UnicodeError, RecursionError, core.GateError):
        raise GateError("invalid_report") from None
    if type(value) is not dict:
        raise GateError("invalid_report")
    return value


def validate_child_environment(environment: dict[str, str], mode: str) -> None:
    if type(mode) is not str or mode not in MODE_KEYS:
        raise GateError("invalid_child_mode")
    required = MODE_KEYS[mode]
    if (
        not required <= environment.keys()
        or environment.keys() - required - set(BASE_KEYS)
        or any(type(v) is not str or not v or "\x00" in v for v in environment.values())
    ):
        raise GateError("unsafe_child_environment")
    patterns = {
        "WORK_SCHEMA": r"p1_work_recovery_[0-9a-f]{32}",
        "CASE_SCHEMA": r"p3_completion_[0-9a-f]{32}",
        "PROJECTION_SCHEMA": r"p3_projection_recovery_[0-9a-f]{32}",
    }
    if any(re.fullmatch(p, environment["P3_RECOVERY_" + k]) is None for k, p in patterns.items()):
        raise GateError("unsafe_child_environment")
    if (
        not 1 <= len(environment["P3_RECOVERY_PG_PORT"]) <= 5
        or not environment["P3_RECOVERY_PG_PORT"].isascii()
        or not environment["P3_RECOVERY_PG_PORT"].isdigit()
        or not 1 <= int(environment["P3_RECOVERY_PG_PORT"]) <= 65535
    ):
        raise GateError("unsafe_child_environment")
    directory = Path(environment["P3_RECOVERY_DIRECTORY"])
    if (
        not directory.is_absolute()
        or ".." in directory.parts
        or str(directory) != os.path.normpath(environment["P3_RECOVERY_DIRECTORY"])
    ):
        raise GateError("unsafe_child_environment")
    if mode not in OWNER_MODES:
        generation = (
            "a"
            if mode
            in {
                "issued-crash",
                "issued-replay",
                "race-a",
                "race-b",
                "race-verify",
                "specialist-loss",
            }
            else "b"
        )
        endpoint = directory / ("endpoint-" + generation + ".json")
        if environment["P3_RECOVERY_ENDPOINT_FILE"] != str(endpoint):
            raise GateError("unsafe_child_environment")
        if any(
            re.fullmatch(r"[A-Za-z0-9_-]{43}", environment[key]) is None
            for key in (
                "P3_RECOVERY_EXECUTION_TOKEN",
                "P3_RECOVERY_COMPLETION_TOKEN",
                "P3_RECOVERY_NODE_TOKEN",
            )
        ):
            raise GateError("unsafe_child_environment")
    if mode in BARRIERS and environment["P3_RECOVERY_BARRIER"] != str(
        directory / (BARRIERS[mode] + ".reached")
    ):
        raise GateError("unsafe_child_environment")


def child_environment(
    values: dict[str, str], *, mode: str, context: dict[str, str]
) -> dict[str, str]:
    if type(mode) is not str or mode not in MODE_KEYS:
        raise GateError("invalid_child_mode")
    mapping = {
        "P3_RECOVERY_OWNER_PASSWORD": "POSTGRES_MIGRATION_PASSWORD",
        "P3_RECOVERY_RUNTIME_PASSWORD": "POSTGRES_PASSWORD",
        "P3_RECOVERY_PG_PORT": "POSTGRES_PORT",
    }
    try:
        env = {
            **core.base_environment(),
            **{n: values[mapping[n]] if n in mapping else context[n] for n in MODE_KEYS[mode]},
        }
    except KeyError:
        raise GateError("missing_setup") from None
    validate_child_environment(env, mode)
    return env


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
DIAGNOSTIC_SUBSTAGES = frozenset(
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
DIAGNOSTIC_STAGES = frozenset(
    {
        "configuration",
        *DIAGNOSTIC_SUBSTAGES,
        *MODE_ORDER,
        *("owner_" + label for label in "iscuvgm"),
        "race_lease_wait",
        "race_owner_lock",
        "race_writer_bindings",
        "race_blocker_observation",
        "race_query_identity",
        "race_blocker_chain",
    }
)


def validated_failure(raw: bytes, mode: str) -> dict[str, Any]:
    if type(mode) is not str or mode not in MODE_KEYS:
        raise GateError("invalid_diagnostic")
    value = decode(raw, 2048)
    if (
        set(value)
        != {"schema_version", "status", "mode", "stage", "error_type", "code", "diagnostics"}
        or not exact_child(value["schema_version"], 1)
        or value["status"] != "failed"
        or value["mode"] != mode
        or type(value["stage"]) is not str
        or value["stage"] not in DIAGNOSTIC_STAGES
        or type(value["error_type"]) is not str
        or value["error_type"]
        not in {
            "AssertionError",
            "WorkError",
            "DelegationRunError",
            "CompletionError",
            "ProjectionError",
            "DependencyError",
        }
        or type(value["code"]) is not str
        or value["code"] not in DIAGNOSTIC_CODES
    ):
        raise GateError("invalid_diagnostic")
    state = value["diagnostics"]
    if (
        type(state) is not dict
        or set(state) != {"queryVisibility", "owned_backend_ids", "waiters", "cleanup_failure"}
        or type(state["cleanup_failure"]) is not bool
        or type(state["queryVisibility"]) is not str
        or state["queryVisibility"] not in {"visible", "redacted", "unobserved"}
        or type(state["owned_backend_ids"]) is not list
        or len(state["owned_backend_ids"]) > 2
        or any(not natural(i, 1, 2147483647) for i in state["owned_backend_ids"])
        or len(set(state["owned_backend_ids"])) != len(state["owned_backend_ids"])
        or type(state["waiters"]) is not list
        or len(state["waiters"]) > 2
    ):
        raise GateError("invalid_diagnostic")
    for waiter in state["waiters"]:
        if (
            type(waiter) is not dict
            or set(waiter) != {"pid", "blockers"}
            or not natural(waiter["pid"], 1, 2147483647)
            or waiter["pid"] not in state["owned_backend_ids"]
            or type(waiter["blockers"]) is not list
            or len(waiter["blockers"]) > 2
            or any(not natural(i, 1, 2147483647) for i in waiter["blockers"])
        ):
            raise GateError("invalid_diagnostic")
    return value


def validated_parent_failure(raw: bytes) -> dict[str, Any]:
    value = decode(raw, 2048)
    if (
        set(value)
        != {"schema_version", "status", "diagnostic_only", "parent_observation", "child_failure"}
        or not exact_child(value["schema_version"], 1)
        or value["status"] != "failed"
        or value["diagnostic_only"] is not True
    ):
        raise GateError("invalid_diagnostic")
    observation = value["parent_observation"]
    if type(observation) is not dict or set(observation) != {
        "child",
        "operation",
        "barrier",
        "kind",
        "process_pid",
        "returncode",
    }:
        raise GateError("invalid_diagnostic")
    child, operation, barrier = (
        observation["child"],
        observation["operation"],
        observation["barrier"],
    )
    if (
        type(child) is not str
        or child not in {*MODE_ORDER, "server-a", "server-b", "compile"}
        or type(operation) is not str
        or operation not in {"wait", "kill", "finish"}
        or type(observation["kind"]) is not str
        or observation["kind"] not in {"exited", "timeout", "control_error"}
        or not natural(observation["process_pid"], 1, 2147483647)
        or (
            observation["returncode"] is not None
            and not natural(observation["returncode"], -255, 255)
        )
    ):
        raise GateError("invalid_diagnostic")
    allowed = (
        {BARRIERS[child]}
        if child in BARRIERS
        else {"peer_a", "specialist_http_started"}
        if child == "server-a"
        else {"peer_b", "coordinator_remote_started"}
        if child == "server-b"
        else set()
    )
    if operation == "wait":
        if type(barrier) is not str or barrier not in allowed:
            raise GateError("invalid_diagnostic")
    elif barrier is not None:
        raise GateError("invalid_diagnostic")
    failure = value["child_failure"]
    if failure is not None:
        if child not in MODE_KEYS or type(failure) is not dict or observation["returncode"] is None:
            raise GateError("invalid_diagnostic")
        validated_failure(json.dumps(failure, allow_nan=False).encode(), child)
    return value


def validated_stage(raw: bytes, mode: str) -> dict[str, Any]:
    if type(mode) is not str or mode not in RESPONSES or RESPONSES[mode] is None:
        raise GateError("invalid_child_mode")
    value = decode(raw)
    if not exact_child(value, RESPONSES[mode]):
        raise GateError("invalid_report")
    return value


def validated_report(raw: bytes) -> dict[str, Any]:
    v = decode(raw)
    expected = SUCCESS
    if v.keys() != expected.keys() | {
        "duration_seconds",
        "child_commands",
        "node_version",
        "proofs",
    } or any(not exact_child(v[k], value) for k, value in expected.items()):
        raise GateError("invalid_report")
    d = v["duration_seconds"]
    children = v["child_commands"]
    if (
        type(d) not in (int, float)
        or not 0 < d <= 180
        or not math.isfinite(d)
        or type(children) is not int
        or children != 28
        or not core.supported_node(v["node_version"])
    ):
        raise GateError("invalid_report")
    proofs = v["proofs"]
    if type(proofs) is not dict or set(proofs) != set(PROOF_FILES):
        raise GateError("invalid_report")
    for r in proofs.values():
        if (
            type(r) is not dict
            or set(r) != {"bytes", "sha256"}
            or type(r["bytes"]) is not int
            or not 1 <= r["bytes"] <= MAX_PROOF_BYTES
            or not hash_value(r["sha256"])
        ):
            raise GateError("invalid_report")
    return v


def target_path(root: Path, path: Path) -> Path:
    p = (path if path.is_absolute() else root / path).absolute()
    base = root / ".local/validation/p3-recovery"
    if (
        ".." in p.parts
        or p.parent != base
        or p.suffix != ".json"
        or re.fullmatch(r"[a-z0-9_-]{1,80}\.json", p.name) is None
        or any(x.is_symlink() for x in (p, *p.parents))
    ):
        raise GateError("unsafe_evidence_path")
    core.private_directory(p.parent)
    if p.exists():
        raise GateError("existing_report")
    proof = p.with_name(p.stem + "-artifacts")
    if proof.exists() or proof.is_symlink():
        raise GateError("existing_proof")
    return p


def write_json(path: Path, value: object, maximum: int = MAX_REPORT_BYTES) -> None:
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > maximum:
        raise GateError("report_limit")
    with os.fdopen(
        os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), "wb"
    ) as out:
        out.write(raw)


def bounded_read(path: Path, maximum: int) -> bytes:
    s = path.lstat()
    if (
        not stat.S_ISREG(s.st_mode)
        or s.st_uid != os.geteuid()
        or stat.S_IMODE(s.st_mode) != 0o600
        or s.st_nlink != 1
        or not 0 <= s.st_size <= maximum
    ):
        raise GateError("invalid_artifact")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as inp:
        raw = inp.read(maximum + 1)
    if len(raw) > maximum:
        raise GateError("invalid_artifact")
    return raw


def uuid_value(v: object) -> bool:
    if type(v) is not str:
        return False
    try:
        u = UUID(v)
        return u.version == 4 and str(u) == v
    except ValueError:
        return False


def hash_value(v: object) -> bool:
    return type(v) is str and re.fullmatch(r"[a-f0-9]{64}", v) is not None


def natural(v: object, minimum: int = 0, maximum: int = 4102444800000) -> bool:
    return type(v) is int and minimum <= v <= maximum


def inventory_digest(records: list[dict[str, Any]]) -> str:
    if type(records) is not list or not 1 <= len(records) <= 64:
        raise GateError("invalid_proof")
    h = hashlib.sha256(b"p3-recovery-inventory-v1\x00")
    total = 0
    for r in records:
        if type(r) is not dict:
            raise GateError("invalid_proof")
        try:
            raw = json.dumps(
                r, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            ).encode()
        except (ValueError, TypeError, RecursionError):
            raise GateError("invalid_proof") from None
        if not 1 <= len(raw) <= 4096:
            raise GateError("invalid_proof")
        total += len(raw)
        if total > 65536:
            raise GateError("invalid_proof")
        h.update(len(raw).to_bytes(4, "big"))
        h.update(raw)
    return h.hexdigest()


def validate_proof(name: str, raw: bytes) -> dict[str, Any]:
    if name not in PROOF_FILES:
        raise GateError("invalid_proof")
    try:
        v = decode(raw, MAX_PROOF_BYTES)
        if (
            type(v.get("schema_version")) is not int
            or v.get("schema_version") != 1
            or v.get("status") != "passed"
        ):
            raise GateError("invalid_proof")
        if name == "recovery-lock.json":
            if (
                set(v)
                != {
                    "schema_version",
                    "status",
                    "owner_backend_pid",
                    "work_schema",
                    "query_visibility",
                    "lock_target",
                    "owned_writers",
                    "work_id",
                    "old_attempt_id",
                    "old_lease_until_ms",
                    "observed_db_clock_ms",
                    "waiters",
                    "graphs",
                }
                or type(v["query_visibility"]) is not str
                or v["query_visibility"] not in {"visible", "redacted"}
                or v["lock_target"] != "p1_work_admission"
                or not natural(v["owner_backend_pid"], 1, 2147483647)
                or not uuid_value(v["work_id"])
                or not uuid_value(v["old_attempt_id"])
                or not natural(v["old_lease_until_ms"], 1)
                or not natural(v["observed_db_clock_ms"], v["old_lease_until_ms"])
                or not exact_child(v["graphs"], 1)
                or type(v["waiters"]) is not list
                or len(v["waiters"]) != 2
            ):
                raise GateError("invalid_proof")
            if (
                type(v["work_schema"]) is not str
                or re.fullmatch(r"p1_work_recovery_[a-f0-9]{32}", v["work_schema"]) is None
                or type(v["owned_writers"]) is not list
                or len(v["owned_writers"]) != 2
            ):
                raise GateError("invalid_proof")
            writers = v["owned_writers"]
            for role, writer in zip(("race-a", "race-b"), writers, strict=True):
                if (
                    type(writer) is not dict
                    or set(writer) != {"role", "process_pid", "backend_pid"}
                    or writer["role"] != role
                    or not natural(writer["process_pid"], 1, 2147483647)
                    or not natural(writer["backend_pid"], 1, 2147483647)
                    or writer["backend_pid"] == v["owner_backend_pid"]
                ):
                    raise GateError("invalid_proof")
            if (
                len({w["process_pid"] for w in writers}) != 2
                or len({w["backend_pid"] for w in writers}) != 2
            ):
                raise GateError("invalid_proof")
            pids = []
            for w in v["waiters"]:
                if (
                    type(w) is not dict
                    or set(w) != {"pid", "blockers"}
                    or not natural(w["pid"], 1, 2147483647)
                    or w["pid"] == v["owner_backend_pid"]
                    or type(w["blockers"]) is not list
                    or not 1 <= len(w["blockers"]) <= 2
                    or any(not natural(i, 1, 2147483647) or i == w["pid"] for i in w["blockers"])
                    or len(set(w["blockers"])) != len(w["blockers"])
                ):
                    raise GateError("invalid_proof")
                pids.append(w["pid"])
            if (
                len(set(pids)) != 2
                or set(pids) != {w["backend_pid"] for w in writers}
                or any(
                    not set(w["blockers"]) <= {v["owner_backend_pid"], *pids} for w in v["waiters"]
                )
                or not any(v["owner_backend_pid"] in w["blockers"] for w in v["waiters"])
                or not any(set(w["blockers"]) & set(pids) for w in v["waiters"])
            ):
                raise GateError("invalid_proof")
        elif name == "recovery-peer.json":
            if (
                set(v) != {"schema_version", "status", "generations"}
                or type(v["generations"]) is not list
                or len(v["generations"]) != 2
            ):
                raise GateError("invalid_proof")
            labels = {
                "a": ("issued_recovery", "specialist_loss"),
                "b": (
                    "specialist_recovery",
                    "coordinator_loss",
                    "coordinator_recovery",
                    "result_precommit",
                    "result_precommit_recovery",
                    "result_postcommit",
                    "unknown_delivery",
                    "useful_current",
                ),
            }
            for generation, g in zip(("a", "b"), v["generations"], strict=True):
                if (
                    type(g) is not dict
                    or set(g)
                    != {
                        "schema_version",
                        "generation",
                        "node_version",
                        "status",
                        "counters",
                        "records",
                    }
                    or not exact_child(g["schema_version"], 1)
                    or g["generation"] != generation
                    or not core.supported_node(g["node_version"])
                    or g["status"] != ("running" if generation == "a" else "closed")
                ):
                    raise GateError("invalid_proof")
                c = g["counters"]
                expected = {
                    "invoked": 2 if generation == "a" else 8,
                    "strict_completed": 1 if generation == "a" else 7,
                    "cancel_requests": 0,
                    "disconnects": 0 if generation == "a" else 1,
                    "active": 1 if generation == "a" else 0,
                    "requests": 1 if generation == "a" else 0,
                    "sockets": 1 if generation == "a" else 0,
                }
                if (
                    not exact_child(c, expected)
                    or type(g["records"]) is not list
                    or len(g["records"]) != len(labels[generation])
                ):
                    raise GateError("invalid_proof")
                for label, r in zip(labels[generation], g["records"], strict=True):
                    keys = {
                        "label",
                        "scope",
                        "delegation_id",
                        "case_id",
                        "request_revision",
                        "attempt_id",
                        "input_fingerprint",
                        "request_sha256",
                        "started_at_ms",
                        "finished_at_ms",
                        "outcome",
                    }
                    comp = label in {"unknown_delivery", "useful_current"}
                    outcome = (
                        "running"
                        if label == "specialist_loss"
                        else "aborted"
                        if label == "coordinator_loss"
                        else "completed"
                    )
                    if (
                        type(r) is not dict
                        or set(r) != keys
                        or r["label"] != label
                        or not exact_child(
                            r["scope"],
                            {
                                "tenant_id": "tenant_recovery",
                                "account_id": "completion" if comp else "execution",
                            },
                        )
                        or type(r["delegation_id"]) is not str
                        or re.fullmatch(r"delegation_recovery_[iscuvgm]", r["delegation_id"])
                        is None
                        or r["case_id"] != ("case_completion" if comp else "case_execution")
                        or not exact_child(r["request_revision"], 2)
                        or type(r["attempt_id"]) is not str
                        or re.fullmatch(r"attempt_[a-f0-9]{32}", r["attempt_id"]) is None
                        or not hash_value(r["input_fingerprint"])
                        or not hash_value(r["request_sha256"])
                        or not natural(r["started_at_ms"], 1)
                        or r["outcome"] != outcome
                        or (outcome == "running" and r["finished_at_ms"] is not None)
                        or (
                            outcome != "running"
                            and not natural(r["finished_at_ms"], r["started_at_ms"])
                        )
                    ):
                        raise GateError("invalid_proof")
        else:
            keys = {
                "schema_version",
                "status",
                "counts",
                "records",
                "inventory_sha256",
                "gap",
                "processing",
                "exact_reconciliation",
            }
            if (
                set(v) != keys
                or not exact_child(v["counts"], EXPECTED_COUNTS)
                or v["exact_reconciliation"] is not True
                or not hash_value(v["inventory_sha256"])
                or type(v["records"]) is not list
                or len(v["records"]) != 29
                or inventory_digest(v["records"]) != v["inventory_sha256"]
            ):
                raise GateError("invalid_proof")
            variants = {
                "result": {
                    "kind",
                    "label",
                    "scope",
                    "work_id",
                    "request_sha256",
                    "attempt_id",
                    "command_id",
                    "owner_id",
                    "number",
                    "event_id",
                    "sequence",
                    "result_sha256",
                    "input_fingerprint",
                },
                "grant": {
                    "kind",
                    "work_id",
                    "attempt_id",
                    "tenant_id",
                    "account_id",
                    "command_id",
                    "owner_id",
                    "number",
                    "epoch",
                    "issued_at_ms",
                    "lease_until_ms",
                },
                "invoke": {"kind", "label", "attempt_id", "request_sha256", "outcome"},
                "completion": {
                    "kind",
                    "work_id",
                    "attempt_id",
                    "result_sha256",
                    "delivery_id",
                    "receipt_id",
                    "event_id",
                    "action_id",
                    "intent_id",
                    "effect_id",
                    "confirmation_sha256",
                    "supplier_result_sha256",
                    "business_event_id",
                },
            }
            sizes = {"result": 0, "grant": 0, "invoke": 0, "completion": 0}
            for r in v["records"]:
                if (
                    type(r) is not dict
                    or type(r.get("kind")) is not str
                    or r["kind"] not in variants
                    or set(r) != variants[r["kind"]]
                ):
                    raise GateError("invalid_proof")
                sizes[r["kind"]] += 1
                for k, x in r.items():
                    if k in {
                        "work_id",
                        "attempt_id",
                        "owner_id",
                        "event_id",
                        "delivery_id",
                        "receipt_id",
                        "action_id",
                        "intent_id",
                        "effect_id",
                        "business_event_id",
                    } and not uuid_value(x):
                        raise GateError("invalid_proof")
                    if (k.endswith("sha256") or k == "input_fingerprint") and not hash_value(x):
                        raise GateError("invalid_proof")
                if r["kind"] == "result":
                    comp = r["label"] in {"g", "m"}
                    if (
                        r["label"] not in tuple("iscuvgm")
                        or not exact_child(
                            r["scope"],
                            {
                                "tenant_id": "tenant_recovery",
                                "account_id": "completion" if comp else "execution",
                            },
                        )
                        or not natural(r["number"], 1, 2)
                        or not natural(r["sequence"], 1, 5)
                        or r["command_id"] != "recovery_" + r["label"] + "_" + str(r["number"])
                    ):
                        raise GateError("invalid_proof")
                if r["kind"] == "grant" and (
                    not natural(r["number"], 1, 2)
                    or not exact_child(r["epoch"], r["number"])
                    or not natural(r["issued_at_ms"], 1)
                    or not natural(r["lease_until_ms"], r["issued_at_ms"] + 1)
                    or r["tenant_id"] != "tenant_recovery"
                    or r["account_id"] not in {"execution", "completion"}
                    or type(r["command_id"]) is not str
                    or re.fullmatch(r"recovery_[iscuvgm]_[12]", r["command_id"]) is None
                ):
                    raise GateError("invalid_proof")
                if r["kind"] == "invoke" and (
                    type(r["label"]) is not str
                    or r["outcome"] not in {"running", "aborted", "completed"}
                ):
                    raise GateError("invalid_proof")
            if sizes != {"result": 7, "grant": 11, "invoke": 10, "completion": 1}:
                raise GateError("invalid_proof")
            gap = v["gap"]
            p = v["processing"]
            if (
                type(gap) is not dict
                or set(gap) != {"work_id", "sequence", "delivery_state", "acknowledged"}
                or not uuid_value(gap["work_id"])
                or not exact_child(gap["sequence"], 1)
                or gap["delivery_state"] != "unknown"
                or gap["acknowledged"] is not False
                or not exact_child(
                    p, {"terminal_watermark": 0, "terminal_count": 1, "scan_after": 1}
                )
            ):
                raise GateError("invalid_proof")
        return v
    except (GateError, KeyError, ValueError, TypeError, RecursionError, OverflowError):
        raise GateError("invalid_proof") from None


def validated_owned_lock(
    raw: bytes, *, work_schema: str, process_ids: tuple[int, int]
) -> dict[str, Any]:
    value = validate_proof("recovery-lock.json", raw)
    if (
        type(work_schema) is not str
        or value["work_schema"] != work_schema
        or type(process_ids) is not tuple
        or len(process_ids) != 2
        or any(not natural(pid, 1, 2147483647) for pid in process_ids)
        or len(set(process_ids)) != 2
        or [w["process_pid"] for w in value["owned_writers"]] != list(process_ids)
    ):
        raise GateError("invalid_proof")
    return value


def validate_proof_bundle(snapshots: dict[str, bytes]) -> None:
    if type(snapshots) is not dict or set(snapshots) != set(PROOF_FILES):
        raise GateError("invalid_proof")
    p = {n: validate_proof(n, raw) for n, raw in snapshots.items()}
    rows = p["recovery-authority.json"]["records"]
    results = {r["label"]: r for r in rows if r["kind"] == "result"}
    grants = {r["command_id"]: r for r in rows if r["kind"] == "grant"}
    invokes = {r["label"]: r for r in rows if r["kind"] == "invoke"}
    if (
        set(results) != set("iscuvgm")
        or len(grants) != 11
        or len(invokes) != 10
        or set(grants)
        != {
            "recovery_" + l + "_" + str(n)
            for l in "iscuvgm"
            for n in range(1, 2 if l in "vgm" else 3)
        }
        or len({g["attempt_id"] for g in grants.values()}) != 11
        or len({r["work_id"] for r in results.values()}) != 7
        or len({r["event_id"] for r in results.values()}) != 7
    ):
        raise GateError("invalid_proof")
    lock = p["recovery-lock.json"]
    old = grants["recovery_i_1"]
    if (
        lock["work_id"] != old["work_id"]
        or lock["old_attempt_id"] != old["attempt_id"]
        or lock["old_lease_until_ms"] != old["lease_until_ms"]
    ):
        raise GateError("invalid_proof")
    for r in results.values():
        g = grants.get(r["command_id"])
        if (
            g is None
            or any(r[k] != g[k] for k in ("work_id", "attempt_id", "owner_id", "number"))
            or g["tenant_id"] != r["scope"]["tenant_id"]
            or g["account_id"] != r["scope"]["account_id"]
        ):
            raise GateError("invalid_proof")
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
    if set(invokes) != set(mapping):
        raise GateError("invalid_proof")
    for account, expected_sequences in (("execution", set(range(1, 6))), ("completion", {1, 2})):
        if {
            r["sequence"] for r in results.values() if r["scope"]["account_id"] == account
        } != expected_sequences:
            raise GateError("invalid_proof")
    for generation in p["recovery-peer.json"]["generations"]:
        for r in generation["records"]:
            a = invokes.get(r["label"])
            label, number = mapping[r["label"]]
            g = grants["recovery_" + label + "_" + str(number)]
            if (
                a is None
                or a["attempt_id"] != g["attempt_id"]
                or r["delegation_id"] != "delegation_recovery_" + label
                or r["scope"] != results[label]["scope"]
                or r["input_fingerprint"] != results[label]["input_fingerprint"]
                or a is None
                or r["attempt_id"] != "attempt_" + UUID(a["attempt_id"]).hex
                or r["request_sha256"] != a["request_sha256"]
                or r["outcome"] != a["outcome"]
            ):
                raise GateError("invalid_proof")
    if p["recovery-authority.json"]["gap"]["work_id"] != results["g"]["work_id"]:
        raise GateError("invalid_proof")
    completion = next(r for r in rows if r["kind"] == "completion")
    if any(
        completion[k] != results["m"][k]
        for k in ("work_id", "attempt_id", "result_sha256", "event_id")
    ):
        raise GateError("invalid_proof")


def retain_proofs(root: Path, target: Path, work: Path) -> dict[str, Any]:
    snaps = {n: bounded_read(work / n, MAX_PROOF_BYTES) for n in PROOF_FILES}
    validate_proof_bundle(snaps)
    out = target.with_name(target.stem + "-artifacts")
    if out.exists() or out.is_symlink():
        raise GateError("existing_proof")
    out.mkdir(mode=0o700)
    manifest = {}
    for n, raw in snaps.items():
        with os.fdopen(
            os.open(out / n, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600), "wb"
        ) as stream:
            stream.write(raw)
        manifest[n] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    write_json(
        out / "manifest.json",
        {
            "schema_version": 1,
            "status": "passed",
            "records": [{"path": n, **v} for n, v in manifest.items()],
        },
    )
    return manifest


class Children:
    def __init__(self, work: Path, deadline: float) -> None:
        self.work, self.deadline = work, deadline
        self.count = 0
        self.budget = core.CaptureBudget()
        self.all: list[OwnedProcess] = []
        self.outputs: set[str] = set()
        self.first_failure: dict[str, Any] | None = None
        self.first_observation: dict[str, Any] | None = None

    def start(self, label: str, args: list[str], env: dict[str, str], *, cwd: Path) -> OwnedProcess:
        if self.count >= 32 or label in self.outputs:
            raise GateError("child_budget")
        self.outputs.add(label)
        self.count += 1
        limit = self.budget.reserve(4096)
        assert limit == MAX_STREAM_BYTES
        child = OwnedProcess(
            args, cwd=cwd, env=env, output_directory=self.work / label, max_output_bytes=limit
        )
        self.all.append(child)
        return child

    def remember(
        self, child: OwnedProcess, *, operation: str, barrier: str | None, kind: str
    ) -> None:
        if self.first_observation is not None:
            return
        self.first_observation = {
            "child": child.output_directory.name,
            "operation": operation,
            "barrier": barrier,
            "kind": kind,
            "process_pid": child.pid,
            "returncode": child.returncode,
        }
        if child.returncode is not None:
            try:
                remaining = self.deadline - time.monotonic()
                if remaining > 0:
                    child.wait(timeout=min(0.25, remaining))
                out, _ = self.budget.read(child.output_directory, MAX_STREAM_BYTES)
                self.first_failure = validated_failure(out, child.output_directory.name)
            except Exception:  # noqa: BLE001 - diagnostic capture cannot mask primary process failure.
                self.first_failure = None

    def wait(self, child: OwnedProcess, barrier: FileBarrier, name: str) -> None:
        try:
            child.wait_for_barrier(barrier, timeout=min(15, core.remaining(self.deadline)))
        except ProcessControlError as error:
            self.remember(
                child,
                operation="wait",
                barrier=name,
                kind="exited"
                if isinstance(error, ProcessExited)
                else "timeout"
                if isinstance(error, ProcessTimeout)
                else "control_error",
            )
            raise

    def finish(
        self, child: OwnedProcess, *, zero: bool = True, deadline: float | None = None
    ) -> bytes:
        try:
            r = child.wait(timeout=core.remaining(deadline or self.deadline))
        except ProcessControlError as error:
            self.remember(
                child,
                operation="finish",
                barrier=None,
                kind="exited"
                if isinstance(error, ProcessExited)
                else "timeout"
                if isinstance(error, ProcessTimeout)
                else "control_error",
            )
            raise
        out, err = self.budget.read(child.output_directory, MAX_STREAM_BYTES)
        if child.cleanup_failed or (zero and r.returncode != 0) or err:
            self.remember(
                child,
                operation="finish",
                barrier=None,
                kind="exited" if r.returncode != 0 else "control_error",
            )
            raise GateError("runner_failed_" + child.output_directory.name)
        return out

    def kill(self, child: OwnedProcess) -> None:
        try:
            r = child.kill(timeout=min(3, core.remaining(self.deadline)))
        except ProcessControlError as error:
            self.remember(
                child,
                operation="kill",
                barrier=None,
                kind="exited"
                if isinstance(error, ProcessExited)
                else "timeout"
                if isinstance(error, ProcessTimeout)
                else "control_error",
            )
            raise
        out, err = self.budget.read(child.output_directory, MAX_STREAM_BYTES)
        if not r.killed or r.returncode != -9 or child.cleanup_failed or out or err:
            self.remember(child, operation="kill", barrier=None, kind="control_error")
            raise GateError("crash_not_observed")

    def close(self) -> None:
        failed = False
        for p in reversed(self.all):
            try:
                p.close()
                failed |= p.cleanup_failed or p.returncode is None
            except Exception:  # noqa: BLE001 - closed process/diagnostic boundary; never reflect details.
                failed = True
        if failed:
            raise GateError("cleanup_incomplete")


def retain_parent_context(target: Path, owned: Children) -> bool:
    if owned.first_observation is None:
        return False
    try:
        context = validated_parent_failure(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "failed",
                    "diagnostic_only": True,
                    "parent_observation": owned.first_observation,
                    "child_failure": owned.first_failure,
                }
            ).encode()
        )
        write_json(target.with_name(target.stem + "-diagnostic.json"), context, maximum=2048)
        return True
    except Exception:  # noqa: BLE001 - secondary diagnostic sink must preserve first failure and cleanup.
        return False


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Retain fixed body-free failure context; never qualifies.",
    )
    args = parser.parse_args(argv)
    began = time.monotonic()
    final = began + 180
    deadline = final - 15
    clean = False
    target: Path | None = None
    owned: Children | None = None
    try:
        target = target_path(
            root, args.report or Path(".local/validation/p3-recovery/" + uuid4().hex + ".json")
        )
        proof = target.with_name(target.stem + "-artifacts")
        if proof.exists() or proof.is_symlink():
            raise GateError("existing_proof")
        setup = core.load_setup(root)
        try:
            values = setup.load_settings()
        except setup.SetupError:
            raise GateError("missing_setup") from None
        node = shutil.which("node")
        python = root / ".venv/bin/python"
        project = root / "projects/delegation-reliability/specialist-ts"
        script = root / "projects/delegation-reliability/tests/pg_recovery_cases.py"
        peer_script = project / "tests/fixtures/recovery-server.mjs"
        compiler = project / "node_modules/typescript/bin/tsc"
        if not node or not all(p.is_file() for p in (python, script, peer_script, compiler)):
            raise GateError("missing_setup")
        scratch = root / ".local/p3-recovery-check"
        core.private_directory(scratch)
        with tempfile.TemporaryDirectory(prefix="run-", dir=scratch) as temporary:
            work = Path(temporary)
            owned = Children(work, deadline)
            barriers = {
                name: FileBarrier(work, name)
                for name in {
                    *BARRIERS.values(),
                    "peer_a",
                    "peer_b",
                    "specialist_http_started",
                    "coordinator_remote_started",
                }
            }
            context = {
                "P3_RECOVERY_WORK_SCHEMA": "p1_work_recovery_" + uuid4().hex,
                "P3_RECOVERY_CASE_SCHEMA": "p3_completion_" + uuid4().hex,
                "P3_RECOVERY_PROJECTION_SCHEMA": "p3_projection_recovery_" + uuid4().hex,
                "P3_RECOVERY_DIRECTORY": str(work),
                "P3_RECOVERY_EXECUTION_TOKEN": secrets.token_urlsafe(32),
                "P3_RECOVERY_COMPLETION_TOKEN": secrets.token_urlsafe(32),
                "P3_RECOVERY_NODE_TOKEN": secrets.token_urlsafe(32),
                "P3_RECOVERY_ENDPOINT_FILE": str(work / "endpoint-a.json"),
            }
            seen: set[str] = set()
            launched: set[str] = set()
            kills = 0
            graphs = 0
            version = ""
            b_peer: OwnedProcess | None = None
            installed = False

            def start(mode: str) -> OwnedProcess:
                if mode in launched or mode not in MODE_KEYS:
                    raise GateError("invalid_child_mode")
                launched.add(mode)
                if mode in BARRIERS:
                    context["P3_RECOVERY_BARRIER"] = str(work / (BARRIERS[mode] + ".reached"))
                return owned.start(
                    mode,
                    [str(python), "-I", str(script), mode],
                    child_environment(values, mode=mode, context=context),
                    cwd=work,
                )

            def collect(mode: str, child: OwnedProcess) -> None:
                value = validated_stage(
                    owned.finish(child, deadline=final if mode == "cleanup" else deadline), mode
                )
                for name in value["cases"]:
                    if name in seen:
                        raise GateError("duplicate_case")
                    seen.add(name)

            def expect(mode: str) -> None:
                collect(mode, start(mode))

            def wait(child: OwnedProcess, name: str) -> None:
                owned.wait(child, barriers[name], name)

            def kill_at(mode: str) -> None:
                nonlocal kills
                p = start(mode)
                wait(p, BARRIERS[mode])
                owned.kill(p)
                kills += 1

            def start_peer(generation: str) -> OwnedProcess:
                nonlocal version
                env = {
                    **core.base_environment(),
                    "P3_RECOVERY_NODE_TOKEN": context["P3_RECOVERY_NODE_TOKEN"],
                    "P3_RECOVERY_DIRECTORY": str(work),
                    "P3_RECOVERY_GENERATION": generation,
                    "P3_RECOVERY_ENDPOINT_FILE": str(work / ("endpoint-" + generation + ".json")),
                    "P3_RECOVERY_READY": str(work / ("peer_" + generation + ".reached")),
                    "P3_RECOVERY_STOP": str(work / ("stop-" + generation)),
                }
                p = owned.start("server-" + generation, [node, str(peer_script)], env, cwd=work)
                wait(p, "peer_" + generation)
                point = decode(bounded_read(work / ("endpoint-" + generation + ".json"), 256), 256)
                if (
                    set(point) != {"schema_version", "generation", "host", "port", "node_version"}
                    or not exact_child(point["schema_version"], 1)
                    or point["generation"] != generation
                    or point["host"] != "127.0.0.1"
                    or not natural(point["port"], 1024, 65535)
                    or not core.supported_node(point["node_version"])
                ):
                    raise GateError("invalid_endpoint")
                version = point["node_version"]
                context["P3_RECOVERY_ENDPOINT_FILE"] = env["P3_RECOVERY_ENDPOINT_FILE"]
                return p

            try:
                compile_child = owned.start(
                    "compile",
                    [node, str(compiler), "--project", str(project / "tsconfig.json")],
                    core.base_environment(),
                    cwd=project,
                )
                owned.finish(compile_child)
                installed = True
                expect("install")
                a_peer = start_peer("a")
                kill_at("issued-crash")
                expect("issued-replay")
                a, b = start("race-a"), start("race-b")
                wait(a, "race_a_ready")
                wait(b, "race_b_ready")
                locker = start("race-locker")
                wait(locker, "recovery_race")
                a.release_barrier(barriers["race_a_ready"])
                b.release_barrier(barriers["race_b_ready"])
                collect("race-locker", locker)
                validated_owned_lock(
                    bounded_read(work / "recovery-lock.json", MAX_PROOF_BYTES),
                    work_schema=context["P3_RECOVERY_WORK_SCHEMA"],
                    process_ids=(a.pid, b.pid),
                )
                graphs += 1
                collect("race-a", a)
                collect("race-b", b)
                expect("race-verify")
                loss = start("specialist-loss")
                wait(a_peer, "specialist_http_started")
                owned.kill(a_peer)
                kills += 1
                collect("specialist-loss", loss)
                b_peer = start_peer("b")
                expect("specialist-resume")
                coordinator = start("coordinator-crash")
                wait(coordinator, "coordinator_http_started")
                wait(b_peer, "coordinator_remote_started")
                owned.kill(coordinator)
                kills += 1
                expect("coordinator-resume")
                kill_at("result-before-crash")
                expect("result-before-resume")
                kill_at("result-after-crash")
                expect("result-after-resume")
                kill_at("delivery-begin-crash")
                expect("unknown-resume")
                kill_at("receiver-crash")
                expect("receiver-resume")
                expect("processing-replay")
                kill_at("action-crash")
                expect("action-resume")
                expect("conflicts")
                expect("owner-check")
                with os.fdopen(
                    os.open(
                        work / "stop-b", os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
                    ),
                    "w",
                ) as out:
                    out.write(str(b_peer.pid) + "\n")
                peer = decode(owned.finish(b_peer))
                wanted = {
                    "schema_version": 1,
                    "status": "passed",
                    "generation": "b",
                    "cleanup_complete": True,
                    "node_version": version,
                    "invocations": 8,
                    "strict_completed": 7,
                    "active": 0,
                    "requests": 0,
                    "sockets": 0,
                }
                if not exact_child(peer, wanted):
                    raise GateError("invalid_peer_report")
                write_json(
                    work / "recovery-peer.json",
                    {
                        "schema_version": 1,
                        "status": "passed",
                        "generations": [
                            decode(
                                bounded_read(
                                    work / ("recovery-peer-" + g + ".json"), MAX_PROOF_BYTES
                                )
                            )
                            for g in ("a", "b")
                        ],
                    },
                )
                if kills != 8 or graphs != 1 or seen != set(CASE_NAMES):
                    raise GateError("invalid_report")
            finally:
                primary = sys.exception()
                failed = False
                owned.deadline = final
                try:
                    owned.close()
                except Exception:  # noqa: BLE001 - closed process/diagnostic boundary; never reflect details.
                    failed = True
                if installed:
                    try:
                        expect("cleanup")
                        owned.close()
                    except Exception:
                        failed = True
                        if primary is None:
                            raise
                clean = not failed
                if primary is None and failed:
                    raise GateError("cleanup_incomplete")
            if not clean or launched != set(MODE_ORDER) or owned.count != 28:
                raise GateError("invalid_report")
            if args.diagnostic:
                raise GateError("diagnostic_not_qualification")
            proofs = retain_proofs(root, target, work)
            report = validated_report(
                json.dumps(
                    {
                        **SUCCESS,
                        "duration_seconds": time.monotonic() - began,
                        "child_commands": owned.count,
                        "node_version": version,
                        "proofs": proofs,
                    }
                ).encode()
            )
        write_json(target, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    except GateError as error:
        code = error.code
    except ProcessControlError:
        code = "runner_failed"
    except Exception:  # noqa: BLE001 - closed process/diagnostic boundary; never reflect details.
        code = "gate_failed"
    failure = {
        "schema_version": 1,
        "status": "failed",
        "mode": MODE,
        "code": code,
        "duration_seconds": time.monotonic() - began,
        "cleanup_complete": clean,
    }
    if args.diagnostic:
        failure["diagnostic"] = True
    if args.diagnostic or (owned is not None and owned.first_observation is not None):
        failure["diagnostic_retained"] = (
            target is not None and owned is not None and retain_parent_context(target, owned)
        )
    if target is not None:
        try:
            write_json(target, failure)
        except (OSError, GateError):
            pass
    print(json.dumps(failure, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
