"""Explicit real-store P1 acceptance assertions with prerequisite-aware reporting.

Host tooling only: test modules use isolated synthetic state and migration roles.
The generic harness receives a closed numeric report, never credentials/tracebacks.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import unittest
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Exact assertion IDs, rather than broad suites or a count inferred from logs.
CASES: dict[str, tuple[str, ...]] = {
    "P1-06": (
        "pg_mutation_cases.PostgresMutationCases.test_normal_inquiry_confirmation_and_separate_mutation_process_preserve_identity",
        "pg_case_cases.PostgresCaseCases.test_valid_exact_confirmation_commits_one_immutable_intent_effect_and_dispatch",
    ),
    "P1-07": (
        "pg_mutation_cases.PostgresMutationCases.test_absent_altered_stale_and_expired_confirmation_make_zero_supplier_apply_calls",
        "pg_case_cases.PostgresCaseCases.test_every_changed_quote_field_rejects_before_any_commit_then_valid_work_progresses",
        "pg_case_cases.PostgresCaseCases.test_expiry_boundary_is_checked_after_lock_admission",
    ),
    "P1-08": (
        "pg_mutation_cases.PostgresMutationCases.test_sigkill_after_supplier_commit_reconciles_original_effect_without_second_apply",
        "pg_mutation_cases.PostgresMutationCases.test_os_exit_after_supplier_commit_reopens_and_recovers_one_effect",
        "pg_mutation_cases.PostgresMutationCases.test_normal_inquiry_confirmation_and_separate_mutation_process_preserve_identity",
    ),
    "P1-09": (
        "pg_mutation_cases.PostgresMutationCases.test_noncooperating_ambiguous_success_is_uncertain_and_never_blindly_resent",
        "pg_mutation_cases.PostgresMutationCases.test_noncooperating_reserved_but_uncalled_crash_stays_uncertain_without_resend",
        "pg_coordination_cases.PostgresCoordinationCases.test_paused_old_call_without_cooperation_remains_uncertain",
    ),
    "P1-10": (
        "pg_lifecycle_cases.PostgresLifecycleCases.test_actual_process_retains_early_signal_and_wait_then_new_process_advances",
        "pg_lifecycle_cases.PostgresLifecycleCases.test_late_signal_concurrent_consumers_commit_one_intent_and_dispatch",
        "pg_lifecycle_cases.PostgresLifecycleCases.test_actual_process_restart_preserves_deadline_and_rejects_expired_wait_signal",
        "pg_lifecycle_cases.PostgresLifecycleCases.test_wait_deadline_is_effective_after_restart_even_with_received_signal",
    ),
    "P1-11": (
        "pg_lifecycle_cases.PostgresLifecycleCases.test_signal_replay_conflict_and_unrelated_quote_cannot_advance",
        "pg_lifecycle_cases.PostgresLifecycleCases.test_lost_signal_and_advance_acknowledgement_replay_original_receipts",
        "pg_lifecycle_cases.PostgresLifecycleCases.test_signal_capacity_rejects_new_receipts_but_preserves_replay_and_progress",
    ),
    "P1-12": (
        "pg_lifecycle_cases.PostgresLifecycleCases.test_transient_predispatch_retries_only_when_due_then_makes_useful_progress",
        "pg_lifecycle_cases.PostgresLifecycleCases.test_permanent_rejection_and_retry_exhaustion_stop_with_finite_attempts",
        "pg_lifecycle_cases.PostgresLifecycleCases.test_deadline_prevents_dispatch_without_inventing_an_attempt",
        "pg_lifecycle_cases.PostgresLifecycleCases.test_ambiguous_dispatch_remains_uncertain_and_never_resends",
    ),
    "P1-13": (
        "pg_effect_cases.PostgresEffectCases.test_cancel_before_commit_is_idempotent_and_prevents_confirmation",
        "pg_effect_cases.PostgresEffectCases.test_confirmation_and_cancel_transaction_winner_has_one_truthful_completion",
        "pg_mutation_cases.PostgresMutationCases.test_cancellation_before_dispatch_prevents_supplier_call",
    ),
    "P1-15": (
        "pg_lease_cases.PostgresLeaseCases.test_two_independent_processes_cannot_acquire_same_unexpired_workflow",
        "pg_lease_cases.PostgresLeaseCases.test_paused_independent_process_loses_local_write_authority_after_takeover",
        "pg_lease_cases.PostgresLeaseCases.test_acquisition_rollback_and_lost_ack_preserve_one_original_epoch",
        "pg_lease_cases.PostgresLeaseCases.test_renew_and_release_rollback_and_ack_loss_do_not_reset_epoch",
        "pg_coordination_cases.PostgresCoordinationCases.test_paused_old_external_call_after_takeover_is_cooperatively_deduplicated",
        "pg_coordination_cases.PostgresCoordinationCases.test_paused_old_call_without_cooperation_remains_uncertain",
        "pg_coordination_cases.PostgresCoordinationCases.test_known_supplier_success_reconciles_after_epoch_takeover_and_rejects_old_ack",
    ),
    "P1-16": (
        "pg_release_acceptance_cases.PostgresCompletionCommitCases.test_completion_commit_process_loss_before_first_delivery_retains_one_event",
        "pg_effect_cases.PostgresEffectCases.test_actual_process_loss_after_receiver_commit_replays_one_stable_event",
        "pg_effect_cases.PostgresEffectCases.test_success_keeps_original_workflow_distinct_ids_and_one_atomic_completion",
    ),
    "P1-17": (
        "pg_store_cases.PostgresStoreCases.test_authenticated_scope_blocks_forged_overrides_and_cross_scope_history_or_cancel",
        "pg_case_cases.PostgresCaseCases.test_scope_and_owner_are_checked_before_any_detailed_disclosure",
        "pg_lifecycle_cases.PostgresLifecycleCases.test_cross_scope_wait_signal_and_history_are_unavailable_without_mutation",
        "pg_effect_cases.PostgresEffectCases.test_cancel_scope_owner_conflicts_and_capacity_replay_are_explicit",
        "pg_conversation_cases.PostgresConversationCases.test_projection_owner_check_precedes_malformed_cursor_and_history_reads",
    ),
    "P1-19": (
        "test_migrations.MigrationTests.test_existing_m1_upgrades_with_stable_id_payload_and_effect",
        "test_migrations.MigrationTests.test_interrupted_ddl_and_precommit_failures_roll_back_old_data",
        "test_migrations.MigrationTests.test_abrupt_process_exit_before_commit_recovers_original_intake",
        "test_migrations.MigrationTests.test_backup_includes_committed_wal_and_can_be_restored_with_sqlite_api",
        "pg_cutover_cases.PostgresCutoverTests.test_complete_cutover_preserves_all_state_and_retry_keeps_runtime_progress",
        "pg_cutover_cases.PostgresCutoverTests.test_process_exit_at_each_checkpoint_recovers_without_python_cleanup",
        "pg_cutover_cases.PostgresCutoverTests.test_retained_backup_is_restorable_as_original_v1_without_touching_target",
        "pg_upgrade_cases.PostgresUpgradeTests.test_populated_v1_upgrade_preserves_original_rows_receipt_and_inquiry_progress",
        "pg_upgrade_cases.PostgresUpgradeTests.test_actual_child_loss_at_each_checkpoint_preserves_atomic_version_and_data",
        "pg_upgrade_v3_cases.PostgresUpgradeV3Cases.test_populated_v2_upgrade_preserves_exact_legacy_data_and_historical_receipt",
        "pg_upgrade_v3_cases.PostgresUpgradeV3Cases.test_actual_child_exit_at_all_three_upgrade_checkpoints_is_atomic",
        "pg_upgrade_v4_cases.PostgresUpgradeV4Cases.test_populated_v3_upgrade_preserves_exact_prior_data_and_historical_receipt",
        "pg_upgrade_v4_cases.PostgresUpgradeV4Cases.test_actual_child_exit_at_all_three_upgrade_checkpoints_is_atomic",
        "pg_store_cases.PostgresStoreCases.test_sqlite_and_postgres_share_identical_core_snapshots_and_fixed_events",
    ),
}


class SetupRequired(ValueError):
    """Required private local configuration is unavailable."""


class MappingInvalid(ValueError):
    """A required exact assertion cannot be loaded."""


def load_settings(root: Path) -> Mapping[str, str]:
    spec = importlib.util.spec_from_file_location(
        "p1_acceptance_setup", root / "local-setup/stack.py"
    )
    if spec is None or spec.loader is None:
        raise SetupRequired("Required setup unavailable")
    stack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stack)
    try:
        return stack.load_settings(root / "local-setup")  # type: ignore[no-any-return]
    except (OSError, ValueError) as error:
        raise SetupRequired("Required setup unavailable") from error


@contextmanager
def configured_environment(values: Mapping[str, str]) -> Iterator[None]:
    fields = ("POSTGRES_PORT", "POSTGRES_PASSWORD", "POSTGRES_MIGRATION_PASSWORD")
    if any(type(values.get(key)) is not str for key in fields):
        raise SetupRequired("Required setup unavailable")
    port = values["POSTGRES_PORT"]
    passwords = (values["POSTGRES_PASSWORD"], values["POSTGRES_MIGRATION_PASSWORD"])
    if (
        not port.isascii()
        or not port.isdecimal()
        or not 1 <= int(port) <= 65535
        or any(
            not 16 <= len(value) <= 256 or any(c in value for c in "\0\r\n") for value in passwords
        )
    ):
        raise SetupRequired("Required setup unavailable")
    original = {key: value for key, value in os.environ.items() if key.startswith(("P1_", "PG"))}
    try:
        for key in original:
            os.environ.pop(key)
        for prefix, user, password in (
            ("P1_POSTGRES_", "livekit_lab", passwords[0]),
            ("P1_MIGRATION_", "continuity_migrator", passwords[1]),
        ):
            os.environ.update(
                {
                    prefix + "HOST": "127.0.0.1",
                    prefix + "PORT": port,
                    prefix + "DB": "livekit_lab",
                    prefix + "USER": user,
                    prefix + "PASSWORD": password,
                    prefix + "SCHEMA": "continuity",
                }
            )
        os.environ["P1_RUN_POSTGRES_TESTS"] = "1"
        yield
    finally:
        for key in tuple(os.environ):
            if key.startswith(("P1_", "PG")):
                os.environ.pop(key)
        os.environ.update(original)


@contextmanager
def test_imports(root: Path) -> Iterator[None]:
    original = list(sys.path)
    try:
        sys.path[:0] = [str(root / "tests"), str(root / "tests/postgres")]
        yield
    finally:
        sys.path[:] = original


ErrorInfo = (
    tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None]
)


class SafeResult(unittest.TestResult):
    """Count failures without formatting or retaining arbitrary exception text."""

    def addError(self, test: unittest.TestCase, err: ErrorInfo) -> None:
        self.errors.append((test, "test_error"))
        if self.failfast:
            self.stop()

    def addFailure(self, test: unittest.TestCase, err: ErrorInfo) -> None:
        self.failures.append((test, "assertion_failed"))
        if self.failfast:
            self.stop()

    def addExpectedFailure(self, test: unittest.TestCase, err: ErrorInfo) -> None:
        self.expectedFailures.append((test, "required_assertion_not_passed"))

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        self.skipped.append((test, "required_assertion_not_executed"))

    def addSubTest(
        self, test: unittest.TestCase, subtest: unittest.TestCase, err: ErrorInfo | None
    ) -> None:
        if err is not None:
            if err[0] is not None and issubclass(err[0], test.failureException):
                self.addFailure(subtest, err)
            else:
                self.addError(subtest, err)


def load_suite(case_id: str, root: Path) -> unittest.TestSuite:
    if case_id not in CASES:
        raise MappingInvalid("Unknown acceptance case")
    loader = unittest.TestLoader()
    with test_imports(root):
        suite = loader.loadTestsFromNames(list(CASES[case_id]))
    if loader.errors or suite.countTestCases() != len(CASES[case_id]):
        raise MappingInvalid("Required assertions unavailable")
    return suite


def run_case(
    case_id: str,
    *,
    root: Path = ROOT,
    settings_loader: Callable[[Path], Mapping[str, str]] = load_settings,
    suite_loader: Callable[[str, Path], unittest.TestSuite] = load_suite,
) -> tuple[dict[str, Any], int]:
    started = time.monotonic()
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "caseId": case_id,
        "mode": "lab",
        "status": "failed",
        "testCount": 0,
        "skippedCount": 0,
        "failureCount": 0,
        "errorCount": 0,
        "durationSeconds": 0.0,
        "code": "mapping_invalid",
    }
    exit_code = 1
    if case_id not in CASES:
        return report, exit_code
    try:
        with configured_environment(settings_loader(root)), test_imports(root):
            suite = suite_loader(case_id, root)
            if suite.countTestCases() != len(CASES[case_id]):
                raise MappingInvalid("Required assertion count mismatch")
            result = SafeResult()
            suite.run(result)
        report.update(
            testCount=result.testsRun,
            skippedCount=len(result.skipped) + len(result.expectedFailures),
            failureCount=len(result.failures) + len(result.unexpectedSuccesses),
            errorCount=len(result.errors),
        )
        if report["testCount"] == 0:
            report["code"] = "no_tests"
        elif report["skippedCount"]:
            report.update(status="incomplete", code="skipped")
            exit_code = 2
        elif report["errorCount"]:
            report["code"] = "test_error"
        elif report["failureCount"]:
            report["code"] = "assertion_failed"
        else:
            report.update(status="passed", code="passed")
            exit_code = 0
    except SetupRequired:
        report.update(status="incomplete", code="setup_required")
        exit_code = 2
    except MappingInvalid:
        pass
    except Exception:  # noqa: BLE001 - CLI containment never serializes private dependency failures
        report.update(code="test_error", errorCount=1)
    report["durationSeconds"] = round(time.monotonic() - started, 6)
    return report, exit_code


def publish(path: Path, report: Mapping[str, Any]) -> None:
    # The generic harness supplies a new path in its private temporary directory.
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "w"
    ) as stream:
        json.dump(report, stream, allow_nan=False, separators=(",", ":"))
        stream.write("\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, choices=tuple(CASES))
    parser.add_argument("--report", required=True, type=Path)
    arguments = parser.parse_args(argv)
    report, code = run_case(arguments.case)
    try:
        publish(arguments.report, report)
    except (OSError, TypeError, ValueError):
        print('{"event":"acceptance_report_error","code":"report_unavailable"}')
        return 1
    print(json.dumps(report, allow_nan=False, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
