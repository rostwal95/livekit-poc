"""Explicit real-PostgreSQL gate using private local setup credentials.

Run with the project interpreter. This command never starts/resets the stack,
rotates credentials, or silently skips an unavailable database. Tests create and
remove only their own isolated schemas and synthetic files.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        "postgres_gate_setup", ROOT / "local-setup/stack.py"
    )
    if spec is None or spec.loader is None:
        print('{"status":"failed","code":"postgres_setup_missing"}')
        return 2
    stack = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stack)
    try:
        values = stack.load_settings()
    except stack.SetupError:
        print(
            '{"status":"failed","code":"postgres_setup_required","action":"init_start_prepare_postgres"}'
        )
        return 2
    # Ambient developer credentials/target selectors cannot redirect this lane.
    for key in list(os.environ):
        if key.startswith(("P1_", "PG")):
            os.environ.pop(key)
    for prefix, user, password in (
        ("P1_POSTGRES_", "livekit_lab", values["POSTGRES_PASSWORD"]),
        ("P1_MIGRATION_", "continuity_migrator", values["POSTGRES_MIGRATION_PASSWORD"]),
    ):
        os.environ.update(
            {
                prefix + "HOST": "127.0.0.1",
                prefix + "PORT": values["POSTGRES_PORT"],
                prefix + "DB": "livekit_lab",
                prefix + "USER": user,
                prefix + "PASSWORD": password,
                prefix + "SCHEMA": "continuity",
            }
        )
    os.environ["P1_RUN_POSTGRES_TESTS"] = "1"
    required = {
        "pg_store_cases.py",
        "pg_readonly_work_cases.py",
        "pg_issued_execution_cases.py",
        "pg_result_delivery_cases.py",
        "pg_result_feed_cases.py",
        "pg_guarded_action_cases.py",
        "pg_migration_cases.py",
        "pg_cutover_cases.py",
        "pg_upgrade_cases.py",
        "pg_case_cases.py",
        "pg_lifecycle_cases.py",
        "pg_upgrade_v3_cases.py",
        "pg_phase_e_boundary_cases.py",
        "pg_mutation_cases.py",
        "pg_effect_cases.py",
        "pg_upgrade_v4_cases.py",
        "pg_upgrade_v5_cases.py",
        "pg_lease_cases.py",
        "pg_coordination_cases.py",
        "pg_conversation_cases.py",
    }
    if not all((ROOT / "tests/postgres" / name).is_file() for name in required):
        print('{"status":"failed","code":"postgres_suite_missing"}')
        return 2
    started = time.monotonic()
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests/postgres"), pattern="pg_*_cases.py"
    )
    count = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = count > 0 and result.wasSuccessful() and not result.skipped
    report = {
        "status": "passed" if passed else "failed",
        "backend": "postgres",
        "mode": "local_synthetic",
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
