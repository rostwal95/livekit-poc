"""Actual document fixture setup/publication regressions; no normal qualification.

The real CLI contract test requires the explicitly built current specialist dist.
It never builds implicitly and starts no HTTP listener, PNG worker or provider.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from harness.process_control import OwnedProcess

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "projects/delegation-reliability/tests/document_cases.py"
NODE_FIXTURE = (
    ROOT / "projects/delegation-reliability/specialist-ts/tests/fixtures/document-cases.mjs"
)
# Use the selected runtime as an absolute child executable. A Homebrew cellar
# location is not a portable installation contract; fixture version guards stay
# unchanged and still qualify the actual runtime that executes the child.
_node_command = shutil.which("node")
if _node_command is None:
    raise RuntimeError("A selected Node runtime is required for document fixture tests")
NODE = Path(_node_command).resolve(strict=True)
SPEC = importlib.util.spec_from_file_location("document_fixture_under_test", FIXTURE)
assert SPEC is not None and SPEC.loader is not None
CASES: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CASES
SPEC.loader.exec_module(CASES)


class DocumentFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp(prefix="phase39-document-fixture-", dir="/private/tmp"))
        self.directory, self.inputs = self.work / "journey", self.work / "inputs"
        self.directory.mkdir(mode=0o700)
        self.inputs.mkdir(mode=0o700)
        self.children: list[OwnedProcess] = []
        self.threads: list[threading.Thread] = []
        self.releases: list[threading.Event] = []
        source = ROOT / "contracts/delegation"
        for path in source.rglob("*"):
            self.assertFalse(path.is_symlink())
            if not path.is_file():
                continue
            target = self.inputs / path.relative_to(source)
            current = self.inputs
            for part in target.relative_to(self.inputs).parent.parts:
                current = current / part
                current.mkdir(mode=0o700, exist_ok=True)
            with os.fdopen(
                os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as stream:
                stream.write(path.read_bytes())
        self.original_directory, self.original_inputs = (
            getattr(CASES, "DIRECTORY", None),
            getattr(CASES, "FIXTURES", None),
        )
        CASES.__dict__.update(DIRECTORY=self.directory, FIXTURES=self.inputs)

    def tearDown(self) -> None:
        for release in self.releases:
            release.set()
        for thread in self.threads:
            thread.join(timeout=3)
        failures: list[BaseException] = []
        for child in self.children:
            try:
                child.close()
            except (OSError, RuntimeError) as error:
                failures.append(error)
        CASES.__dict__.update(DIRECTORY=self.original_directory, FIXTURES=self.original_inputs)
        settled = all(not thread.is_alive() for thread in self.threads) and all(
            type(child.returncode) is int and not child.cleanup_failed for child in self.children
        )
        if settled:
            shutil.rmtree(self.work)
        self.assertTrue(settled, "Retained private work because a test owner remains unresolved")
        self.assertFalse(failures)

    def cli(self, command: list[str], name: str) -> tuple[int, dict[str, object]]:
        environment = {
            "PATH": str(NODE.parent) + ":/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "CI": "1",
            "NO_COLOR": "1",
            "COREPACK_HOME": "/private/tmp/livekit-pinned-corepack",
            "COREPACK_ENABLE_NETWORK": "0",
            "P3_DOCUMENT_DIRECTORY": str(self.directory),
            "P3_DOCUMENT_FIXTURES": str(self.inputs),
        }
        wrapper = "import os,sys;os.umask(0o077);os.execv(sys.argv[1],sys.argv[1:])"
        child = OwnedProcess(
            [sys.executable, "-I", "-c", wrapper, *command],
            cwd=self.work,
            env=environment,
            output_directory=self.work / name,
            max_output_bytes=32768,
        )
        self.children.append(child)
        result = child.wait(timeout=10)
        child.close()
        self.assertFalse(child.cleanup_failed)
        self.assertEqual((child.output_directory / "stderr.bin").read_bytes(), b"")
        value = json.loads((child.output_directory / "stdout.bin").read_bytes())
        self.assertIs(type(value), dict)
        return result.returncode, value

    def test_real_node_producer_and_python_contracts_read_complete_legacy_corpus(self) -> None:
        legacy = self.inputs / "v1.json"
        self.assertEqual(legacy.stat().st_size, 35116)
        self.assertGreater(legacy.stat().st_size, 32768)
        code, produced = self.cli([str(NODE), str(NODE_FIXTURE), "node-producer"], "producer")
        self.assertEqual(code, 0)
        self.assertEqual(produced["producer_rows"], 8)
        self.assertTrue(produced["cleanup_complete"])
        code, consumed = self.cli(
            [sys.executable, "-I", str(FIXTURE), "python-contracts"], "contracts"
        )
        self.assertEqual(code, 0)
        self.assertEqual((consumed["tests"], consumed["passed"]), (8, 8))
        self.assertTrue(consumed["cleanup_complete"])
        proof = json.loads((self.directory / "document-contract-proof.json").read_bytes())
        self.assertEqual(len(proof["records"]), 8)
        self.assertLessEqual((self.directory / "document-producer.json").stat().st_size, 32768)
        self.assertLessEqual(
            (self.directory / "document-contract-proof.json").stat().st_size, 32768
        )

    def test_only_exact_legacy_setup_file_gets_64k_and_the_upper_limit_is_real(self) -> None:
        legacy = self.inputs / "v1.json"
        original = legacy.read_bytes()
        legacy.write_bytes(original + b" " * (65536 - len(original)))
        self.assertEqual(CASES.input_json("v1.json")["schema_version"], 1)
        legacy.write_bytes(legacy.read_bytes() + b" ")
        with self.assertRaises(AssertionError):
            CASES.input_json("v1.json")
        code, failed = self.cli([str(NODE), str(NODE_FIXTURE), "node-producer"], "too-large")
        self.assertEqual(code, 1)
        self.assertEqual(
            (failed["mode"], failed["stage"], failed["code"]),
            ("node-producer", "setup", "fixture_failed"),
        )
        self.assertFalse((self.directory / "document-producer.json").exists())
        ordinary = self.inputs / "document-v1.json"
        raw = ordinary.read_bytes()
        ordinary.write_bytes(raw + b" " * (32769 - len(raw)))
        with self.assertRaises(AssertionError):
            CASES.input_json("document-v1.json")

    def test_complete_arrival_is_published_without_replacement_and_two_link_window_waits(
        self,
    ) -> None:
        target = self.directory / "document_timeout_verified.reached"
        pending = target.with_name(f"{target.name}.{os.getpid()}.pending")
        published, release = threading.Event(), threading.Event()
        self.releases.append(release)
        errors: list[BaseException] = []
        original_link = os.link

        def held_link(source: Path, destination: Path, *, follow_symlinks: bool = True) -> None:
            self.assertFalse(target.exists())
            self.assertEqual(source, pending)
            self.assertEqual(pending.read_bytes(), f"{os.getpid()}\n".encode())
            self.assertEqual(stat.S_IMODE(pending.stat().st_mode), 0o600)
            original_link(source, destination, follow_symlinks=follow_symlinks)
            published.set()
            self.assertTrue(release.wait(timeout=3))

        def writer() -> None:
            try:
                CASES.arrived("document_timeout_verified")
            except (AssertionError, OSError) as error:
                errors.append(error)

        with patch.object(CASES.os, "link", side_effect=held_link):
            thread = threading.Thread(target=writer)
            self.threads.append(thread)
            thread.start()
            try:
                self.assertTrue(published.wait(timeout=3))
                self.assertEqual(target.read_bytes(), f"{os.getpid()}\n".encode())
                self.assertEqual(target.stat().st_nlink, 2)
                self.assertIsNone(CASES.marker_pid(target, os.getpid()))
            finally:
                release.set()
                thread.join(timeout=3)
        self.assertFalse(errors)
        self.assertFalse(thread.is_alive())
        self.assertEqual(CASES.marker_pid(target, os.getpid()), os.getpid())
        self.assertEqual(target.stat().st_nlink, 1)
        original = target.read_bytes()
        with self.assertRaises(FileExistsError):
            CASES.arrived("document_timeout_verified")
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(pending.exists())
        with self.assertRaises(AssertionError):
            CASES.marker_pid(target, os.getpid() + 1)

    def test_proof_is_complete_before_peer_visibility_and_original_bytes_survive(self) -> None:
        name = "document-http-proof.json"
        target, pending = self.directory / name, self.directory / (name + ".publishing")
        original_link = os.link
        observed: list[dict[str, int]] = []

        def inspect_link(source: Path, destination: Path, *, follow_symlinks: bool = True) -> None:
            self.assertFalse(target.exists())
            self.assertEqual(source, pending)
            observed.append(json.loads(pending.read_bytes()))
            self.assertEqual(stat.S_IMODE(pending.stat().st_mode), 0o600)
            original_link(source, destination, follow_symlinks=follow_symlinks)
            self.assertEqual(json.loads(target.read_bytes()), {"schema_version": 1})

        with patch.object(CASES.os, "link", side_effect=inspect_link):
            CASES.save(name, {"schema_version": 1})
        self.assertEqual(observed, [{"schema_version": 1}])
        self.assertFalse(pending.exists())
        self.assertEqual(target.stat().st_nlink, 1)
        original = target.read_bytes()
        with self.assertRaises(FileExistsError):
            CASES.save(name, {"schema_version": 2})
        self.assertEqual(target.read_bytes(), original)
        with self.assertRaises(AssertionError):
            CASES.save("document-http-wires.json", {"padding": "x" * 32768})
        self.assertFalse((self.directory / "document-http-wires.json").exists())


if __name__ == "__main__":
    unittest.main()
