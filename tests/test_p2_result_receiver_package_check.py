"""Package controls and bounded harmless children; no builders or remote services."""

from __future__ import annotations

import ast
import contextlib
import copy
import functools
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import patch

SCRIPT = (
    Path(__file__).resolve().parents[1] / "local-setup/scripts/p2_result_receiver_package_check.py"
)
SPEC = importlib.util.spec_from_file_location("result_package_tested", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


def child_registry(
    directory: Path, nonce: str, parent_pid: int = 22000, *, count: int = 10
) -> dict[str, Any]:
    package.private_parents(directory)
    for number, (name, returns) in enumerate(
        sorted(package.APPLICATION_CHILD_RETURNS.items())[:count], 1
    ):
        slot = directory / ("child-" + str(number).zfill(2))
        package.private_parents(slot)
        common = {"schemaVersion": 1, "nonce": nonce, "slot": slot.name}
        pid = 23000 + number
        package.write(
            slot / "descriptor.json",
            package.json_bytes(
                {
                    **common,
                    "parentPid": parent_pid,
                    "testId": "test_channel_policy_native_worker_process.WorkerProcessTests."
                    + name,
                    "programSha256": "0" * 64,
                    "lifetimeDeadlineNs": 9_000_000_000,
                }
            ),
        )
        package.write(
            slot / "started.json",
            package.json_bytes({**common, "parentPid": parent_pid, "pid": pid, "pgid": pid}),
        )
        package.write(slot / "go.json", package.json_bytes({**common, "pid": pid, "pgid": pid}))
        package.write(
            slot / "settled.json",
            package.json_bytes(
                {
                    **common,
                    "pid": pid,
                    "pgid": pid,
                    "returncode": returns[0],
                    "directReaped": True,
                    "pipesDrained": True,
                    "groupAbsent": True,
                }
            ),
        )
    return package.application_child_records(
        directory, nonce, complete=count == 10, parent_pid=parent_pid
    )


@functools.cache
def retention_tools() -> tuple[ModuleType, ModuleType]:
    # Retention helpers come only from this maintained checkout.
    root = Path(__file__).resolve().parents[1]
    starter, _scoped, products = package.helpers(root)
    return starter, products


def retained_api(fake: SimpleNamespace) -> SimpleNamespace:
    starter, _products = retention_tools()
    for name in (
        "json_bytes",
        "write_private",
        "retained_inventory",
        "validate_retained_index",
        "settled",
    ):
        setattr(fake, name, getattr(starter, name))
    return fake


def npm(
    files: dict[str, bytes], *, extra: tuple[str, bytes] | None = None, link: bool = False
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, raw in list(files.items()) + ([] if extra is None else [extra]):
            entry = tarfile.TarInfo(name)
            if link:
                entry.type, entry.linkname = tarfile.SYMTYPE, "../escape"
            else:
                entry.size = len(raw)
            archive.addfile(entry, None if link else io.BytesIO(raw))
    return output.getvalue()


def wheel(files: dict[str, bytes], *, extra: tuple[str, bytes] | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, raw in list(files.items()) + ([] if extra is None else [extra]):
            archive.writestr(name, raw)
    return output.getvalue()


class BudgetAndPlan(unittest.TestCase):
    def test_plan_keeps_offline_fake_port_and_actual_profiles_separate(self) -> None:
        value = package.plan()
        self.assertEqual(value["expected_process_groups"], 6 + 17 + 2)
        self.assertEqual(value["max_process_groups"], 32)
        self.assertEqual(value["total_seconds"], 360)
        self.assertEqual(value["cleanup_seconds"], 20)
        self.assertEqual(value["max_stream_bytes"], 65536)
        self.assertEqual(value["aggregate_capture_bytes"], 2097152)
        self.assertEqual(value["p3_offline_assertions"], 8)
        self.assertEqual(value["p3_installed_fake_port_tests"], 20)
        self.assertEqual(value["source_actual_assertions"], 0)
        self.assertEqual(value["installed_actual_assertions"], 0)
        self.assertEqual(
            value["payloads"], {"p2": 124, "p3_python": 39, "p1_python": 77, "specialist_npm": 32}
        )
        self.assertFalse(value["provider_calls"])

    def test_combined_budget_counts_both_live_owners_and_reservations(self) -> None:
        package.combined_budget(8, 100, 20, 17, 200, 30)
        for args, kwargs in [
            ((16, 0, 0, 17, 0, 0), {}),
            ((True, 0, 0, 0, 0, 0), {}),
            ((1, 2097100, 20, 1, 20, 20), {}),
            ((1, 0, 0, 1, 0, 2097152), {"new_outer_reservation": 1}),
            ((1, 0, -1, 1, 0, 0), {}),
        ]:
            with self.subTest(args=args), self.assertRaises(package.PackageError):
                package.combined_budget(*args, **kwargs)

    def test_module_import_and_plan_are_inert_without_tool_or_socket_work(self) -> None:
        spec = importlib.util.spec_from_file_location("package_import_only", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with (
            patch("subprocess.Popen", side_effect=AssertionError("spawned")),
            patch("socket.socket.connect", side_effect=AssertionError("connected")),
            patch("socket.socket.bind", side_effect=AssertionError("bound")),
            patch("tempfile.mkdtemp", side_effect=AssertionError("allocated")),
            patch("shutil.which", side_effect=AssertionError("tool_lookup")),
        ):
            spec.loader.exec_module(module)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(module.main(["--plan"]), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "planned")

    def test_plan_starts_no_helpers_or_external_work(self) -> None:
        output = io.StringIO()
        with (
            patch.object(package, "helpers", side_effect=AssertionError("helpers_called")),
            patch.object(package.tempfile, "mkdtemp", side_effect=AssertionError("allocated")),
            patch.object(package.shutil, "which", side_effect=AssertionError("tool_lookup")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(package.main(["--plan"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "planned")


class ChannelOriginMode(unittest.TestCase):
    def test_explicit_mode_retains_budget_roles_and_separates_all_counts(self) -> None:
        legacy, origin = package.plan(), package.plan(channel_origin=True)
        self.assertEqual(legacy["mode"], "offline_result_package_bridge")
        self.assertEqual(origin["mode"], "offline_channel_origin_package_bridge")
        self.assertEqual(origin["p3_installed_fake_port_tests"], 61)
        self.assertEqual(origin["p3_installed_legacy_fake_port_tests"], 20)
        self.assertEqual(origin["p3_installed_origin_fake_port_tests"], 41)
        self.assertEqual(origin["p3_origin_test_counts"], package.ORIGIN_TEST_COUNTS)
        self.assertEqual(legacy["p3_installed_origin_fake_port_tests"], 0)
        self.assertTrue(origin["p2_operation_only_probe"])
        for key in (
            "total_seconds",
            "cleanup_seconds",
            "max_process_groups",
            "expected_process_groups",
            "aggregate_capture_bytes",
            "max_stream_bytes",
            "p3_builder_roles",
            "payloads",
            "source_actual_assertions",
            "installed_actual_assertions",
            "database_calls",
            "rtc_rooms",
            "provider_calls",
        ):
            with self.subTest(key=key):
                self.assertEqual(origin[key], legacy[key])
        self.assertEqual(len(package.input_names()), 8)
        self.assertEqual(len(package.input_names(channel_origin=True)), 12)
        self.assertEqual(
            set(package.input_names(channel_origin=True)) - set(package.input_names()),
            {"contracts/delegation/channel-policy-v3.json"}
            | {"projects/delegation-reliability/tests/" + n for n in package.ORIGIN_TEST_COUNTS},
        )

    def test_mode_is_explicit_strict_boolean_before_helpers_or_allocation(self) -> None:
        mode_values: tuple[object, ...] = (None, 0, 1, "true", [])
        for value in mode_values:
            for method in (
                package.plan,
                package.input_names,
                package.package_mode,
                package.p2_consumer,
                package.p3_types,
                package.p3_execution,
                package.p3_expected_report,
            ):
                with (
                    self.subTest(value=value, method=method.__name__),
                    self.assertRaises(package.PackageError),
                ):
                    method(channel_origin=value)
            with (
                patch.object(package, "helpers", side_effect=AssertionError("helper called")),
                self.assertRaises(package.PackageError),
            ):
                package.run(
                    Path("/private/tmp"), Path("/private/tmp/unused.json"), channel_origin=value
                )

    def test_origin_plan_is_inert_and_cli_opt_in_selects_only_new_mode(self) -> None:
        output = io.StringIO()
        with (
            patch.object(package, "helpers", side_effect=AssertionError("helper called")),
            patch.object(package.tempfile, "mkdtemp", side_effect=AssertionError("allocated")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(package.main(["--plan", "--channel-origin"]), 0)
        self.assertEqual(json.loads(output.getvalue()), package.plan(channel_origin=True))

    def test_early_cli_failure_preserves_explicit_mode_and_finite_diagnostics(self) -> None:
        output = io.StringIO()
        with (
            patch.object(package, "report_path", side_effect=package.PackageError("invalid_input")),
            patch.object(package, "run", side_effect=AssertionError("run started")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(package.main(["--channel-origin"]), 1)
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "schema_version": 1,
                "mode": "offline_channel_origin_package_bridge",
                "channel_origin": True,
                "status": "failed",
                "code": "invalid_input",
            },
        )

    def test_both_cli_modes_contain_unhashable_dependency_error_codes(self) -> None:
        unhashable_codes: tuple[object, ...] = ([], {})
        for channel_origin in (False, True):
            for code in unhashable_codes:
                with self.subTest(channel_origin=channel_origin, code_type=type(code).__name__):
                    self._assert_contained_dependency_code(code, channel_origin=channel_origin)

    def test_both_cli_modes_hide_private_dependency_codes_and_exception_text(self) -> None:
        private_codes: tuple[object, ...] = ("PRIVATE_SENTINEL code", None, 1, False)
        for channel_origin in (False, True):
            for code in private_codes:
                with self.subTest(channel_origin=channel_origin, code_type=type(code).__name__):
                    self._assert_contained_dependency_code(code, channel_origin=channel_origin)

    def test_both_cli_modes_contain_private_dependency_code_getter_failure(self) -> None:
        class GetterError(RuntimeError):
            @property
            def code(self) -> str:
                raise RuntimeError("PRIVATE_SENTINEL code getter failure")

        error = GetterError("PRIVATE_SENTINEL original exception")
        self.assertEqual(package.finite_code(error), "package_failed")
        for channel_origin in (False, True):
            with self.subTest(channel_origin=channel_origin):
                self._assert_contained_dependency_error(error, channel_origin=channel_origin)

    def test_finite_code_preserves_base_exception_control_flow_from_getter(self) -> None:
        class GetterInterrupt(RuntimeError):
            @property
            def code(self) -> str:
                raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            package.finite_code(GetterInterrupt())

    def _assert_contained_dependency_code(self, code: object, *, channel_origin: bool) -> None:
        class DependencyError(RuntimeError):
            def __init__(self, reported_code: object) -> None:
                self.code = reported_code
                super().__init__("PRIVATE_SENTINEL exception text")

        self._assert_contained_dependency_error(
            DependencyError(code), channel_origin=channel_origin
        )

    def _assert_contained_dependency_error(self, error: Exception, *, channel_origin: bool) -> None:
        output = io.StringIO()
        with (
            patch.object(package, "report_path", side_effect=error),
            patch.object(package, "run", side_effect=AssertionError("run started")),
            patch.object(package.tempfile, "mkdtemp", side_effect=AssertionError("allocated")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(package.main(["--channel-origin"] if channel_origin else []), 1)
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "schema_version": 1,
                "mode": package.package_mode(channel_origin=channel_origin),
                "channel_origin": channel_origin,
                "status": "failed",
                "code": "package_failed",
            },
        )
        self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())

    def test_exact_origin_sources_are_copied_unadapted_and_source_bound(self) -> None:
        names = package.input_names(channel_origin=True)
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            for name in names:
                source = root / "source" / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes((name + "\nsynthetic original bytes\n").encode())
            inventory = package.copy_inputs(
                root / "source", root / "app", root / "retained", channel_origin=True
            )
            self.assertEqual(set(inventory), set(names))
            for name in names:
                original = (root / "source" / name).read_bytes()
                self.assertEqual((root / "app" / name).read_bytes(), original)
                self.assertEqual((root / "retained/inputs" / name).read_bytes(), original)
                self.assertEqual(
                    inventory[name], {"bytes": len(original), "sha256": package.digest(original)}
                )
            self.assertFalse(any("/src/" in name for name in inventory))
            self.assertEqual(
                {
                    str(p.relative_to(root / "app"))
                    for p in (root / "app").rglob("*")
                    if p.is_file()
                },
                set(names),
            )

    def test_missing_or_symlinked_origin_fixture_cannot_reduce_selected_inventory(self) -> None:
        for linked in (False, True):
            with (
                self.subTest(linked=linked),
                tempfile.TemporaryDirectory(dir="/private/tmp") as folder,
            ):
                root = Path(folder).resolve()
                names = package.input_names(channel_origin=True)
                for name in names[:-1]:
                    source = root / "source" / name
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes(b"synthetic\n")
                if linked:
                    other = root / "other.json"
                    other.write_bytes(b"untrusted\n")
                    (root / "source" / names[-1]).symlink_to(other)
                with self.assertRaises(package.PackageError):
                    package.copy_inputs(
                        root / "source", root / "app", root / "retained", channel_origin=True
                    )
                self.assertFalse((root / "app" / names[-1]).exists())

    def test_current_origin_sources_are_all_part_of_change_detection(self) -> None:
        root = SCRIPT.parents[2]
        before = package.source_snapshot(root)
        selected = package.source_snapshot(root, channel_origin=True)
        self.assertEqual(
            set(selected) - set(before),
            set(package.input_names(channel_origin=True)) - set(package.input_names()),
        )
        for name in package.input_names(channel_origin=True):
            self.assertEqual(selected[name], package.digest((root / name).read_bytes()))

    def test_public_probes_keep_legacy_bytes_and_include_inert_origin_surfaces(self) -> None:
        self.assertEqual(package.p2_consumer(), package.P2_CONSUMER)
        self.assertEqual(package.p3_types(), package.P3_TYPES)
        self.assertEqual(package.p3_execution(), package.P3_EXECUTION)
        p2 = package.p2_consumer(channel_origin=True)
        for name in (
            "OperationClientConfig",
            "OperationClientBinding",
            "new starter.ExternalOperationClient(config)",
            "await client.close()",
            "operation_only_config:true",
        ):
            self.assertIn(name, p2)
        self.assertLess(
            p2.index("Socket.prototype.connect=denied"),
            p2.index("new starter.ExternalOperationClient(config)"),
        )
        self.assertLess(
            p2.index("await client.close()"), p2.index("finally{Socket.prototype.connect=connect")
        )
        self.assertNotIn("providerScope", p2)
        self.assertNotIn("databasePassword", p2)
        for name in (
            "ChannelPolicyCoordinator",
            "ChannelPolicyRunner",
            "ChannelPolicyDeliveryClient",
            "ChannelPolicyResultReadPort",
            "coordinator.scope",
        ):
            self.assertIn(name, package.p3_types(channel_origin=True))
        executable = package.p3_execution(channel_origin=True)
        compile(executable, "origin-consumer.py", "exec")
        self.assertIn("channel_contracts", executable)
        self.assertIn("channel_execution", executable)
        self.assertIn("scope_property.fset is None", executable)
        self.assertIn("is_relative_to(Path(sys.prefix).resolve())", executable)

    def test_generated_runner_rejects_missing_extra_failed_or_skipped_cases(self) -> None:
        tree = ast.parse(package.p3_execution(channel_origin=True))
        selected = []
        for node in tree.body:
            is_counts = isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "counts" for t in node.targets
            )
            is_suite = (
                isinstance(node, ast.For)
                and isinstance(node.target, ast.Tuple)
                and [ast.unparse(target) for target in node.target.elts] == ["pattern", "expected"]
            )
            is_total = isinstance(node, ast.Assert) and "sum(counts.values())" in ast.unparse(node)
            if is_counts or is_suite or is_total:
                selected.append(node)
        self.assertEqual(len(selected), 3)
        code = compile(
            ast.Module(body=selected, type_ignores=[]), "selected-real-origin-suite-guards", "exec"
        )
        expected = {"test_fixed_policy_completion.py": 20, **package.ORIGIN_TEST_COUNTS}
        for corrupted in (None, "missing", "extra", "failed", "skipped", "run_count"):

            def discover(
                path: str, *, pattern: str, corruption: str | None = corrupted
            ) -> SimpleNamespace:
                number = expected[pattern]
                if pattern == "test_channel_policy_execution.py":
                    number += -1 if corruption == "missing" else 1 if corruption == "extra" else 0
                return SimpleNamespace(countTestCases=lambda: number, pattern=pattern)

            def run(suite: SimpleNamespace, corruption: str | None = corrupted) -> SimpleNamespace:
                failed = suite.pattern == "test_channel_policy_execution.py"
                return SimpleNamespace(
                    wasSuccessful=lambda: not (failed and corruption == "failed"),
                    testsRun=expected[suite.pattern] - int(failed and corruption == "run_count"),
                    skipped=[("one", "skip")] if failed and corruption == "skipped" else [],
                )

            fake = SimpleNamespace(
                defaultTestLoader=SimpleNamespace(discover=discover),
                TextTestRunner=lambda runner=run, **kwargs: SimpleNamespace(run=runner),
            )
            namespace = {"unittest": fake, "root": Path("/private/tmp/inert")}
            with self.subTest(corrupted=corrupted):
                if corrupted is None:
                    exec(code, namespace)  # noqa: S102 - trusted generated AST, fake ports only
                    self.assertEqual(namespace["counts"], expected)
                else:
                    with self.assertRaises(AssertionError):
                        exec(code, namespace)  # noqa: S102 - trusted generated AST, fake ports only

    def test_origin_report_cannot_relabel_fake_tests_as_actual_or_drop_legacy(self) -> None:
        expected = package.p3_expected_report(channel_origin=True)
        self.assertEqual(expected["legacy_fake_port_tests"], 20)
        self.assertEqual(expected["origin_fake_port_tests"], 41)
        self.assertEqual(expected["fake_port_tests"], 61)
        mutations: tuple[dict[str, object], ...] = (
            {"origin_fake_port_tests": 40},
            {"legacy_fake_port_tests": 0},
            {"origin_test_counts": {}},
            {"installed_actual_assertions": 14},
        )
        for changed in mutations:
            with self.subTest(changed=changed), self.assertRaises(package.PackageError):
                package.selected_report(package.json_bytes({**expected, **changed}), expected)


class RootApplicationMode(unittest.TestCase):
    def test_old_plan_and_probe_bytes_remain_exact(self) -> None:
        values = {
            "legacy_plan": package.json_bytes(package.plan()),
            "origin_plan": package.json_bytes(package.plan(channel_origin=True)),
            "legacy_p2_probe": package.p2_consumer().encode(),
            "origin_p2_probe": package.p2_consumer(channel_origin=True).encode(),
            "legacy_p3_types": package.p3_types().encode(),
            "origin_p3_types": package.p3_types(channel_origin=True).encode(),
            "legacy_p3_execution": package.p3_execution().encode(),
            "origin_p3_execution": package.p3_execution(channel_origin=True).encode(),
        }
        self.assertEqual(
            {key: package.digest(raw) for key, raw in values.items()},
            {
                "legacy_plan": "643a3e1deefcedd8ea6f9bc9e2b287b3340d6cce375b8d29bae3a4bfb0e9c184",
                "origin_plan": "24afcda48282e88623f09a1157dea01f3d990a504f422c7921d9139eb3f2617b",
                "legacy_p2_probe": "034326a0e8de7c4cf569272a597ce6f86081af5f917941bbae5aaa78b5f689c5",
                "origin_p2_probe": "9dbfbfe36ed2633bcf179688c6fc312c04cec41727761e886bccf4ad22b6b174",
                "legacy_p3_types": "e05a1cfa58f3c0d2ce1c49d8dec6b7e7c65534dbf0826bfd5582620ef611891e",
                "origin_p3_types": "d930eef275e85f4ccbbde66ac67c92c8979e47f5a824a9845fcfb1f764682ecb",
                "legacy_p3_execution": "1126796b49d5facba98b26617a263733315d3732a073e14f6f1651c963221b94",
                "origin_p3_execution": "ec99f07a7940cc0ee22ad1cfa88d1b97beaca74291cace045dae35619dfe5370",
            },
        )

    def test_app_plan_implies_origin_and_freezes_seven_extra_roles_and_all_suites(self) -> None:
        legacy, app = package.plan(channel_origin=True), package.plan(root_application=True)
        self.assertEqual(app, package.plan(channel_origin=True, root_application=True))
        self.assertEqual(app["mode"], "offline_root_application_package_bridge")
        self.assertTrue(app["channel_origin"])
        self.assertTrue(app["root_application"])
        self.assertEqual(app["expected_process_groups"], 32)
        self.assertEqual(len(package.outer_roles(root_application=True)), 15)
        self.assertEqual(
            app["root_application_roles"],
            [
                "app-build",
                "app-rebuild",
                "p2-python-build",
                "app-install",
                "app-check",
                "app-types",
                "app-execution",
            ],
        )
        self.assertEqual(
            app["root_application_test_counts"],
            {
                "test_p2_channel_origin_wire.py": 13,
                "test_p3_channel_origin.py": 18,
                "test_p3_channel_origin_http.py": 19,
                "test_p3_channel_origin_composition.py": 2,
                "test_channel_policy_discovery.py": 22,
                "test_channel_policy_current_result.py": 24,
                "test_channel_policy_current_result_producer.py": 43,
                "test_channel_policy_executor.py": 34,
                "test_channel_policy_worker_client.py": 20,
                "test_channel_policy_origin_router.py": 34,
                "test_channel_policy_jobs.py": 61,
                "test_channel_policy_public_clients.py": 21,
                "test_channel_policy_transport_canonical.py": 5,
                "test_channel_policy_owner_config.py": 22,
                "test_channel_policy_application.py": 33,
                "test_p2_current_case_bridge.py": 17,
                "test_p3_channel_receiver.py": 15,
                "test_channel_policy_cli.py": 22,
                "test_channel_policy_room_result_client.py": 25,
                "test_channel_policy_room_control.py": 15,
                "test_channel_policy_room_control_client.py": 14,
                "test_channel_policy_worker_current_result.py": 15,
                "test_channel_policy_current_result_context.py": 20,
                "test_channel_policy_native_models.py": 34,
                "test_channel_policy_native_prepare_http.py": 26,
                "test_channel_policy_current_result_http.py": 20,
                "test_channel_policy_native_worker_config.py": 26,
                "test_channel_policy_native_worker.py": 27,
                "test_channel_policy_native_room.py": 21,
                "test_channel_policy_native_room_admin.py": 12,
                "test_channel_policy_native_room_state.py": 14,
                "test_channel_policy_native_worker_process.py": 13,
                "test_channel_policy_operator_contract.py": 12,
                "test_channel_policy_operator_sms.py": 14,
                "test_channel_policy_operator_http.py": 12,
                "test_channel_policy_parent.py": 19,
            },
        )
        self.assertEqual(app["root_application_installed_fake_port_tests"], 764)
        self.assertEqual((app["root_application_payloads"], app["p2_python_payloads"]), (86, 9))
        self.assertEqual(len(package.input_names(root_application=True)), 54)
        for key in (
            "total_seconds",
            "cleanup_seconds",
            "max_process_groups",
            "aggregate_capture_bytes",
            "max_stream_bytes",
            "p3_offline_assertions",
            "p3_installed_fake_port_tests",
            "source_actual_assertions",
            "installed_actual_assertions",
            "database_calls",
            "rtc_rooms",
            "provider_calls",
        ):
            self.assertEqual(app[key], legacy[key], key)
        output = io.StringIO()
        with (
            patch.object(package, "helpers", side_effect=AssertionError("helpers")),
            patch.object(package.tempfile, "mkdtemp", side_effect=AssertionError("allocate")),
            patch("subprocess.Popen", side_effect=AssertionError("child")),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(package.main(["--root-application", "--plan"]), 0)
        self.assertEqual(json.loads(output.getvalue()), app)

    def test_selected_current_app_suite_counts_match_raw_source_and_frozen_runtime_inventory(
        self,
    ) -> None:
        root = SCRIPT.parents[2]
        observed = {}
        for name, expected in package.ROOT_APPLICATION_TEST_COUNTS.items():
            tree = ast.parse((root / "tests" / name).read_bytes())
            count = sum(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
                for node in ast.walk(tree)
            )
            self.assertEqual(count, expected, name)
            observed[name] = count
        self.assertEqual((len(observed), sum(observed.values())), (36, 764))
        payloads = package.application_payload(root)
        self.assertEqual(len(payloads), 86)
        for name in (
            "current_result_producer",
            "worker_client",
            "origin_router",
            "jobs",
            "public_clients",
            "case_bridge",
            "result_receiver",
            "owner_config",
            "application",
            "__main__",
            "_bounded_loopback_http",
            "_loopback_json",
            "_native_models_sdk",
            "room_result_client",
            "room_control",
            "room_control_client",
            "worker_current_result",
            "current_result_context",
            "native_models",
            "native_prepare_http",
            "current_result_http",
            "native_worker_config",
            "native_worker",
            "native_room",
            "native_room_admin",
            "native_room_state",
            "native_worker_process",
            "operator",
            "operator_contract",
            "operator_sms",
            "operator_http",
            "parent",
        ):
            self.assertIn("services/channel_policy_demo/" + name + ".py", payloads)
        self.assertIn("tests/test_channel_policy_parent.py", package.application_source_tests(root))
        self.assertEqual(len(package.application_source_tests(root)), 161)
        self.assertTrue(
            {
                "local-setup/scripts/p2_current_case_bridge.py",
                "local-setup/scripts/p3_channel_receiver.py",
            }
            <= set(package.ROOT_APPLICATION_HELPERS)
        )

    def test_root_runtime_extra_requires_all_five_exact_declared_edges(self) -> None:
        root = SCRIPT.parents[2]
        config = package.tomllib.loads((root / "pyproject.toml").read_text())
        edges = config["project"]["optional-dependencies"]["channel-demo"]
        self.assertEqual(
            edges,
            [
                "channel-continuity[native]==0.1.0",
                "delegation-reliability==0.1.0",
                "aiohttp==3.14.5",
                "h11==0.16.0",
                "livekit-api==1.2.2",
            ],
        )
        mutations = [
            edges[:-1],
            [edge.replace("3.14.5", "3.14.4") for edge in edges],
            [edge.replace("0.16.0", "0.15.0") for edge in edges],
            edges + ["unapproved-extra==1.0.0"],
        ]
        for changed in mutations:
            candidate = copy.deepcopy(config)
            candidate["project"]["optional-dependencies"]["channel-demo"] = changed
            with (
                self.subTest(edges=changed),
                patch.object(package.tomllib, "loads", return_value=candidate),
                self.assertRaises(package.PackageError),
            ):
                package.application_payload(root)

    def test_mode_rejects_nonbooleans_before_helpers(self) -> None:
        for value in (None, 0, 1, "true", []):
            for method in (package.plan, package.input_names, package.package_mode):
                with (
                    self.subTest(value=value, method=method.__name__),
                    self.assertRaises(package.PackageError),
                ):
                    method(channel_origin=False, root_application=value)
            with (
                patch.object(package, "helpers", side_effect=AssertionError("helpers")),
                self.assertRaises(package.PackageError),
            ):
                package.run(
                    Path("/private/tmp"), Path("/private/tmp/unused.json"), root_application=value
                )

    def test_third_cli_mode_hides_private_unhashable_and_getter_codes(self) -> None:
        class GetterError(RuntimeError):
            @property
            def code(self) -> str:
                raise RuntimeError("PRIVATE_GETTER")

        errors = [GetterError("PRIVATE_ERROR")]
        for code in ([], {}, "PRIVATE_CODE", False):
            error = RuntimeError("PRIVATE_ERROR")
            error.code = code
            errors.append(error)
            self.assertEqual(package.PackageError(code).code, "package_failed")
        for error in errors:
            output = io.StringIO()
            with (
                self.subTest(error=type(error).__name__),
                patch.object(package, "report_path", side_effect=error),
                patch.object(package, "run", side_effect=AssertionError("run")),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(package.main(["--root-application"]), 1)
            self.assertEqual(
                json.loads(output.getvalue()),
                {
                    "schema_version": 1,
                    "mode": "offline_root_application_package_bridge",
                    "channel_origin": True,
                    "root_application": True,
                    "status": "failed",
                    "code": "package_failed",
                },
            )
            self.assertNotIn("PRIVATE", output.getvalue())

    def test_root_inputs_are_copied_verbatim_without_product_sources(self) -> None:
        names = package.input_names(root_application=True)
        self.assertTrue(
            {
                "tests/test_channel_policy_current_result.py",
                "tests/test_channel_policy_current_result_producer.py",
                "tests/test_channel_policy_executor.py",
                "tests/test_channel_policy_worker_client.py",
                "tests/test_channel_policy_origin_router.py",
                "tests/test_channel_policy_jobs.py",
                "tests/test_channel_policy_public_clients.py",
                "tests/test_channel_policy_transport_canonical.py",
                "tests/test_channel_policy_owner_config.py",
                "tests/test_channel_policy_application.py",
                "tests/test_channel_policy_cli.py",
                "tests/test_p2_current_case_bridge.py",
                "tests/test_p3_channel_receiver.py",
                "local-setup/scripts/p2_current_case_bridge.py",
                "local-setup/scripts/p3_channel_receiver.py",
                "contracts/delegation/channel-policy-v3.json",
                "contracts/delegation/result-receiver-v1.json",
                "contracts/delegation/fixed-policy-v2.json",
            }
            <= set(names)
        )
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            for name in names:
                source = root / "source" / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes((name + "\noriginal UTF-8 Ω\n").encode())
            inventory = package.copy_inputs(
                root / "source", root / "app", root / "retained", root_application=True
            )
            self.assertEqual(set(inventory), set(names))
            for name in names:
                raw = (root / "source" / name).read_bytes()
                self.assertEqual((root / "app" / name).read_bytes(), raw)
                self.assertEqual((root / "retained/inputs" / name).read_bytes(), raw)
                self.assertEqual(inventory[name]["sha256"], package.digest(raw))
            self.assertFalse((root / "app/services").exists())
            self.assertFalse((root / "app/projects/channel-continuity/python").exists())
            self.assertEqual(
                set(names) - set(package.input_names(channel_origin=True)),
                set(package.ROOT_APPLICATION_INPUTS),
            )

    def test_snapshot_binds_all_built_runtime_metadata_and_new_raw_inputs(self) -> None:
        root = SCRIPT.parents[2]
        old = package.source_snapshot(root, channel_origin=True)
        selected = package.source_snapshot(root, root_application=True)
        required = (
            set(package.application_payload(root))
            | set(package.application_source_tests(root))
            | set(package.ROOT_APPLICATION_INPUTS)
            | {
                "README.md",
                "pyproject.toml",
                "uv.lock",
                "projects/channel-continuity/python/pyproject.toml",
                "projects/channel-continuity/python/README.md",
            }
        )
        required |= {
            str(p.relative_to(root))
            for p in (root / "projects/channel-continuity/python/src").rglob("*")
            if p.is_file() and (p.suffix == ".py" or p.name == "py.typed")
        }
        required |= {str(p.relative_to(root)) for p in (root / "services").rglob("*.md")}
        self.assertTrue(required <= set(selected))
        self.assertEqual(len(package.application_payload(root)), 86)
        for name in required:
            self.assertEqual(selected[name], package.digest((root / name).read_bytes()))
        self.assertFalse(
            any(
                part in {".env", ".env.providers", ".local", "node_modules"}
                for name in selected
                for part in Path(name).parts
            )
        )
        self.assertTrue(set(old) <= set(selected))

    def test_generated_probes_use_public_prefix_only_and_closed_test_cardinalities(self) -> None:
        compile(package.ROOT_APPLICATION_TYPES, "app-types.py", "exec")
        executable = package.application_execution()
        compile(executable, "app-execution.py", "exec")
        self.assertIn(
            "from channel_continuity.native import NativeRuntime", package.ROOT_APPLICATION_TYPES
        )
        self.assertIn("TrustedPrincipal", package.ROOT_APPLICATION_TYPES)
        self.assertIn("operator_contract,operator_sms,operator_http,parent", executable)
        for public_name in (
            "CurrentResultObservation",
            "CurrentResultProducer",
            "ProducerBinding",
            "InspectionFactoryPort",
            "ReadOnlyInspection",
            "CurrentResultRequest",
            "encode_current_result_observation",
            "encode_current_result_request",
            "parse_current_result_observation",
            "parse_current_result_request",
            "ChannelPolicyExecutor",
            "DiscoveryPort",
            "ExecutorBinding",
            "PreparedReadPort",
            "RunnerFactory",
            "ScanObservation",
            "StoredWorkPort",
            "await executor.scan_once()",
            "await executor.close()",
            "executor.pending_count",
            "ChannelPolicyWorkerClient",
            "CoordinatorWorkerPreparedReader",
            "ChannelOriginRouter",
            "CoordinatorFactory",
            "ActualJob",
            "ChannelPolicyJobFactory",
            "EvidenceCatalogue",
            "JobClientFactory",
            "PublicClientFactory",
            "PublicWorkConfig",
            "PublicSpecialistConfig",
            "PublicReceiverConfig",
            "CurrentCaseBinding",
            "CurrentCaseBridge",
            "PublicCurrentCaseReader",
            "ChannelResultReceiver",
            "OwnerProfile",
            "parse_owner_profile",
            "ChannelPolicyApplication",
            "ApplicationPort",
            "run_application",
            "runner: ChannelPolicyRunner",
            "delivery: ChannelPolicyDeliveryClient",
            "NativeRoomOwner",
            "NativeRoomRoute",
            "RoomAdminPort",
            "RoomControlPort",
            "WorkerPort",
            "LiveKitRoomAdmin",
            "NativeWorkerProcess",
            "StartCommand",
            "EndCommand",
            "RoomOperatorPort",
            "ApplicationObservationPort",
            "SmsOperatorPort",
            "ChannelPolicyOperator",
            "ChannelPolicySmsClient",
            "ChannelPolicyOperatorHttp",
            "ChannelPolicyParent",
            "ParentSettings",
            "ParentFactories",
            "ParentAppPort",
            "ParentRoomsPort",
            "ParentSmsPort",
            "ParentHttpPort",
            "await owner.start_sources()",
            "await owner.start(cursor)",
            "owner.ready, owner.metrics()",
            "await owner.read_current(end)",
            "application.observe_case()",
            "application.observe_progress()",
        ):
            self.assertIn(public_name, package.ROOT_APPLICATION_TYPES)
        self.assertIn(
            "from services.channel_policy_demo import wire,origin,origin_http,discovery,current_result,current_result_producer,executor",
            executable,
        )
        self.assertIn(
            "(application,wire,origin,origin_http,discovery,current_result,current_result_producer,executor,worker_client,origin_router,jobs,public_clients,case_bridge,result_receiver,owner_config,runtime_application,application_cli,channel,native,work,delegation)",
            executable,
        )
        for module in (
            "current_result_producer",
            "worker_client",
            "origin_router",
            "jobs",
            "public_clients",
            "case_bridge",
            "result_receiver",
            "owner_config",
            "runtime_application",
            "application_cli",
        ):
            self.assertIn(module, executable)
        self.assertIn('version("aiohttp")=="3.14.5"', executable)
        self.assertIn('version("h11")=="0.16.0"', executable)
        self.assertIn("Path(sys.prefix).resolve()", executable)
        self.assertIn(
            '"services","channel_continuity","continuity_lab","delegation_reliability","livekit"',
            executable,
        )
        self.assertIn('root/"root-application-payloads.json"', executable)
        self.assertNotIn("sys.path.insert", executable)
        self.assertNotIn("ROOT", executable)
        tree = ast.parse(executable)
        selected = []
        for node in tree.body:
            is_counts = isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "counts" for t in node.targets
            )
            is_suite = (
                isinstance(node, ast.For)
                and isinstance(node.target, ast.Tuple)
                and [ast.unparse(t) for t in node.target.elts] == ["pattern", "expected"]
            )
            is_total = isinstance(node, ast.Assert) and "sum(counts.values())" in ast.unparse(node)
            if is_counts or is_suite or is_total:
                selected.append(node)
        self.assertEqual(len(selected), 3)
        code = compile(ast.Module(body=selected, type_ignores=[]), "app-suite-guards", "exec")
        expected = package.ROOT_APPLICATION_TEST_COUNTS
        for corruption in (None, "missing", "extra", "failed", "skipped", "run_count"):

            def discover(
                path: str, *, pattern: str, corruption: str | None = corruption
            ) -> SimpleNamespace:
                delta = (
                    (-1 if corruption == "missing" else 1 if corruption == "extra" else 0)
                    if pattern == "test_channel_policy_discovery.py"
                    else 0
                )
                return SimpleNamespace(
                    pattern=pattern, countTestCases=lambda: expected[pattern] + delta
                )

            def run(suite: SimpleNamespace, corruption: str | None = corruption) -> SimpleNamespace:
                selected = suite.pattern == "test_channel_policy_discovery.py"
                return SimpleNamespace(
                    wasSuccessful=lambda: not (selected and corruption == "failed"),
                    testsRun=expected[suite.pattern] - int(selected and corruption == "run_count"),
                    skipped=[("one", "skip")] if selected and corruption == "skipped" else [],
                )

            fake = SimpleNamespace(
                defaultTestLoader=SimpleNamespace(discover=discover),
                TextTestRunner=lambda **kwargs: SimpleNamespace(run=run),
            )
            namespace = {"unittest": fake, "root": Path("/private/tmp/app"), "json": json}
            with (
                self.subTest(corruption=corruption),
                patch(
                    "importlib.import_module",
                    return_value=SimpleNamespace(configure_child_records=lambda *args: None),
                ),
                patch.object(
                    Path,
                    "read_bytes",
                    return_value=package.json_bytes({"schemaVersion": 1, "nonce": "a" * 32}),
                ),
            ):
                if corruption is None:
                    exec(code, namespace)  # noqa: S102 - trusted generated AST with fake ports only
                    self.assertEqual(namespace["counts"], expected)
                else:
                    with self.assertRaises(AssertionError):
                        exec(code, namespace)  # noqa: S102 - trusted generated AST with fake ports only
        report = package.application_expected_report()
        self.assertEqual(
            (
                report["application_fake_port_tests"],
                report["source_actual_assertions"],
                report["installed_actual_assertions"],
            ),
            (764, 0, 0),
        )
        with self.assertRaises(package.PackageError):
            package.selected_report(
                package.json_bytes({**report, "installed_actual_assertions": 14}), report
            )

    def test_root_42_group_proof_keeps_32_builder_validator_separate(self) -> None:
        outer = SimpleNamespace(children=[])
        nested = SimpleNamespace(children=[], outputs={})
        for role in sorted(package.outer_roles(root_application=True)):
            outer.children.append(
                SimpleNamespace(
                    pid=12000 + len(outer.children),
                    output_directory=Path("/private/tmp/owned") / role,
                    returncode=0,
                    cleanup_failed=False,
                    group_settled=True,
                )
            )
        for number, role in enumerate(package.NESTED_ROLE_ORDER, 1):
            child = SimpleNamespace(
                pid=13000 + number, returncode=0, cleanup_failed=False, group_settled=True
            )
            nested.children.append(child)
            nested.outputs[child.pid] = Path("/private/tmp/owned") / f"{number:02d}-{role}"
        parent = next(
            child.pid for child in outer.children if child.output_directory.name == "app-execution"
        )
        fixture = {
            "groups": [
                {
                    "test_id": "test_channel_policy_native_worker_process.WorkerProcessTests."
                    + name,
                    "slot": "child-" + str(number).zfill(2),
                    "parent_pid": parent,
                    "pid": 14000 + number,
                    "pgid": 14000 + number,
                    "returncode": returns[0],
                    "direct_reaped": True,
                    "pipes_drained": True,
                    "group_absent": True,
                }
                for number, (name, returns) in enumerate(
                    sorted(package.APPLICATION_CHILD_RETURNS.items()), 1
                )
            ]
        }
        value = package.observe_process_groups(
            outer, nested, root_application=True, fixture=fixture
        )
        package.validate_process_groups(value, root_application=True)
        self.assertEqual(len(value["groups"]), 32)
        self.assertEqual(
            (value["schema_version"], len(value["test_child_groups"]), value["total_groups"]),
            (2, 10, 42),
        )
        with self.assertRaises(package.PackageError):
            package.validate_process_groups(value)
        with self.assertRaises(package.PackageError):
            package.observe_process_groups(outer, nested)
        for change in (
            lambda v: v["groups"].pop(),
            lambda v: v["groups"][0].update(role="unknown-app-role"),
            lambda v: v["groups"][0].update(owned_pid=v["groups"][1]["owned_pid"]),
            lambda v: v["groups"][0].update(group_settled=False),
        ):
            candidate = copy.deepcopy(value)
            change(candidate)
            with self.assertRaises(package.PackageError):
                package.validate_process_groups(candidate, root_application=True)

    def test_early_root_failure_preserves_cleanup_and_zero_actual_or_fake_claims(self) -> None:
        class Children:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.count = self.captured = self.reservations = 0
                self.children = []
                self.roles = kwargs["roles"]

            def close(self) -> None:
                pass

            def all_settled(self) -> bool:
                return True

        starter = retained_api(
            SimpleNamespace(
                Children=Children,
                prepare_installed=lambda *args: (_ for _ in ()).throw(
                    package.PackageError("consumer_failed")
                ),
            )
        )
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            with (
                patch.object(
                    package, "helpers", return_value=(starter, SimpleNamespace(), SimpleNamespace())
                ),
                patch.object(package, "source_snapshot", return_value={"fixture": "0"}),
                patch("subprocess.Popen", side_effect=AssertionError("child")),
            ):
                value = package.run(root, root / "failed.json", root_application=True)
            self.assertEqual(value["code"], "consumer_failed")
            self.assertTrue(value["cleanup_complete"])
            self.assertTrue(value["root_application"])
            self.assertTrue(value["channel_origin"])
            self.assertEqual(value["child_commands"], 0)
            self.assertEqual(value["root_application_installed_fake_port_tests"], 0)
            self.assertEqual(value["installed_actual_assertions"], 0)
            self.assertEqual(value["source_actual_assertions"], 0)
            self.assertEqual(json.loads((root / "failed.json").read_bytes()), value)


class RootApplicationArchives(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[dict[str, bytes], dict[str, bytes]]:
        readme = b"# Synthetic root app\n\nNo credentials.\n"
        metadata = (
            b'Name: livekit-agent-ecosystem\nVersion: 0.1.0\nRequires-Python: <3.15,>=3.14\nProvides-Extra: channel-demo\nRequires-Dist: agent-continuity==0.1.0\nRequires-Dist: channel-continuity[native]==0.1.0; extra == "channel-demo"\nRequires-Dist: delegation-reliability==0.1.0; extra == "channel-demo"\nRequires-Dist: aiohttp==3.14.5; extra == "channel-demo"\nRequires-Dist: h11==0.16.0; extra == "channel-demo"\nRequires-Dist: livekit-api==1.2.2; extra == "channel-demo"\n\n'
            + readme
        )
        config = b'[project]\nname="livekit-agent-ecosystem"\nversion="0.1.0"\nrequires-python=">=3.14,<3.15"\ndependencies=["agent-continuity==0.1.0"]\n[project.optional-dependencies]\nchannel-demo=["channel-continuity[native]==0.1.0", "delegation-reliability==0.1.0", "aiohttp==3.14.5", "h11==0.16.0", "livekit-api==1.2.2"]\n'
        (root / "README.md").write_bytes(readme)
        (root / "pyproject.toml").write_bytes(config)
        payloads = {
            "services/__init__.py": b'"""Inert."""\n',
            "services/channel_policy_demo/py.typed": b"",
            "services/channel_policy_demo/README.md": b"# Raw guide\n",
            "services/conversation_agent/assets/manifest.json": b'{"synthetic":true}\n',
        }
        files = {
            **payloads,
            "README.md": readme,
            "pyproject.toml": config,
            "PKG-INFO": metadata,
            "setup.cfg": b"[egg_info]\n",
            "livekit_agent_ecosystem.egg-info/PKG-INFO": metadata,
            "livekit_agent_ecosystem.egg-info/SOURCES.txt": b"",
            "livekit_agent_ecosystem.egg-info/dependency_links.txt": b"\n",
            "livekit_agent_ecosystem.egg-info/requires.txt": b"agent-continuity==0.1.0\n",
            "livekit_agent_ecosystem.egg-info/top_level.txt": b"services\n",
        }
        files["livekit_agent_ecosystem.egg-info/SOURCES.txt"] = (
            "\n".join(sorted(set(files) - {"PKG-INFO", "setup.cfg"})) + "\n"
        ).encode()
        return payloads, files

    def sdist(
        self, files: dict[str, bytes], *, extra: tuple[str, bytes] | None = None, link: bool = False
    ) -> bytes:
        prefix = "livekit_agent_ecosystem-0.1.0/"
        return npm(
            {prefix + name: raw for name, raw in files.items()},
            extra=None if extra is None else (prefix + extra[0], extra[1]),
            link=link,
        )

    def test_sdist_raw_payloads_metadata_and_restrictive_manual_extraction(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            payloads, files = self.fixture(root)
            selected = package.application_sdist(self.sdist(files), root, payloads)
            self.assertEqual(selected, files)
            target = root / "extracted"
            with patch.object(
                tarfile.TarFile, "extractall", side_effect=AssertionError("unsafe extraction")
            ):
                package.extract_application(selected, target)
            for name, raw in files.items():
                self.assertEqual((target / name).read_bytes(), raw)
                self.assertEqual(stat.S_IMODE((target / name).stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE((target / name).parent.stat().st_mode), 0o700)
            with self.assertRaises(package.PackageError):
                package.extract_application(selected, target)

    def test_sdist_rejects_changed_missing_extra_traversal_env_links_and_bad_metadata(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            payloads, files = self.fixture(root)
            changed = {**files, "services/__init__.py": b"changed"}
            missing = {name: raw for name, raw in files.items() if name != "services/__init__.py"}
            bad_metadata = {
                **files,
                "PKG-INFO": files["PKG-INFO"].replace(
                    b"channel-continuity[native]", b"channel-continuity[wrong]"
                ),
            }
            for candidate in (
                changed,
                missing,
                bad_metadata,
                {**files, "README.md": b"private changed"},
                {**files, "livekit_agent_ecosystem.egg-info/SOURCES.txt": b"/outside/private\n"},
            ):
                with self.subTest(names=set(candidate)), self.assertRaises(package.PackageError):
                    package.application_sdist(self.sdist(candidate), root, payloads)
            for name in (
                "../escape.py",
                "/absolute.py",
                ".env",
                ".env.providers",
                ".local/private.json",
                "node_modules/api.js",
                "services/extra.py",
                "services/__init__.py",
            ):
                with self.subTest(name=name), self.assertRaises(package.PackageError):
                    package.application_sdist(
                        self.sdist(files, extra=(name, b"PRIVATE_SYNTHETIC")), root, payloads
                    )
            with self.assertRaises(package.PackageError):
                package.application_sdist(self.sdist(files, link=True), root, payloads)
            for name in ("../x", "/x", "a//b", "a/./b", "a\\b", "a:.py", "a/\0b"):
                with self.subTest(name=name), self.assertRaises(package.PackageError):
                    package.archive_name(name)
            self.assertFalse((root / "escape.py").exists())

    def test_normal_sdist_tests_are_source_bound_and_never_relabelled_as_selected_tests(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            payloads, files = self.fixture(root)
            (root / "tests").mkdir()
            test = root / "tests/test_incidental.py"
            test.write_bytes(b"# Synthetic default sdist input, not a selected suite.\n")
            selected = package.application_source_tests(root)
            self.assertEqual(selected, {"tests/test_incidental.py": test.read_bytes()})
            with self.assertRaises(package.PackageError):
                package.application_sdist(self.sdist(files), root, payloads)
            files.update(selected)
            files["livekit_agent_ecosystem.egg-info/SOURCES.txt"] = (
                "\n".join(sorted(set(files) - {"PKG-INFO", "setup.cfg"})) + "\n"
            ).encode()
            self.assertEqual(package.application_sdist(self.sdist(files), root, payloads), files)
            files["tests/test_incidental.py"] = b"changed"
            with self.assertRaises(package.PackageError):
                package.application_sdist(self.sdist(files), root, payloads)
            self.assertNotIn("test_incidental.py", package.ROOT_APPLICATION_TEST_COUNTS)
            test.unlink()
            test.symlink_to(root / "README.md")
            with self.assertRaises(package.PackageError):
                package.application_source_tests(root)

    def test_wheel_checks_exact_metadata_raw_guide_payloads_record_and_links(self) -> None:
        import base64
        import csv
        import hashlib

        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            payloads, source = self.fixture(root)
            prefix = "livekit_agent_ecosystem-0.1.0.dist-info/"
            files = {
                **payloads,
                prefix + "METADATA": source["PKG-INFO"],
                prefix + "WHEEL": b"Wheel-Version: 1.0\n",
                prefix + "top_level.txt": b"services\n",
            }

            def completed(
                values: dict[str, bytes], *, bad_record: bool = False, link: bool = False
            ) -> bytes:
                rows = [
                    [
                        name,
                        "sha256="
                        + base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
                        .rstrip(b"=")
                        .decode(),
                        str(len(raw)),
                    ]
                    for name, raw in values.items()
                ]
                if bad_record:
                    rows[0][1] = "sha256=wrong"
                rows.append([prefix + "RECORD", "", ""])
                records = io.StringIO()
                csv.writer(records).writerows(rows)
                entries = {**values, prefix + "RECORD": records.getvalue().encode()}
                result = io.BytesIO()
                with zipfile.ZipFile(result, "w") as archive:
                    for name, raw in entries.items():
                        info = zipfile.ZipInfo(name)
                        if link and name == "services/__init__.py":
                            info.external_attr = (stat.S_IFLNK | 0o600) << 16
                        archive.writestr(info, raw)
                return result.getvalue()

            packages = retention_tools()[1]
            archive = root / "root.whl"
            archive.write_bytes(completed(files))
            proof = package.application_wheel(
                archive, root, "livekit_agent_ecosystem", payloads, packages
            )
            self.assertEqual(proof["payload_count"], len(payloads))
            self.assertEqual(proof["metadata_sha256"], package.digest(source["PKG-INFO"]))
            for raw in (
                completed({**files, "services/__init__.py": b"changed"}),
                completed(
                    {
                        **files,
                        prefix + "METADATA": source["PKG-INFO"].replace(b"[native]", b"[wrong]"),
                    }
                ),
                completed({**files, prefix + "METADATA": source["PKG-INFO"] + b"changed guide"}),
                completed(files, bad_record=True),
                completed(files, link=True),
                completed({**files, ".env.providers": b"PRIVATE_SYNTHETIC"}),
            ):
                archive.write_bytes(raw)
                with self.subTest(sha=package.digest(raw)), self.assertRaises(packages.GateError):
                    package.application_wheel(
                        archive, root, "livekit_agent_ecosystem", payloads, packages
                    )

    def test_seven_role_driver_has_normal_root_build_pinned_backend_and_retains_partial_artifacts(
        self,
    ) -> None:
        for fail_rebuild in (False, True):
            with (
                self.subTest(fail_rebuild=fail_rebuild),
                tempfile.TemporaryDirectory(dir="/private/tmp") as folder,
            ):
                temporary = Path(folder).resolve()
                root, work, retained, app = (
                    temporary / name for name in ("checkout", "work", "retained", "app")
                )
                for path in (root, work, retained, app):
                    path.mkdir(mode=0o700)
                payloads, source = self.fixture(root)
                source_raw = self.sdist(source)
                sdk = temporary / "consumer/sdk"
                sdk_payloads = {"dist/native.js": b"native", "dist/index.js": b"index"}
                sdk_payloads.update({f"dist/module{i}.js": b"public" for i in range(122)})
                sdk_manifest = b'{"name":"@livekit-ecosystem/channel-continuity","version":"0.1.0"}'
                for name, body in {**sdk_payloads, "package.json": sdk_manifest}.items():
                    package.write(sdk / name, body)
                node = temporary / "node"
                node.write_bytes(b"synthetic declared toolchain")
                descriptor = package.native_sdk_fixture(
                    app, sdk, node, sdk_payloads, sdk_manifest, "0" * 64
                )
                package.write(
                    app / "public-native-sdk-fixture.json", package.json_bytes(descriptor)
                )
                python = temporary / "isolated/bin/python"
                environment = {
                    "PATH": "/usr/bin:/bin",
                    "UV_PYTHON_DOWNLOADS": "never",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
                calls = []

                def command(
                    role: str,
                    argv: list[str],
                    *,
                    cwd: Path,
                    environment: dict[str, str],
                    calls: list[object] = calls,
                    root: Path = root,
                    source_raw: bytes = source_raw,
                    fail_rebuild: bool = fail_rebuild,
                    python: Path = python,
                    app: Path = app,
                    node: Path = node,
                    descriptor: dict[str, Any] = descriptor,
                    payloads: dict[str, bytes] = payloads,
                ) -> bytes:
                    calls.append((role, list(argv), cwd, dict(environment)))
                    self.assertEqual(environment["UV_PYTHON_DOWNLOADS"], "never")
                    if role == "app-build":
                        self.assertEqual(argv[-1], str(root))
                        self.assertIn("--wheel", argv)
                        self.assertIn("--sdist", argv)
                        output = Path(argv[argv.index("--out-dir") + 1])
                        (output / "livekit_agent_ecosystem-0.1.0-py3-none-any.whl").write_bytes(
                            b"synthetic direct wheel"
                        )
                        (output / "livekit_agent_ecosystem-0.1.0.tar.gz").write_bytes(source_raw)
                    elif role == "app-rebuild":
                        self.assertEqual(
                            argv[1:8],
                            [
                                "--no-config",
                                "run",
                                "--offline",
                                "--no-project",
                                "--isolated",
                                "--with",
                                "setuptools==84.2.1",
                            ],
                        )
                        self.assertIn("-I", argv)
                        self.assertEqual(
                            (cwd / "pyproject.toml").read_bytes(),
                            (root / "pyproject.toml").read_bytes(),
                        )
                        self.assertIn('version("setuptools")=="84.2.1"', argv[-2])
                        if fail_rebuild:
                            raise package.PackageError("consumer_failed")
                        (
                            Path(argv[-1]) / "livekit_agent_ecosystem-0.1.0-py3-none-any.whl"
                        ).write_bytes(b"synthetic rebuilt wheel")
                    elif role == "p2-python-build":
                        output = Path(argv[argv.index("--out-dir") + 1])
                        (output / "channel_continuity-0.1.0-py3-none-any.whl").write_bytes(
                            b"synthetic P2 wheel"
                        )
                    elif role == "app-install":
                        self.assertEqual(argv[argv.index("--python") + 1], str(python))
                        self.assertTrue(argv[-1].endswith(".whl[channel-demo]"))
                    elif role == "app-types":
                        self.assertEqual(argv[argv.index("--python-executable") + 1], str(python))
                    elif role == "app-execution":
                        self.assertEqual(argv[:2], [str(python), "-I"])
                        self.assertFalse((app / "services").exists())
                        self.assertEqual(environment["PATH"], str(node.parent) + ":/usr/bin:/bin")
                        observed = package.native_fixture_report(
                            descriptor,
                            package.digest(
                                payloads["services/conversation_agent/assets/manifest.json"]
                            ),
                        )
                        package.write(
                            app / "native-fixture-observed.json", package.json_bytes(observed)
                        )
                        policy, _ = package.child_record(app / "native-child-policy.json")
                        child_proof = child_registry(app / "native-child-groups", policy["nonce"])
                        package.write(
                            app / "native-child-groups-proof.json", package.json_bytes(child_proof)
                        )
                        return package.json_bytes(package.application_expected_report())
                    return b""

                products = ModuleType("synthetic_products")
                products._payload = lambda *args: {
                    f"channel_continuity/p{i}.py": b"fixture\n" for i in range(9)
                }
                parity = {"metadata_sha256": "0" * 64, "payload_count": len(payloads)}
                with (
                    patch.object(package, "application_payload", return_value=payloads),
                    patch.object(package, "application_wheel", return_value=parity),
                    patch(
                        "subprocess.Popen",
                        side_effect=AssertionError("actual compiler or installer"),
                    ),
                ):
                    if fail_rebuild:
                        with self.assertRaisesRegex(package.PackageError, "^consumer_failed$"):
                            package.application_checks(
                                root, work, retained, app, python, environment, command, products
                            )
                    else:
                        result = package.application_checks(
                            root, work, retained, app, python, environment, command, products
                        )
                        self.assertEqual(result["consumer"], package.application_expected_report())
                        self.assertEqual(result["runtime_versions"]["setuptools"], "84.2.1")
                        self.assertEqual(result["runtime_versions"]["aiohttp"], "3.14.5")
                        self.assertEqual(result["runtime_versions"]["h11"], "0.16.0")
                        self.assertEqual(
                            result["root_sdist"]["bound_default_test_sources"],
                            len(package.application_source_tests(root)),
                        )
                        self.assertEqual(
                            tuple(item["role"] for item in result["commands"]),
                            package.ROOT_APPLICATION_ROLES,
                        )
                self.assertEqual(
                    (retained / "root-application/public-native-sdk-fixture.json").read_bytes(),
                    package.json_bytes(descriptor),
                )
                if fail_rebuild:
                    self.assertFalse(
                        (retained / "root-application/native-fixture-observed.json").exists()
                    )
                expected_roles = (
                    package.ROOT_APPLICATION_ROLES[:2]
                    if fail_rebuild
                    else package.ROOT_APPLICATION_ROLES
                )
                self.assertEqual(tuple(item[0] for item in calls), expected_roles)
                for role, argv, cwd, _environment in calls:
                    self.assertEqual(
                        json.loads(
                            (retained / "root-application/commands" / (role + ".json")).read_bytes()
                        ),
                        {"role": role, "argv": argv, "cwd": str(cwd)},
                    )
                archived = retained / "root-application/artifacts/direct"
                self.assertEqual(
                    (archived / "livekit_agent_ecosystem-0.1.0.tar.gz").read_bytes(), source_raw
                )
                self.assertEqual(
                    (archived / "livekit_agent_ecosystem-0.1.0-py3-none-any.whl").read_bytes(),
                    b"synthetic direct wheel",
                )
                if fail_rebuild:
                    self.assertFalse(
                        (retained / "root-application/commands/app-install.json").exists()
                    )


class NativeApplicationFixtures(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.app = self.root / "app"
        self.app.mkdir(mode=0o700)
        self.purelib = self.root / "prefix/lib/python3.14/site-packages"
        self.sdk = self.root / "consumer/sdk"
        self.node = self.root / "node"
        self.node.write_bytes(b"synthetic executable path, never invoked")
        self.payloads = {"dist/native.js": b"native", "dist/index.js": b"index"}
        self.payloads.update({f"dist/public{i}.js": b"export{}" for i in range(122)})
        self.manifest = b'{"name":"@livekit-ecosystem/channel-continuity","version":"0.1.0"}'
        for name, body in {**self.payloads, "package.json": self.manifest}.items():
            package.write(self.sdk / name, body)
        self.asset_name = "services/conversation_agent/assets/manifest.json"
        self.asset = b'{"kind":"synthetic-spoken-fixtures","source":"installed-wheel"}'
        package.write(self.purelib / self.asset_name, self.asset)
        self.expected = {self.asset_name: package.digest(self.asset)}
        self.descriptor = package.native_sdk_fixture(
            self.app, self.sdk, self.node, self.payloads, self.manifest, "0" * 64
        )
        self.write_descriptor(self.descriptor)
        namespace = {
            "Path": Path,
            "os": os,
            "stat": stat,
            "json": json,
            "hashlib": package.hashlib,
            "shutil": SimpleNamespace(which=lambda name: str(self.node)),
        }
        exec(compile(package.NATIVE_APPLICATION_FIXTURES, "native-fixture.py", "exec"), namespace)  # noqa: S102 - trusted generated source with actual isolated data only
        self.prepare = namespace["prepare_native_fixtures"]

    def write_descriptor(self, value: dict[str, Any]) -> None:
        target = self.app / "public-native-sdk-fixture.json"
        if target.exists():
            target.unlink()
        package.write(target, package.json_bytes(value))

    def test_generated_fixture_uses_isolated_public_npm_and_installed_asset_bytes_only(
        self,
    ) -> None:
        with patch("subprocess.Popen", side_effect=AssertionError("unexpected compiler/Node")):
            value = self.prepare(self.app, self.purelib, self.expected)
        expected = package.native_fixture_report(self.descriptor, package.digest(self.asset))
        expected.pop("node_client_exit_and_reap_assertions_passed")
        self.assertEqual(value, expected)
        self.assertNotIn("node_client_exit_and_reap_assertions_passed", value)
        link = self.app / "projects/channel-continuity"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), self.sdk)
        self.assertEqual((self.app / self.asset_name).read_bytes(), self.asset)
        self.assertEqual(stat.S_IMODE((self.app / self.asset_name).stat().st_mode), 0o600)
        self.assertFalse(list((self.app / "services").rglob("*.py")))
        self.assertEqual(
            {
                str(path.relative_to(self.app / "services"))
                for path in (self.app / "services").rglob("*")
                if path.is_file()
            },
            {"conversation_agent/assets/manifest.json"},
        )
        for path in (self.app / "services").rglob("*"):
            if path.is_dir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        self.assertEqual(
            (self.sdk / "dist/native.js").read_bytes(), self.payloads["dist/native.js"]
        )

    def test_changed_installed_public_sdk_byte_is_denied_before_symlink_or_asset_creation(
        self,
    ) -> None:
        (self.sdk / "dist/native.js").write_bytes(b"changed")
        with self.assertRaises(AssertionError):
            self.prepare(self.app, self.purelib, self.expected)
        self.assertFalse((self.app / "projects/channel-continuity").exists())
        self.assertFalse((self.app / "services").exists())
        with self.assertRaises(package.PackageError):
            package.native_sdk_fixture(
                self.app, self.sdk, self.node, self.payloads, self.manifest, "0" * 64
            )

    def test_descriptor_node_version_missing_tool_and_route_changes_are_nonpassing(self) -> None:
        for change in (
            lambda value: value.update(extra="unexpected"),
            lambda value: value.update(node_version="24.22.1"),
            lambda value: value.update(node=str(self.root / "absent-node")),
            lambda value: value.update(package=str(self.root)),
            lambda value: value["payloads"].pop("dist/native.js"),
        ):
            value = copy.deepcopy(self.descriptor)
            change(value)
            self.write_descriptor(value)
            with self.assertRaises(AssertionError):
                self.prepare(self.app, self.purelib, self.expected)
            self.assertFalse((self.app / "projects/channel-continuity").exists())
        self.write_descriptor(self.descriptor)
        namespace = {
            "Path": Path,
            "os": os,
            "stat": stat,
            "json": json,
            "hashlib": package.hashlib,
            "shutil": SimpleNamespace(which=lambda name: None),
        }
        exec(compile(package.NATIVE_APPLICATION_FIXTURES, "native-fixture.py", "exec"), namespace)  # noqa: S102 - trusted generated guard only
        with self.assertRaises(AssertionError):
            namespace["prepare_native_fixtures"](self.app, self.purelib, self.expected)

    def test_changed_installed_asset_manifest_cannot_be_replaced_by_checkout_fixture(self) -> None:
        (self.purelib / self.asset_name).write_bytes(b"changed installed manifest")
        with self.assertRaises(AssertionError):
            self.prepare(self.app, self.purelib, self.expected)
        self.assertFalse((self.app / self.asset_name).exists())
        self.assertFalse(list(self.app.rglob("*.py")))

    def test_host_descriptor_rejects_outside_public_prefix_symlink_payload_and_wrong_inventory(
        self,
    ) -> None:
        for installed, node, payloads, manifest, archive in (
            (self.root, self.node, self.payloads, self.manifest, "0" * 64),
            (self.sdk, self.root / "missing", self.payloads, self.manifest, "0" * 64),
            (self.sdk, self.node, {"dist/native.js": b"native"}, self.manifest, "0" * 64),
            (self.sdk, self.node, self.payloads, self.manifest, "not-a-sha"),
            (self.sdk, self.node, self.payloads, b'{"name":"foreign","version":"0.1.0"}', "0" * 64),
        ):
            with self.assertRaises(package.PackageError):
                package.native_sdk_fixture(self.app, installed, node, payloads, manifest, archive)
        source = self.sdk / "dist/native.js"
        source.unlink()
        source.symlink_to(self.sdk / "dist/index.js")
        with self.assertRaises(package.PackageError):
            package.native_sdk_fixture(
                self.app, self.sdk, self.node, self.payloads, self.manifest, "0" * 64
            )

    def test_fixture_report_keeps_component_scope_distinct_from_full_acceptance(self) -> None:
        value = package.application_expected_report()
        self.assertTrue(value["public_native_fixtures_verified"])
        self.assertEqual(value["native_prepare_node_client_descendants"], 2)
        self.assertEqual(value["descendant_process_group"], "app-execution")
        self.assertEqual(
            (
                value["database_calls"],
                value["rtc_rooms"],
                value["source_actual_assertions"],
                value["installed_actual_assertions"],
            ),
            (0, 0, 0, 0),
        )
        self.assertFalse(value["provider_calls"])
        self.assertEqual(package.plan(root_application=True)["expected_process_groups"], 32)
        self.assertEqual(package.plan(root_application=True)["root_application_groups"], 7)
        execution = package.application_execution()
        self.assertGreater(
            execution.index('native_fixture["node_client_exit_and_reap_assertions_passed"]=True'),
            execution.index("assert sum(counts.values())==764"),
        )


class ArchiveParity(unittest.TestCase):
    def test_npm_payload_bytes_and_distinct_manifest_representations(self) -> None:
        source = b'{"name":"synthetic","exports":{"./result-receiver":"./dist/api.js"}}\n'
        archived = b'{\n  "exports": {"./result-receiver": "./dist/api.js"}, "name": "synthetic"\n}'
        payloads = {"dist/api.js": b"runtime\n", "dist/api.d.ts": b"declare\n"}
        raw = npm(
            {**{"package/" + n: b for n, b in payloads.items()}, "package/package.json": archived}
        )
        proof, actual = package.npm_parity(raw, payloads, source)
        self.assertEqual(actual, archived)
        self.assertEqual(proof["payload_count"], 2)
        self.assertTrue(proof["manifest_semantic_equal"])
        self.assertNotEqual(proof["source_manifest_sha256"], proof["archive_manifest_sha256"])
        self.assertEqual(proof["payloads"]["dist/api.js"], package.digest(payloads["dist/api.js"]))

    def test_npm_changed_payload_manifest_duplicate_extra_and_link_are_denied(self) -> None:
        payloads = {"dist/api.js": b"original"}
        files = {
            "package/dist/api.js": b"original",
            "package/package.json": b'{"name":"synthetic"}',
        }
        mutants = [
            npm({**files, "package/dist/api.js": b"changed"}),
            npm({**files, "package/package.json": b'{"name":"foreign"}'}),
            npm(files, extra=("package/dist/api.js", b"original")),
            npm({**files, "package/extra.js": b"extra"}),
            npm(files, link=True),
        ]
        for raw in mutants:
            with self.subTest(digest=package.digest(raw)), self.assertRaises(package.PackageError):
                package.npm_parity(raw, payloads, files["package/package.json"])

    def test_wheel_runtime_inventory_exact_byte_parity(self) -> None:
        expected = {"installed/api.py": b"x=1\n", "installed/py.typed": b""}
        raw = wheel({**expected, "installed-0.1.0.dist-info/METADATA": b"Version:0.1.0"})
        self.assertEqual(package.wheel_parity(raw, expected, "installed", 2)["payload_count"], 2)
        for mutant in [
            wheel({**expected, "installed/api.py": b"x=2\n"}),
            wheel({**expected, "installed/extra.py": b"x=3\n"}),
            wheel({"installed/api.py": b"x=1\n"}),
        ]:
            with (
                self.subTest(digest=package.digest(mutant)),
                self.assertRaises(package.PackageError),
            ):
                package.wheel_parity(mutant, expected, "installed", 2)

    def test_selected_probe_report_rejects_extra_or_changed_claim(self) -> None:
        fields = {"schema_version": 1, "installed_actual_assertions": 0}
        self.assertEqual(package.selected_report(json.dumps(fields).encode(), fields), fields)
        for raw in [
            b"not-json",
            json.dumps({**fields, "extra": True}).encode(),
            json.dumps({**fields, "installed_actual_assertions": 20}).encode(),
            json.dumps({**fields, "schema_version": True}).encode(),
        ]:
            with self.subTest(raw=raw), self.assertRaises(package.PackageError):
                package.selected_report(raw, fields)


class ProcessGroupEvidence(unittest.TestCase):
    def test_final_owned_fields_form_exact_group_proof_and_corruptions_are_denied(self) -> None:
        outer = SimpleNamespace(children=[])
        nested = SimpleNamespace(children=[], outputs={})
        for role in sorted(package.OUTER_ROLES):
            outer.children.append(
                SimpleNamespace(
                    pid=12000 + len(outer.children),
                    output_directory=Path("/private/tmp/owned") / role,
                    returncode=0,
                    cleanup_failed=False,
                    group_settled=True,
                )
            )
        for number, role in enumerate(package.NESTED_ROLE_ORDER, 1):
            child = SimpleNamespace(
                pid=13000 + number, returncode=0, cleanup_failed=False, group_settled=True
            )
            nested.children.append(child)
            nested.outputs[child.pid] = Path("/private/tmp/owned") / f"{number:02d}-{role}"
        observed = package.observe_process_groups(outer, nested)
        package.validate_process_groups(observed)
        self.assertEqual(len(observed["groups"]), 25)
        self.assertEqual(observed["groups"][0]["owned_pid"], outer.children[0].pid)
        # A retained observation is stable even if an owner object later changes.
        outer.children[0].returncode = 9
        self.assertEqual(observed["groups"][0]["returncode"], 0)
        changes: tuple[Callable[[dict[str, Any]], object], ...] = (
            lambda v: v["groups"].pop(),
            lambda v: v["groups"][0].update(returncode=1),
            lambda v: v["groups"][0].update(returncode=True),
            lambda v: v["groups"][0].update(cleanup_failed=True),
            lambda v: v["groups"][0].update(group_settled=False),
            lambda v: v["groups"][0].update(owned_pid=v["groups"][1]["owned_pid"]),
            lambda v: v["groups"][0].update(owned_pid=True),
            lambda v: v["groups"][0].update(role="foreign"),
            lambda v: v["groups"][0].update(role=[]),
            lambda v: v["groups"][8].update(role="node_example"),
            lambda v: v["groups"][0].update(extra="PRIVATE_SENTINEL"),
        )
        for number, change in enumerate(changes):
            candidate = copy.deepcopy(observed)
            change(candidate)
            with self.subTest(corruption=number), self.assertRaises(package.PackageError) as caught:
                package.validate_process_groups(candidate)
            self.assertEqual(caught.exception.code, "retention_failed")


class PrivateWriteChain(unittest.TestCase):
    def test_nested_write_is_accepted_by_real_physical_inventory_under_ordinary_mask(self) -> None:
        starter, _products = retention_tools()
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            target = root / "inputs/projects/delegation-reliability/tests/consumer.py"
            # A permissive ordinary mask is a regression input, restored before assertions.
            previous = os.umask(0o022)
            try:
                package.write(target, b"synthetic consumer\n")
            finally:
                os.umask(previous)
            for directory in (root, *tuple(target.parents)[:4]):
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            inventory = starter.retained_inventory(root)
            self.assertEqual(set(inventory["files"]), {target.relative_to(root).as_posix()})
            raw = starter.json_bytes(inventory)
            starter.write_private(root / "retained-index.json", raw)
            self.assertEqual(starter.validate_retained_index(root, raw), inventory)

    def test_existing_nonprivate_anchor_is_rejected_without_creating_or_changing_it(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            existing = root / "inputs"
            previous = os.umask(0o022)
            try:
                existing.mkdir(mode=0o755)
            finally:
                os.umask(previous)
            with self.assertRaises(package.PackageError) as caught:
                package.write(existing / "projects/tests/consumer.py", b"synthetic")
            self.assertEqual(caught.exception.code, "invalid_input")
            self.assertEqual(stat.S_IMODE(existing.stat().st_mode), 0o755)
            self.assertFalse((existing / "projects").exists())

    def test_symlink_anchor_is_rejected_without_writing_through_it(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            target, link = root / "other", root / "inputs"
            target.mkdir(mode=0o700)
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(package.PackageError) as caught:
                package.write(link / "projects/tests/consumer.py", b"synthetic")
            self.assertEqual(caught.exception.code, "invalid_input")
            self.assertTrue(link.is_symlink())
            self.assertFalse((target / "projects").exists())
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)


class ExactCopiedInputs(unittest.TestCase):
    def test_copy_is_exact_closed_test_and_contract_inventory_without_products(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            names = ["projects/delegation-reliability/tests/" + n for n in package.HELPER_TESTS]
            names += ["contracts/delegation/" + n for n in package.CONTRACTS]
            for name in names:
                path = root / "source" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((name + "\n").encode())
            result = package.copy_inputs(root / "source", root / "application", root / "retained")
            self.assertEqual(set(result), set(names))
            copied = {
                str(p.relative_to(root / "application"))
                for p in (root / "application").rglob("*")
                if p.is_file()
            }
            self.assertEqual(copied, set(names))
            self.assertEqual(len(copied), 8)
            for name in names:
                self.assertEqual(
                    (root / "application" / name).read_bytes(),
                    (root / "source" / name).read_bytes(),
                )
                self.assertEqual(
                    result[name]["sha256"], package.digest((root / "source" / name).read_bytes())
                )
            self.assertFalse(any("/src/" in n for n in copied))

    def test_symlinked_helper_is_denied_before_copy(self) -> None:
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            first = root / "projects/delegation-reliability/tests" / package.HELPER_TESTS[0]
            first.parent.mkdir(parents=True)
            target = root / "other.py"
            target.write_bytes(b"synthetic")
            first.symlink_to(target)
            with self.assertRaises(package.PackageError):
                package.copy_inputs(root, root / "application", root / "retained")
            self.assertFalse((root / "application").exists())


class PreparationCleanup(unittest.TestCase):
    def test_cleanup_code_getter_failure_cannot_replace_primary_failure(self) -> None:
        class GetterError(RuntimeError):
            @property
            def code(self) -> str:
                raise RuntimeError("PRIVATE_SENTINEL cleanup getter failure")

        class EmptyChildren:
            def __init__(self, *args: object, **kwargs: object) -> None:
                self.count, self.captured, self.reservations = 0, 0, 0
                self.children: list[object] = []

            def close(self) -> None:
                raise GetterError("PRIVATE_SENTINEL cleanup exception")

            def all_settled(self) -> bool:
                return True

        def prepare(*args: object, **kwargs: object) -> object:
            raise package.PackageError("consumer_failed")

        starter = retained_api(SimpleNamespace(Children=EmptyChildren, prepare_installed=prepare))
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            with (
                patch.object(
                    package, "helpers", return_value=(starter, SimpleNamespace(), SimpleNamespace())
                ),
                patch.object(package, "source_snapshot", return_value={"synthetic": "0"}),
                patch("subprocess.Popen", side_effect=AssertionError("process started")),
            ):
                value = package.run(root, root / "primary-failure.json")
            self.assertEqual(value["status"], "failed")
            self.assertEqual(value["code"], "consumer_failed")
            self.assertEqual(value["failure_stage"], "p2_prepare_installed")
            self.assertEqual(value["child_commands"], 0)
            self.assertTrue(value["cleanup_complete"])
            self.assertEqual(
                value["cleanup_errors"], [{"stage": "outer_cleanup", "code": "package_failed"}]
            )
            self.assertEqual(value["proof"]["ownership"]["cleanup_errors"], value["cleanup_errors"])
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(value))
            self.assertEqual(json.loads((root / "primary-failure.json").read_bytes()), value)

    def test_failed_prepare_captures_late_settled_streams_before_work_removal(self) -> None:
        owners: list[Children] = []

        class Children:
            def __init__(self, directory: Path, *args: object, **kwargs: object) -> None:
                self.directory = directory
                self.count, self.captured, self.reservations = 1, 0, 16384
                self.closed = False
                self.children = [
                    SimpleNamespace(
                        pid=12001,
                        output_directory=directory / "compile",
                        returncode=None,
                        cleanup_failed=False,
                        group_settled=False,
                    )
                ]
                self.capture_calls = 0
                owners.append(self)

            def close(self) -> None:
                self.closed = True
                self.children[0].returncode = 7
                self.children[0].group_settled = True

            def capture(self, child: SimpleNamespace) -> tuple[bytes, bytes]:
                self.capture_calls += 1
                raw = (
                    (self.directory / "compile/stdout.bin").read_bytes(),
                    (self.directory / "compile/stderr.bin").read_bytes(),
                )
                self.captured = sum(map(len, raw))
                self.reservations = 0
                return raw

            def all_settled(self) -> bool:
                return self.closed

        def prepare(root: Path, work: Path, artifacts: Path, children: Children) -> object:
            package.write(children.directory / "compile/stdout.bin", b"retained")
            package.write(children.directory / "compile/stderr.bin", b"")
            raise package.PackageError("consumer_failed")

        starter = retained_api(SimpleNamespace(Children=Children, prepare_installed=prepare))
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            target = Path(folder).resolve() / "failed.json"
            with (
                patch.object(
                    package, "helpers", return_value=(starter, SimpleNamespace(), SimpleNamespace())
                ),
                patch.object(package, "source_snapshot", return_value={"f": "0"}),
            ):
                value = package.run(Path(folder).resolve(), target)
            self.assertTrue(owners[0].closed)
            self.assertEqual(owners[0].capture_calls, 1)
            self.assertEqual((owners[0].captured, owners[0].reservations), (8, 0))
            self.assertEqual(value["status"], "failed")
            self.assertEqual(value["code"], "consumer_failed")
            self.assertEqual(value["failure_stage"], "p2_prepare_installed")
            self.assertTrue(value["cleanup_complete"])
            self.assertIsNone(value["proof"]["ownership"]["retained_work"])
            self.assertEqual(
                (
                    target.with_name("failed-artifacts") / "outer-commands/compile/stdout.bin"
                ).read_bytes(),
                b"retained",
            )
            self.assertEqual(json.loads(target.read_bytes()), value)
            index = target.with_name("failed-artifacts") / "retained-index.json"
            self.assertEqual(value["retained_index_sha256"], package.digest(index.read_bytes()))
            starter.validate_retained_index(index.parent, index.read_bytes())
            groups = index.parent / "process-groups.json"
            self.assertEqual(value["process_groups_sha256"], package.digest(groups.read_bytes()))
            self.assertIn("process-groups.json", json.loads(index.read_bytes())["files"])
            original_starter = retention_tools()[0]
            with (
                patch.object(
                    package, "helpers", return_value=(starter, SimpleNamespace(), SimpleNamespace())
                ),
                patch.object(package, "source_snapshot", return_value={"f": "0"}),
                patch.object(
                    starter,
                    "retained_inventory",
                    side_effect=original_starter.GateError("unsafe_path"),
                ),
            ):
                failed_index = package.run(
                    Path(folder).resolve(), Path(folder).resolve() / "index-failure.json"
                )
            self.assertEqual(failed_index["code"], "consumer_failed")
            self.assertEqual(failed_index["failure_stage"], "p2_prepare_installed")
            self.assertIn(
                {"stage": "retained_index", "code": "retention_failed"},
                failed_index["cleanup_errors"],
            )
            self.assertEqual(failed_index["proof"]["ownership"]["cleanup_errors"], [])
            saved_ownership = json.loads(
                (Path(folder) / "index-failure-artifacts/ownership.json").read_bytes()
            )
            self.assertEqual(saved_ownership, failed_index["proof"]["ownership"])
            self.assertIsNone(failed_index["retained_index_sha256"])

    def test_unsettled_outer_probe_withholds_nested_dependency_cleanup_and_retains_primary(
        self,
    ) -> None:
        self._assert_nested_failure("outer_unsettled")

    def test_marked_partial_constructor_owner_is_registered_and_cleaned_without_full_methods(
        self,
    ) -> None:
        self._assert_nested_failure("marked_constructor")

    def test_unmarked_partial_constructor_owner_stays_unknown_and_withholds_outer_removal(
        self,
    ) -> None:
        self._assert_nested_failure("unknown_constructor")

    def _assert_nested_failure(self, scenario: str) -> None:
        assert scenario in {"outer_unsettled", "marked_constructor", "unknown_constructor"}
        owners: list[Children] = []
        nested_owners: list[Nested] = []
        sha = "0" * 64

        class Children:
            def __init__(self, directory: Path, *args: object, **kwargs: object) -> None:
                self.count, self.captured, self.reservations = 4, 0, 0
                self.children: list[object] = []
                self.close_called = False
                owners.append(self)

            def start(self, role: str, *args: object, **kwargs: object) -> SimpleNamespace:
                self.count += 1
                return SimpleNamespace(role=role)

            def finish(self, child: SimpleNamespace) -> bytes:
                if child.role == "p2-result-codecs":
                    return bytes(
                        package.json_bytes(
                            {
                                "schema_version": 1,
                                "status": "passed",
                                "private_npm_paths": True,
                                "imports_no_IO": True,
                                "canonical_equal": True,
                                "negative_cases": 9,
                                "original_result_sha": sha,
                                "notice_hash_separate": True,
                            }
                        )
                    )
                return b""

            def close(self) -> None:
                self.close_called = True

            def all_settled(self) -> bool:
                return scenario != "outer_unsettled"

        class Nested:
            def __init__(self, root: Path, target: Path, **kwargs: object) -> None:
                self.commands, self.captured = 0, 0
                self.reservations: dict[int, int] = {}
                if scenario == "outer_unsettled":
                    self.work = root / "nested-owned"
                    self.work.mkdir()
                else:
                    self.work = Path(
                        tempfile.mkdtemp(prefix="p3-standalone-package-", dir="/private/tmp")
                    ).resolve()
                    if scenario == "marked_constructor":
                        package.write(self.work / "owned-marker", b"p3-standalone-package-v1\n")
                self.cleanup_called = False
                nested_owners.append(self)
                if scenario != "outer_unsettled":
                    raise package.PackageError("consumer_failed")

            def offline(self) -> None:
                raise package.PackageError("consumer_failed")

            def cleanup_resources(self) -> None:
                self.cleanup_called = True
                shutil.rmtree(self.work)

        def prepare(
            root: Path, work: Path, artifacts: Path, children: Children
        ) -> dict[str, object]:
            payloads = {f"dist/{n}.js": b"synthetic" for n in range(124)}
            manifest = b'{"name":"synthetic"}'
            archive = work / "package.tgz"
            archive.write_bytes(
                npm(
                    {
                        **{"package/" + n: b for n, b in payloads.items()},
                        "package/package.json": manifest,
                    }
                )
            )
            consumer = work / "consumer"
            consumer.mkdir(mode=0o700)
            installed = consumer / "node_modules/@livekit-ecosystem/channel-continuity"
            installed.mkdir(parents=True)
            (installed / "package.json").write_bytes(manifest)
            return {
                "payloads": payloads,
                "archive": archive,
                "consumer": consumer,
                "node": Path("/usr/bin/false"),
            }

        starter = retained_api(
            SimpleNamespace(
                Children=Children,
                prepare_installed=prepare,
                MAX_STREAM_BYTES=8192,
                offline_environment=dict,
            )
        )
        with tempfile.TemporaryDirectory(dir="/private/tmp") as folder:
            root = Path(folder).resolve()
            manifest = root / "projects/channel-continuity/package.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_bytes(b'{"name":"synthetic"}')
            wire = root / "contracts/delegation/result-receiver-v1.json"
            wire.parent.mkdir(parents=True)
            wire.write_bytes(
                package.json_bytes({"intent_canonical": json.dumps({"result_sha256": sha})})
            )
            target = root / "failed.json"
            work = None
            try:
                with (
                    patch.object(
                        package,
                        "helpers",
                        return_value=(
                            starter,
                            SimpleNamespace(ScopedPackageRun=Nested),
                            retention_tools()[1],
                        ),
                    ),
                    patch.object(package, "source_snapshot", return_value={"f": "0"}),
                ):
                    value = package.run(root, target)
                owned = value["proof"]["ownership"]
                work = None if owned["retained_work"] is None else Path(owned["retained_work"])
                self.assertTrue(owners[0].close_called)
                self.assertFalse(nested_owners[0].cleanup_called)
                self.assertEqual(value["status"], "failed")
                self.assertEqual(value["code"], "consumer_failed")
                self.assertEqual(value["failure_stage"], "p3_offline_builder")
                self.assertEqual(value["cleanup_complete"], scenario == "marked_constructor")
                self.assertEqual(owned["outer_settled"], scenario != "outer_unsettled")
                self.assertEqual(
                    owned["nested_construction_complete"], scenario == "outer_unsettled"
                )
                self.assertEqual(
                    owned["nested_ownership_unknown"], scenario == "unknown_constructor"
                )
                if scenario == "marked_constructor":
                    self.assertTrue(owned["nested_partial_cleanup_verified"])
                    self.assertIsNone(work)
                    self.assertFalse(nested_owners[0].work.exists())
                else:
                    assert work is not None
                    self.assertTrue(work.exists())
                    self.assertTrue(nested_owners[0].work.exists())
                    self.assertEqual(
                        (work / "owned-marker").read_bytes(), b"p2-result-package-bridge-v1\n"
                    )
                if scenario == "unknown_constructor":
                    self.assertFalse(owned["nested_partial_cleanup_verified"])
                    self.assertIn(
                        {"stage": "nested_partial_cleanup", "code": "cleanup_incomplete"},
                        owned["cleanup_errors"],
                    )
            finally:
                if work is not None:
                    self.assertEqual(work.parent, Path("/private/tmp"))
                    self.assertTrue(work.name.startswith("p2-result-installed-"))
                    shutil.rmtree(work)
                if scenario != "outer_unsettled" and nested_owners:
                    allocated = nested_owners[0].work
                    if allocated.exists():
                        self.assertEqual(allocated.parent, Path("/private/tmp"))
                        self.assertTrue(allocated.name.startswith("p3-standalone-package-"))
                        shutil.rmtree(allocated)


class RetainedEvidence(unittest.TestCase):
    def test_existing_physical_index_binds_bytes_names_and_its_own_control_file(self) -> None:
        starter, _products = retention_tools()
        for corruption in ("bytes", "extra", "index"):
            with (
                self.subTest(corruption=corruption),
                tempfile.TemporaryDirectory(dir="/private/tmp") as folder,
            ):
                root = Path(folder).resolve()
                starter.write_private(root / "proof.json", b'{"status":"passed"}')
                raw = starter.json_bytes(starter.retained_inventory(root))
                starter.write_private(root / "retained-index.json", raw)
                starter.validate_retained_index(root, raw)
                if corruption == "bytes":
                    (root / "proof.json").write_bytes(b'{"status":"failed"}')
                elif corruption == "extra":
                    starter.write_private(root / "foreign.json", b"{}")
                else:
                    (root / "retained-index.json").write_bytes(b"{}")
                with self.assertRaises(starter.GateError):
                    starter.validate_retained_index(root, raw)

    def test_existing_physical_inventory_enforces_aggregate_size_and_private_file_mode(
        self,
    ) -> None:
        starter, _products = retention_tools()
        for corruption in ("size", "mode"):
            with (
                self.subTest(corruption=corruption),
                tempfile.TemporaryDirectory(dir="/private/tmp") as folder,
            ):
                root = Path(folder).resolve()
                starter.write_private(root / "a.bin", b"a" * 40)
                starter.write_private(root / "b.bin", b"b" * 40)
                if corruption == "size":
                    with (
                        patch.object(starter, "MAX_EVIDENCE_BYTES", 64),
                        self.assertRaises(starter.GateError),
                    ):
                        starter.retained_inventory(root)
                else:
                    (root / "b.bin").chmod(0o644)
                    with self.assertRaises(starter.GateError):
                        starter.retained_inventory(root)


class ApplicationChildProofTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.directory = self.root / "children"
        self.nonce = "a" * 32
        self.proof = child_registry(self.directory, self.nonce)

    def rewrite(self, name, **change):
        path = self.directory / "child-01" / name
        value = json.loads(path.read_bytes())
        value.update(change)
        path.write_bytes(package.json_bytes(value))

    def test_exact_ten_receipts_are_private_retained_and_join_actual_owner_scope(self):
        retained = self.root / "retained"
        proof = package.application_child_records(
            self.directory, self.nonce, complete=True, parent_pid=22000, retained=retained
        )
        self.assertEqual(proof, self.proof)
        self.assertEqual(len(list(retained.rglob("*.json"))), 40)
        self.assertTrue(
            all(
                p.stat().st_size <= 512 and stat.S_IMODE(p.stat().st_mode) == 0o600
                for p in retained.rglob("*.json")
            )
        )
        package.validate_child_group_entries(proof["groups"], 22000)

    def test_wrong_nonce_parent_pid_and_missing_or_extra_slot_never_qualify(self):
        for nonce, parent in [("b" * 32, 22000), (self.nonce, 22001)]:
            with self.subTest(nonce=nonce, parent=parent), self.assertRaises(package.PackageError):
                package.application_child_records(
                    self.directory, nonce, complete=True, parent_pid=parent
                )
        (self.directory / "child-10/settled.json").unlink()
        with self.assertRaises(package.PackageError):
            package.application_child_records(self.directory, self.nonce, complete=True)
        (self.directory / "child-11").mkdir(mode=0o700)
        with self.assertRaises(package.PackageError):
            package.application_child_records(self.directory, self.nonce, complete=False)

    def test_false_drain_foreign_identity_bool_and_unexpected_exit_are_rejected(self):
        changes = [
            {"directReaped": False},
            {"pipesDrained": False},
            {"groupAbsent": False},
            {"schemaVersion": True},
            {"pid": True},
            {"pgid": 23002},
            {"returncode": 143},
            {"extra": "PRIVATE_REGISTRY_BODY"},
        ]
        path = self.directory / "child-01/settled.json"
        original = path.read_bytes()
        for change in changes:
            path.write_bytes(original)
            self.rewrite("settled.json", **change)
            with self.subTest(change=change), self.assertRaises(package.PackageError):
                package.application_child_records(self.directory, self.nonce, complete=True)

    def test_duplicate_test_group_cannot_replace_another_case(self):
        first = json.loads((self.directory / "child-01/descriptor.json").read_bytes())
        second = self.directory / "child-02/descriptor.json"
        value = json.loads(second.read_bytes())
        value["testId"] = first["testId"]
        second.write_bytes(package.json_bytes(value))
        with self.assertRaises(package.PackageError):
            package.application_child_records(self.directory, self.nonce, complete=True)

    def test_oversize_duplicate_link_fifo_or_foreign_permissions_fail_without_blocking(self):
        path = self.directory / "child-01/go.json"
        original = path.read_bytes()
        for raw in [b"x" * 513, b'{"schemaVersion":1,"schemaVersion":1}']:
            path.write_bytes(raw)
            with self.subTest(raw=raw[:10]), self.assertRaises(package.PackageError):
                package.child_record(path)
        path.write_bytes(original)
        path.chmod(0o644)
        with self.assertRaises(package.PackageError):
            package.child_record(path)
        path.chmod(0o600)
        hard = path.with_name("extra-link.json")
        os.link(path, hard)
        with self.assertRaises(package.PackageError):
            package.child_record(path)
        hard.unlink()
        path.unlink()
        path.symlink_to(self.directory / "child-02/go.json")
        with self.assertRaises(package.PackageError):
            package.child_record(path)
        path.unlink()
        os.mkfifo(path, 0o600)
        with self.assertRaises(package.PackageError):
            package.child_record(path)

    def test_receipt_rewrite_during_read_is_rejected(self):
        path = self.directory / "child-01/go.json"
        original = os.fdopen

        class ChangedRead:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.stream.close()

            def fileno(self):
                return self.stream.fileno()

            def read(self, maximum):
                raw = self.stream.read(maximum)
                path.write_bytes(raw + b"\n")
                return raw

        with (
            patch.object(
                package.os,
                "fdopen",
                side_effect=lambda fd, *args, **kwargs: ChangedRead(original(fd, *args, **kwargs)),
            ),
            self.assertRaises(package.PackageError),
        ):
            package.child_record(path)

    def test_partial_settled_receipts_allow_cleanup_but_cannot_pass_full_qualification(self):
        for number in range(4, 11):
            shutil.rmtree(self.directory / ("child-" + str(number).zfill(2)))
        partial = package.application_child_records(
            self.directory, self.nonce, complete=False, parent_pid=22000
        )
        self.assertEqual(len(partial["groups"]), 3)
        with self.assertRaises(package.PackageError):
            package.application_child_records(self.directory, self.nonce, complete=True)
        with self.assertRaises(package.PackageError):
            package.validate_child_group_entries(partial["groups"], 22000)

    def test_unresolved_registration_retains_work_and_never_authorizes_pid_actions(self):
        work = self.root / "work"
        app = work / "p3-application"
        package.private_parents(app)
        package.write(
            app / "native-child-policy.json",
            package.json_bytes({"schemaVersion": 1, "nonce": self.nonce}),
        )
        shutil.copytree(self.directory, app / "native-child-groups")
        (app / "native-child-groups/child-01/settled.json").unlink()
        owner = SimpleNamespace(output_directory=Path("/private/tmp/app-execution"), pid=22000)
        with (
            patch.object(package.os, "killpg", side_effect=AssertionError("no PID action")),
            patch.object(package.shutil, "rmtree", side_effect=AssertionError("retain state")),
            self.assertRaises(package.PackageError),
        ):
            package.application_child_cleanup(
                work, self.root / "retained", SimpleNamespace(children=[owner])
            )
        self.assertTrue(work.exists())
        self.assertTrue((app / "native-child-groups/child-01/started.json").exists())

    def test_child_bootstrap_requires_go_and_never_runs_bad_control(self):
        from tests.test_channel_policy_native_worker_process import (
            ChildGroupRecords,
            child_bootstrap,
        )

        for bad in (None, "wrong-nonce", "expired"):
            directory = self.root / ("actual-" + str(bad))
            records = ChildGroupRecords(directory, "b" * 32)
            marker = self.root / ("executed-" + str(bad))
            program = "from pathlib import Path;Path(" + repr(str(marker)) + ').write_text("bad")'
            slot = records.allocate(
                "tests.test_channel_policy_native_worker_process.WorkerProcessTests.test_original_venv_path_fixed_role_environment_and_real_reap",
                program,
            )
            if bad == "expired":
                descriptor = records.read(slot, "descriptor.json")
                descriptor["lifetimeDeadlineNs"] = 1
                (slot / "descriptor.json").write_bytes(package.json_bytes(descriptor))
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    child_bootstrap(program, slot, records.nonce, os.getpid()),
                ],
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                until = time.monotonic() + 1
                while (
                    records.read(slot, "started.json") is None
                    and process.poll() is None
                    and time.monotonic() < until
                ):
                    time.sleep(0.001)
                if bad == "wrong-nonce":
                    records.write(
                        slot,
                        "go.json",
                        {
                            "schemaVersion": 1,
                            "nonce": "c" * 32,
                            "slot": slot.name,
                            "pid": process.pid,
                            "pgid": process.pid,
                        },
                    )
                process.communicate(timeout=2)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(marker.exists())
                with self.assertRaises(ProcessLookupError):
                    os.killpg(process.pid, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=2)


if __name__ == "__main__":
    unittest.main()
