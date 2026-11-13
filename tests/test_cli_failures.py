"""Public CLI boundaries never render private arguments or defect exception data."""

import io
import json
import logging
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from continuity_lab import execution_cli, inquiry_worker
from continuity_lab.execution_cli import _SafeFormatter
from continuity_lab.migrations import migrate
from continuity_lab.supplier import initialize_supplier


class PrivateFailure(RuntimeError):
    def __str__(self):
        raise AssertionError("Private exception text must not be read")

    def __repr__(self):
        raise AssertionError("Private exception representation must not be read")


class CliFailureTests(unittest.TestCase):
    def assert_safe_defect(self, result, output, records):
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output)["code"], "unexpected_error")
        rendered = "\n".join(_SafeFormatter().format(record) for record in records)
        self.assertNotIn("SECRET_SENTINEL", output + rendered)
        self.assertNotIn("Traceback", output + rendered)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].levelno, logging.ERROR)

    def test_malformed_cli_arguments_do_not_reflect_private_values(self):
        commands = (
            (
                "continuity_lab.execution_cli",
                [
                    "--db",
                    "SECRET_SENTINEL",
                    "submit",
                    "--scope",
                    "a",
                    "--key",
                    "one",
                    "--booking",
                    "DEMO-BK-001",
                    "--check-in",
                    "SECRET_SENTINEL",
                    "--confirm",
                ],
            ),
            (
                "continuity_lab.inquiry_worker",
                ["--db", "SECRET_SENTINEL", "--supplier-db", "SECRET_SENTINEL", "--scope"],
            ),
            (
                "continuity_lab.supplier",
                [
                    "--db",
                    "SECRET_SENTINEL",
                    "init",
                    "--scope",
                    "a",
                    "--check-in",
                    "SECRET_SENTINEL",
                ],
            ),
        )
        root = Path(__file__).resolve().parents[1]
        for module, arguments in commands:
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, "-m", module, *arguments],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("SECRET_SENTINEL", result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_execution_cli_unexpected_defect_is_safe_and_nonzero(self):
        error = PrivateFailure("SECRET_SENTINEL")
        with (
            patch.object(execution_cli, "configure_logging"),
            patch.object(execution_cli, "migrate", side_effect=error),
            redirect_stdout(io.StringIO()) as output,
            self.assertLogs("continuity_lab", level="ERROR") as logs,
        ):
            result = execution_cli.main(["--db", "unused", "migrate", "--backup", "unused-backup"])
        self.assert_safe_defect(result, output.getvalue(), logs.records)

    def test_worker_initialization_defect_is_safe_and_logged_once(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database, supplier = root / "execution.sqlite3", root / "supplier.sqlite3"
            migrate(database, root / "backup.sqlite3")
            initialize_supplier(supplier, scope_id="account-a")
            with (
                patch.object(inquiry_worker, "configure_logging"),
                patch.object(
                    inquiry_worker, "InquiryWorker", side_effect=PrivateFailure("SECRET_SENTINEL")
                ),
                redirect_stdout(io.StringIO()) as output,
                self.assertLogs("continuity_lab.inquiry_worker", level="ERROR") as logs,
            ):
                result = inquiry_worker.main(
                    [
                        "--db",
                        str(database),
                        "--supplier-db",
                        str(supplier),
                        "--scope",
                        "account-a",
                        "--task-id",
                        "unused",
                    ]
                )
        self.assert_safe_defect(result, output.getvalue(), logs.records)


if __name__ == "__main__":
    unittest.main()
