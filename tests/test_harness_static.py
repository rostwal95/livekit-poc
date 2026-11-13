"""Negative fixtures verify that structural checks reject architectural drift."""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness.static_check import (
    ContractError,
    changed_modules,
    git_changed_paths,
    load_contracts,
    main,
    run_tests,
    safe_path,
)


class StructuralHarnessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for directory in (
            "harness/modules",
            "harness/rules",
            "tests",
            "code",
            "local-setup",
            "services/rtc_agent",
            "apps/local-console/src",
            "contracts/local-transport",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / "README.md").write_text(
            "# Fixture documentation\n\nStatus: Active\nLast reviewed: 9 November 2026\n\n## Overview\nFixture.\n"
        )
        (self.root / "harness/documentation.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "include": ["README.md", "docs/decisions/*.md"],
                    "requiredDocuments": ["README.md"],
                    "statuses": ["Active"],
                    "roles": [
                        {
                            "name": "readme",
                            "patterns": ["README.md"],
                            "requiredHeadings": ["Overview"],
                        }
                    ],
                    "forbiddenTerms": [],
                    "forbiddenPatterns": [],
                }
            )
        )
        (self.root / "code/domain.py").write_text("from dataclasses import dataclass\n")
        (self.root / "tests/test_example.py").write_text("# fixture target\n")
        for relative, content in {
            "local-setup/stack.py": "from pathlib import Path\n",
            "services/rtc_agent/worker.py": "from livekit import rtc\n",
            "apps/local-console/src/main.ts": "import { Room } from 'livekit-client';\n",
            "contracts/local-transport/diagnostics.json": '{"type":"audio.frames"}\n',
        }.items():
            (self.root / relative).write_text(content)
        self.foundation = {
            "schemaVersion": 1,
            "ownedPaths": ["services", "apps", "local-setup", "contracts"],
            "sourceRoots": [
                {"path": name, "status": "implemented"}
                for name in (
                    "services/rtc_agent",
                    "apps/local-console/src",
                    "local-setup",
                    "contracts",
                )
            ],
            "requiredFiles": [
                "services/rtc_agent/worker.py",
                "apps/local-console/src/main.ts",
                "local-setup/stack.py",
                "contracts/local-transport/diagnostics.json",
            ],
            "requiredDocuments": ["README.md"],
            "forbiddenImports": [
                {
                    "roots": ["local-setup/stack.py"],
                    "modules": ["httpx", "livekit", "services"],
                },
                {"roots": ["services/rtc_agent"], "modules": ["continuity_lab.store"]},
                {
                    "roots": ["apps/local-console/src"],
                    "modules": ["services", "continuity_lab"],
                },
                {"roots": ["contracts"], "modules": ["services", "continuity_lab"]},
            ],
        }
        self.save_foundation()
        self.configs = {}
        catalog = {
            "projects": {},
            "runners": {
                "BASE-01": {
                    "project": "p1",
                    "kind": "unittest_discovery",
                    "startDirectory": "tests",
                    "pattern": "test_example.py",
                }
            },
        }
        for number in range(1, 4):
            module = f"p{number}"
            source = f"scope{number}.md"
            (self.root / source).write_text(f"| P{number}-01 | scenario | assertion |\n")
            self.configs[module] = {
                "schemaVersion": 1,
                "module": module,
                "implementationStatus": "partial" if number == 1 else "planned",
                "owners": ["fixture"],
                "ownedPaths": [f"project{number}", source],
                "sourceRoots": [
                    {
                        "path": "code" if number == 1 else f"project{number}/src",
                        "status": "implemented" if number == 1 else "planned",
                    }
                ],
                "requiredDocuments": ["README.md"],
                "forbiddenImports": [{"roots": ["code"], "modules": ["livekit", "other_project"]}]
                if number == 1
                else [],
                "acceptance": {"scopeDocument": source, "prefix": f"P{number}-"},
                "testMappings": [
                    {
                        "caseId": "BASE-01",
                        "status": "implemented",
                        "testFiles": ["tests/test_example.py"],
                    }
                ]
                if number == 1
                else [],
            }
            catalog["projects"][module] = {"scope": source}
        (self.root / "harness/catalog.json").write_text(json.dumps(catalog))
        self.save_configs()
        (self.root / "harness/rules/static.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "groups": ["docs", "boundary", "contract"],
                    "sourceSuffixes": [".py", ".ts"],
                    "ignoredDirectories": ["__pycache__"],
                }
            )
        )

    def save_foundation(self):
        (self.root / "harness/foundation.json").write_text(json.dumps(self.foundation))

    def save_configs(self):
        for module, config in self.configs.items():
            (self.root / f"harness/modules/{module}.json").write_text(json.dumps(config))

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(args), root=self.root)
        return code, json.loads(output.getvalue())

    def test_clean_structure_passes_without_certifying_planned_features(self):
        code, result = self.cli()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "structural_checks_passed")
        self.assertEqual(result["productAcceptance"], "not_certified")
        self.assertEqual(result["modules"][1]["implementationStatus"], "planned")
        self.assertEqual(result["modules"][1]["plannedAcceptanceCases"], 1)
        self.assertEqual(len(result["modules"]), 3)
        self.assertEqual(result["foundation"]["policy"], "harness/foundation.json")
        self.assertEqual(len(result["foundation"]["sources"]), 4)

    def test_foundation_manifest_deletion_fails_closed_for_focused_checks(self):
        (self.root / "harness/foundation.json").unlink()
        code, result = self.cli("--module", "p2", "--groups", "boundary")
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "invalid")
        self.assertIn("foundation.json", result["error"])

    def test_foundation_manifest_rejects_duplicate_unknown_and_invalid_fields(self):
        path = self.root / "harness/foundation.json"
        path.write_text('{"schemaVersion":1,"schemaVersion":1}')
        self.assertEqual(self.cli()[0], 2)
        for variant in (
            {**self.foundation, "unexpected": True},
            {**self.foundation, "schemaVersion": True},
            {**self.foundation, "ownedPaths": []},
            {**self.foundation, "sourceRoots": []},
            {**self.foundation, "sourceRoots": self.foundation["sourceRoots"] * 2},
            {**self.foundation, "requiredFiles": self.foundation["requiredFiles"] * 2},
            {**self.foundation, "forbiddenImports": "not-a-list"},
        ):
            with self.subTest(variant=variant):
                path.write_text(json.dumps(variant))
                code, result = self.cli()
                self.assertEqual(code, 2)
                self.assertEqual(result["status"], "invalid")
        self.save_foundation()

    def test_foundation_required_entrypoints_cannot_be_missing_empty_or_directories(
        self,
    ):
        path = self.root / "apps/local-console/src/main.ts"
        original = path.read_text()
        path.unlink()
        for replacement in ("missing", "empty", "directory"):
            with self.subTest(replacement=replacement):
                if replacement == "empty":
                    path.touch()
                elif replacement == "directory":
                    path.mkdir()
                code, result = self.cli("--module", "p3", "--groups", "boundary")
                self.assertEqual(code, 1)
                self.assertTrue(
                    any(
                        "required foundation file" in issue["message"]
                        for issue in result["violations"]
                    )
                )
                if path.is_dir():
                    path.rmdir()
                elif path.exists():
                    path.unlink()
        path.write_text(original)

    def test_foundation_planned_roots_are_allowed_but_implemented_roots_need_content(
        self,
    ):
        self.foundation["sourceRoots"].append({"path": "apps/future/src", "status": "planned"})
        self.save_foundation()
        self.assertEqual(self.cli()[0], 0)
        self.foundation["sourceRoots"][-1]["status"] = "implemented"
        self.save_foundation()
        code, result = self.cli()
        self.assertEqual(code, 1)
        self.assertTrue(
            any(
                "implemented foundation source" in issue["message"]
                for issue in result["violations"]
            )
        )

    def test_foundation_blocks_bootstrap_worker_browser_and_contract_import_drift(self):
        changes = (
            ("local-setup/stack.py", "import httpx\n"),
            ("local-setup/stack.py", "from livekit import api\n"),
            ("services/rtc_agent/worker.py", "from continuity_lab import store\n"),
            (
                "apps/local-console/src/main.ts",
                "import { secret } from '../../../services/control_api/settings';\n",
            ),
            ("contracts/orchestration.py", "from services.control_api import app\n"),
        )
        for relative, content in changes:
            with self.subTest(relative=relative, content=content):
                path = self.root / relative
                original = path.read_text() if path.exists() else None
                path.write_text(content)
                code, result = self.cli("--module", "p2", "--groups", "boundary")
                self.assertEqual(code, 1)
                self.assertTrue(
                    any(
                        issue.get("area") == "foundation"
                        and "forbidden dependency" in issue["message"]
                        for issue in result["violations"]
                    )
                )
                if original is None:
                    path.unlink()
                else:
                    path.write_text(original)

    def test_relative_python_import_cannot_bypass_a_foundation_boundary(self):
        self.foundation["forbiddenImports"][1]["modules"].append("services.control_api.app")
        self.save_foundation()
        (self.root / "services/rtc_agent/worker.py").write_text("from ..control_api import app\n")
        code, result = self.cli("--groups", "boundary")
        self.assertEqual(code, 1)
        self.assertTrue(
            any("services.control_api.app" in issue["message"] for issue in result["violations"])
        )

    def test_foundation_paths_owners_and_boundary_roots_are_validated(self):
        variants = (
            {**self.foundation, "requiredFiles": ["../secret"]},
            {
                **self.foundation,
                "sourceRoots": [{"path": "unclaimed", "status": "implemented"}],
            },
            {**self.foundation, "requiredFiles": ["unclaimed/worker.py"]},
            {
                **self.foundation,
                "forbiddenImports": [{"roots": ["outside"], "modules": ["httpx"]}],
            },
        )
        for variant in variants:
            with self.subTest(variant=variant):
                (self.root / "harness/foundation.json").write_text(json.dumps(variant))
                self.assertEqual(self.cli()[0], 2)
        self.save_foundation()
        (self.root / "escape").symlink_to(self.root.parent, target_is_directory=True)
        self.foundation["requiredFiles"] = ["escape/private.py"]
        self.foundation["ownedPaths"].append("escape")
        self.save_foundation()
        code, result = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("escapes repository", result["error"])

    def test_foundation_document_requirement_applies_even_without_a_corpus_match(self):
        self.foundation["requiredDocuments"].append("local-setup/README.md")
        self.save_foundation()
        code, result = self.cli("--module", "p1", "--groups", "docs")
        self.assertEqual(code, 1)
        self.assertTrue(
            any(
                "required foundation document" in issue["message"] for issue in result["violations"]
            )
        )

    def test_architecture_decisions_are_discovered_and_metadata_checked(self):
        directory = self.root / "docs/decisions"
        directory.mkdir(parents=True)
        path = directory / "0001-fixture.md"
        path.write_text("# A decision\n\nStatus: Active\nLast reviewed: 9 November 2026\n")
        self.assertEqual(self.cli("--groups", "docs")[0], 0)
        path.write_text("# A decision with missing metadata\n")
        code, result = self.cli("--groups", "docs")
        self.assertEqual(code, 1)
        self.assertTrue(
            any(
                issue.get("path") == "docs/decisions/0001-fixture.md"
                for issue in result["violations"]
            )
        )

    def test_missing_required_document_fails(self):
        (self.root / "README.md").unlink()
        code, result = self.cli("--module", "p2", "--groups", "docs")
        self.assertEqual(code, 1)
        self.assertIn("required document", result["violations"][0]["message"])

    def test_forbidden_python_and_typescript_imports_fail(self):
        for name, content in (
            ("domain.py", "from livekit import agents\n"),
            ("domain.ts", "import { value } from '../other_project/store';\n"),
        ):
            with self.subTest(name=name):
                (self.root / "code" / name).write_text(content)
                code, result = self.cli("--module", "p1", "--groups", "boundary")
                self.assertEqual(code, 1)
                self.assertTrue(
                    any(
                        "forbidden dependency" in issue["message"] for issue in result["violations"]
                    )
                )
                (self.root / "code" / name).unlink()

    def test_standalone_examples_require_public_imports_and_present_sources(self):
        rules_path = self.root / "harness/rules/static.json"
        rules = json.loads(rules_path.read_text())
        rules["sourceSuffixes"].append(".mjs")
        rules_path.write_text(json.dumps(rules))
        for module, suffix in (("p2", ".ts"), ("p3", ".mjs")):
            with self.subTest(module=module):
                directory = self.root / f"project{module[1:]}/examples"
                directory.mkdir(parents=True)
                example = directory / ("standalone" + suffix)
                public = "import { example } from '@fixture/public-library';\n"
                example.write_text(public)
                self.configs[module]["implementationStatus"] = "partial"
                self.configs[module]["sourceRoots"].append(
                    {"path": str(directory.relative_to(self.root)), "status": "implemented"}
                )
                self.configs[module]["forbiddenImports"].append(
                    {
                        "roots": [str(directory.relative_to(self.root))],
                        "modules": ["other_project"],
                    }
                )
                self.save_configs()
                self.assertEqual(
                    self.cli("--module", module, "--groups", "boundary,contract")[0], 0
                )
                example.write_text("import { privateStore } from '../../other_project/store';\n")
                code, result = self.cli("--module", module, "--groups", "boundary,contract")
                self.assertEqual(code, 1)
                self.assertTrue(
                    any(
                        "forbidden dependency" in issue["message"] for issue in result["violations"]
                    )
                )
                example.write_text(public)
                self.assertEqual(
                    self.cli("--module", module, "--groups", "boundary,contract")[0], 0
                )
                example.unlink()
                code, result = self.cli("--module", module, "--groups", "boundary,contract")
                self.assertEqual(code, 1)
                self.assertTrue(
                    any(
                        "implemented source missing" in issue["message"]
                        for issue in result["violations"]
                    )
                )

    def test_coordinator_public_work_api_does_not_allow_storage_internals(self):
        self.configs["p1"]["forbiddenImports"][0]["modules"] = [
            "continuity_lab.work_store",
            "continuity_lab.work_schema",
            "continuity_lab.execution_store",
            "continuity_lab.issued_models",
            "continuity_lab.action_store",
            "continuity_lab.delivery_store",
            "continuity_lab.result_feed_store",
            "continuity_lab.result_feed_models",
        ]
        self.save_configs()
        source = self.root / "code/domain.py"
        source.write_text("from continuity_lab.work_api import WorkPayload\n")
        self.assertEqual(self.cli("--module", "p1", "--groups", "boundary")[0], 0)
        for statement in (
            "from continuity_lab import work_store\n",
            "from continuity_lab.work_schema import validate_work_schema\n",
            "from continuity_lab.execution_store import ExecutionStore\n",
            "from continuity_lab import issued_models\n",
            "from continuity_lab.action_store import ActionStore\n",
            "from continuity_lab.delivery_store import DeliveryStore\n",
            "from continuity_lab.result_feed_store import ResultFeedStore\n",
            "from continuity_lab import result_feed_models\n",
        ):
            source.write_text(statement)
            code, report = self.cli("--module", "p1", "--groups", "boundary")
            self.assertEqual(code, 1)
            self.assertTrue(
                any("forbidden dependency" in row["message"] for row in report["violations"])
            )
        source.write_text(
            "from continuity_lab.work_api import WorkPayload\n"
            "from continuity_lab.execution_api import ExecutionClient\n"
            "from continuity_lab.result_feed_api import ResultFeedClient\n"
        )
        self.assertEqual(self.cli("--module", "p1", "--groups", "boundary")[0], 0)

    def test_missing_implemented_source_fails_but_planned_source_is_allowed(self):
        self.configs["p1"]["sourceRoots"][0]["path"] = "missing"
        self.configs["p1"]["forbiddenImports"] = []
        self.save_configs()
        code, result = self.cli()
        self.assertEqual(code, 1)
        self.assertIn("implemented source missing", result["violations"][0]["message"])

    def test_from_import_alias_cannot_bypass_specific_forbidden_module(self):
        self.configs["p1"]["forbiddenImports"][0]["modules"] = ["other_project.store"]
        self.save_configs()
        (self.root / "code/domain.py").write_text("from other_project import store\n")
        code, result = self.cli("--groups", "boundary")
        self.assertEqual(code, 1)
        self.assertIn("other_project.store", result["violations"][0]["message"])

    def test_unknown_and_duplicate_config_fields_fail(self):
        config_path = self.root / "harness/modules/p2.json"
        config_path.write_text('{"schemaVersion": 1, "schemaVersion": 1}')
        code, result = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("duplicate JSON field", result["error"])
        self.configs["p2"]["unexpected"] = True
        self.save_configs()
        code, result = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("expected fields", result["error"])

    def test_bad_status_duplicate_mapping_and_invalid_case_fail(self):
        for change in (
            lambda c: c.update(implementationStatus="done"),
            lambda c: c["testMappings"].append(c["testMappings"][0].copy()),
            lambda c: c["acceptance"].update(prefix="P2-"),
        ):
            with self.subTest(change=change):
                config = self.configs["p1"]
                original = json.loads(json.dumps(config))
                change(config)
                self.save_configs()
                self.assertEqual(self.cli()[0], 2)
                self.configs["p1"] = original

    def test_unsafe_paths_and_symlink_escapes_fail(self):
        for path in (
            "../secret",
            "/tmp/secret",
            "code/../secret",
            "code\\secret",
            "code//file",
        ):
            with self.subTest(path=path), self.assertRaises(ContractError):
                safe_path(self.root, path)
        (self.root / "escape").symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(ContractError):
            safe_path(self.root, "escape/secret")
        self.configs["p2"]["requiredDocuments"] = ["../secret"]
        self.save_configs()
        self.assertEqual(self.cli()[0], 2)

    def test_implemented_test_requires_existing_file_and_runner(self):
        (self.root / "tests/test_example.py").unlink()
        code, result = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("implemented test missing", result["error"])

    def test_implemented_test_mapping_must_match_exact_runner_target(self):
        (self.root / "tests/test_unrelated.py").write_text("# unrelated fixture\n")
        self.configs["p1"]["testMappings"][0]["testFiles"] = ["tests/test_unrelated.py"]
        self.save_configs()
        code, result = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("test mapping disagrees", result["error"])

    def test_changed_scope_expands_for_shared_unknown_and_multiple_modules(self):
        _, configs = load_contracts(self.root)
        self.assertEqual(changed_modules(["project2/src/index.ts"], configs), {"p2"})
        self.assertEqual(changed_modules(["project2/a", "project3/b"], configs), {"p2", "p3"})
        for path in (
            "AGENTS.md",
            "harness/rules/static.json",
            "scripts/harness-check.sh",
            "docs/validation-plan.md",
            "unknown/path",
            "services/control_api/app.py",
            "apps/local-console/src/main.ts",
            "local-setup/stack.py",
            "contracts/events.json",
        ):
            with self.subTest(path=path):
                self.assertEqual(changed_modules([path], configs), {"p1", "p2", "p3"})

    def test_missing_git_baseline_conservatively_selects_all(self):
        with patch("harness.static_check.git_changed_paths", return_value=None):
            code, result = self.cli("--changed", "--module", "p2")
        self.assertEqual(code, 0)
        self.assertEqual(len(result["modules"]), 3)
        self.assertEqual(result["selection"], "all_no_git_baseline")
        with patch("harness.static_check.subprocess.run") as run:
            self.assertIsNone(git_changed_paths(self.root, "--unsafe"))
        run.assert_not_called()

    def test_fast_tests_require_positive_count_and_no_skips(self):
        (self.root / "projects/agent-continuity/tests").mkdir(parents=True)
        for stderr, expected in (
            ("Ran 0 tests in 0.001s\nOK\n", "no_tests"),
            ("Ran 2 tests in 0.001s\nOK (skipped=1)\n", "skipped_tests"),
            ("", "no_tests"),
        ):
            with (
                self.subTest(stderr=stderr),
                patch(
                    "harness.static_check.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 0, "", stderr),
                ),
                patch("harness.static_check.run_root_tests", return_value={"exitCode": 0}),
            ):
                result = run_tests(self.root, self.configs)[0]
            self.assertEqual(result["status"], expected)
            self.assertEqual(result["runnerExitCode"], 0)
            self.assertEqual(result["exitCode"], 1)

    def test_fast_timeout_keeps_safe_test_progress_but_never_becomes_a_pass(self):
        (self.root / "projects/agent-continuity/tests").mkdir(parents=True)
        raw = (
            b"PRIVATE_FAILURE_BODY\xff\n"
            b"test_before (test_demo.Checks.test_before) ... ok\n"
            b"test_last (test_demo.Checks.test_last) ... ok\n"
            b"Ran 3 tests in 113.125s\nOK\n"
        )
        with (
            patch(
                "harness.static_check.subprocess.run",
                side_effect=subprocess.TimeoutExpired(
                    [], 120, output=b"PRIVATE_STDOUT", stderr=raw
                ),
            ) as run,
            patch("harness.static_check.run_root_tests", return_value={"exitCode": 0}),
        ):
            result = run_tests(self.root, self.configs)[0]
        self.assertEqual(run.call_args.kwargs["timeout"], 120)
        self.assertEqual(result["exitCode"], 124)
        self.assertEqual(result["stderr"], "test suite exceeded 120 seconds")
        self.assertEqual(
            result["timeoutProgress"],
            {
                "lastObservedTest": "test_demo.Checks.test_last",
                "observedTestCount": 3,
                "observedSeconds": 113.125,
            },
        )
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("runnerExitCode", result)

    def test_fast_timeout_rejects_payloads_and_overlong_or_old_progress(self):
        (self.root / "projects/agent-continuity/tests").mkdir(parents=True)
        for value in (
            None,
            b"PRIVATE_BODY\xff",
            "test_case (private/key?token=SECRET) ... ok\n",
            "test_case (" + "a" * 600 + ") ... ok\n",
            "test_old (test_demo.Checks.test_old) ... ok\n" + "x" * 65537,
        ):
            with (
                self.subTest(kind=type(value).__name__),
                patch(
                    "harness.static_check.subprocess.run",
                    side_effect=subprocess.TimeoutExpired([], 120, stderr=value),
                ),
                patch("harness.static_check.run_root_tests", return_value={"exitCode": 0}),
            ):
                result = run_tests(self.root, self.configs)[0]
            self.assertEqual(result["exitCode"], 124)
            self.assertEqual(
                result["timeoutProgress"],
                {
                    "lastObservedTest": None,
                    "observedTestCount": None,
                    "observedSeconds": None,
                },
            )
            self.assertNotIn("SECRET", json.dumps(result))

    def test_fast_tests_preserve_failure_and_discover_project_suites(self):
        for project in ("channel-continuity", "delegation-reliability"):
            (self.root / f"projects/{project}/tests").mkdir(parents=True)
        completed = subprocess.CompletedProcess(
            [], 7, "diagnostic", "Ran 1 test in 0.01s\nFAILED\n"
        )
        root_result = {
            "command": ["python", "-m", "unittest", "discover", "-s", "tests"],
            "exitCode": 7,
            "runnerExitCode": 7,
            "testCount": 1,
        }
        with (
            patch("harness.static_check.subprocess.run", return_value=completed) as run,
            patch("harness.static_check.run_root_tests", return_value=root_result) as root_run,
        ):
            results = run_tests(self.root, self.configs)
        root_run.assert_called_once()
        self.assertEqual(root_run.call_args.args[0], self.root.resolve())
        self.assertEqual(len(results), 3)
        self.assertEqual(
            {result["command"][5] for result in results},
            {"tests", "projects/channel-continuity/tests", "projects/delegation-reliability/tests"},
        )
        self.assertTrue(all(result["exitCode"] == 7 for result in results))
        self.assertTrue(all(result["runnerExitCode"] == 7 for result in results))
        self.assertTrue(all(result["testCount"] == 1 for result in results))
        self.assertTrue(
            all(
                isinstance(call.args[0], list) and "shell" not in call.kwargs
                for call in run.call_args_list
            )
        )

    def report_mapping(self):
        (self.root / "tests/postgres").mkdir()
        (self.root / "tests/postgres/pg_fixture.py").write_text(
            "# explicit service assertion fixture\n"
        )
        path = self.root / "harness/catalog.json"
        catalog = json.loads(path.read_text())
        catalog["runners"]["BASE-01"] = {
            "project": "p1",
            "title": "explicit service lane",
            "mode": "lab",
            "kind": "python_json_report",
            "script": "local-setup/stack.py",
            "timeoutSeconds": 60,
            "assertionFiles": ["tests/postgres/pg_fixture.py"],
        }
        path.write_text(json.dumps(catalog))
        self.configs["p1"]["testMappings"][0]["testFiles"] = ["tests/postgres/pg_fixture.py"]
        self.save_configs()
        return path

    def test_report_mapping_accepts_exact_explicit_assertion_sources(self):
        self.report_mapping()
        code, result = self.cli()
        self.assertEqual(code, 0, result)

    def test_report_mapping_rejects_changed_or_missing_assertion_sources(self):
        path = self.report_mapping()
        catalog = json.loads(path.read_text())
        catalog["runners"]["BASE-01"]["assertionFiles"] = ["tests/test_example.py"]
        path.write_text(json.dumps(catalog))
        code, result = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("test mapping disagrees", result["error"])
        catalog["runners"]["BASE-01"]["assertionFiles"] = ["tests/postgres/pg_fixture.py"]
        path.write_text(json.dumps(catalog))
        (self.root / "tests/postgres/pg_fixture.py").unlink()
        code, result = self.cli()
        self.assertEqual(code, 2)
        self.assertIn("implemented test missing", result["error"])

    def test_infrastructure_mapping_retains_exact_files_and_mode_timeout_language_boundaries(self):
        path = self.report_mapping()
        catalog = json.loads(path.read_text())
        runner = catalog["runners"]["BASE-01"]
        runner.update(kind="python_infrastructure_report", timeoutSeconds=900)
        (self.root / "tests/browser.ts").write_text("// browser assertion fixture\n")
        runner["assertionFiles"] = ["tests/browser.ts"]
        self.configs["p1"]["testMappings"][0]["testFiles"] = ["tests/browser.ts"]
        self.save_configs()
        path.write_text(json.dumps(catalog))
        self.assertEqual(0, self.cli()[0])
        runner["mode"] = "live"
        path.write_text(json.dumps(catalog))
        self.assertEqual(0, self.cli()[0])
        runner["mode"] = "lab"
        for field, value in [
            ("timeoutSeconds", 901),
            ("mode", "unknown"),
            ("mode", "offline"),
            ("script", "tests/browser.ts"),
            ("assertionFiles", ["README.md"]),
        ]:
            original = dict(runner)
            runner[field] = value
            path.write_text(json.dumps(catalog))
            with self.subTest(field=field, value=value):
                self.assertEqual(2, self.cli()[0])
            runner.clear()
            runner.update(original)
        runner.update(kind="python_json_report", timeoutSeconds=301)
        path.write_text(json.dumps(catalog))
        self.assertEqual(2, self.cli()[0])

    def test_offline_discovery_never_enters_report_runner_assertion_directory(self):
        self.report_mapping()
        with (
            patch("harness.static_check.run_root_tests", return_value={"exitCode": 0}) as root_run,
            patch("harness.static_check.subprocess.run") as run,
        ):
            results = run_tests(self.root, self.configs)
        self.assertEqual(len(results), 1)
        root_run.assert_called_once()
        self.assertEqual(root_run.call_args.args[0], self.root.resolve())
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
