"""Actual tiny process fixtures for Root discovery, coverage and timeout containment."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from harness import root_unittest as m
from harness.static_check import _timeout_progress


class RootUnittestTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="root-lane-fixture-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name).resolve()
        (self.root / "tests").mkdir()
        self.write(
            "test_conversation_agent",
            "import unittest\nclass SDK(unittest.TestCase):\n def test_sdk(self): pass\n",
        )
        self.write(
            "test_other",
            "import unittest\nclass Other(unittest.TestCase):\n def test_other(self): pass\n",
        )

    def write(self, module, source):
        (self.root / "tests" / (module + ".py")).write_text(textwrap.dedent(source))

    def run_lane(self, total=3.0, cleanup=0.7):
        return m.run_root_tests(self.root, _timeout_progress, _timing=m._Timing(total, cleanup))

    def evidence(self, result, suffix):
        return json.loads((Path(result["retainedWork"]) / suffix).read_bytes())

    def assert_failed(self, result):
        self.assertNotEqual(result["exitCode"], 0)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))

    def test_actual_two_process_union_order_fixtures_and_new_module_coverage(self):
        self.write(
            "test_provider_inference",
            "import unittest\nclass Provider(unittest.TestCase):\n def test_provider(self): pass\n",
        )
        self.write(
            "test_new_module",
            """
            import unittest
            from pathlib import Path
            path=Path('events.txt')
            def add(s):
                with path.open('a') as f: f.write(s+'\\n')
            def setUpModule(): add('module-start')
            def tearDownModule(): add('module-end')
            class Ordered(unittest.TestCase):
                @classmethod
                def setUpClass(cls): add('class-start')
                @classmethod
                def tearDownClass(cls): add('class-end')
                def test_a(self): add('a')
                def test_b(self): add('b')
        """,
        )
        result = self.run_lane()
        self.assertEqual((result["exitCode"], result["testCount"]), (0, 5), result)
        self.assertTrue(result["cleanup_complete"])
        self.assertTrue(result["outer_groups_settled"])
        self.assertEqual(len(result["workers"]), 2)
        self.assertEqual([w["selectedCount"] for w in result["workers"]], [2, 3])
        self.assertTrue(all(w["returncode"] == 0 and w["groupAbsent"] for w in result["workers"]))
        a, b = [self.evidence(result, r + ".manifest.json") for r in m.ROLES]
        self.assertEqual(a["full"], b["full"])
        self.assertFalse(set(a["selected"]) & set(b["selected"]))
        self.assertEqual(set(a["selected"]) | set(b["selected"]), set(a["full"]))
        for role in m.ROLES:
            self.assertEqual(
                self.evidence(result, role + ".result.json")["started"],
                self.evidence(result, role + ".manifest.json")["selected"],
            )
        self.assertEqual(
            (self.root / "events.txt").read_text().splitlines(),
            ["module-start", "class-start", "a", "b", "class-end", "module-end"],
        )
        directory = Path(result["retainedWork"])
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertTrue(all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in directory.iterdir()))

    def test_expected_failure_preserves_unittest_semantics(self):
        self.write(
            "test_other",
            "import unittest\nclass Other(unittest.TestCase):\n @unittest.expectedFailure\n def test_other(self): self.fail('expected')\n",
        )
        result = self.run_lane()
        self.assertEqual(result["exitCode"], 0, result)
        self.assertEqual(self.evidence(result, "other.result.json")["expectedFailures"], 1)

    def test_required_skip_is_nonpassing(self):
        self.write(
            "test_other",
            "import unittest\nclass Other(unittest.TestCase):\n @unittest.skip('PRIVATE_SENTINEL')\n def test_other(self): pass\n",
        )
        result = self.run_lane()
        self.assert_failed(result)
        self.assertEqual(result["skippedCount"], 1)

    def test_skipped_subtest_is_nonpassing(self):
        self.write(
            "test_other",
            "import unittest\nclass Other(unittest.TestCase):\n def test_other(self):\n  with self.subTest(x=1): self.skipTest('PRIVATE_SENTINEL')\n",
        )
        result = self.run_lane()
        self.assert_failed(result)
        self.assertEqual(result["skippedCount"], 1)

    def test_assertion_failure_is_private(self):
        self.write(
            "test_other",
            "import unittest\nclass Other(unittest.TestCase):\n def test_other(self): self.fail('PRIVATE_SENTINEL')\n",
        )
        result = self.run_lane()
        self.assert_failed(result)
        self.assertEqual(result["code"], "tests_failed")
        self.assertIn(
            b"PRIVATE_SENTINEL", (Path(result["retainedWork"]) / "other.stderr.bin").read_bytes()
        )

    def test_error_is_nonpassing(self):
        self.write(
            "test_other",
            "import unittest\nclass Other(unittest.TestCase):\n def test_other(self): raise RuntimeError('PRIVATE_SENTINEL')\n",
        )
        self.assert_failed(self.run_lane())

    def test_unexpected_success_is_nonpassing(self):
        self.write(
            "test_other",
            "import unittest\nclass Other(unittest.TestCase):\n @unittest.expectedFailure\n def test_other(self): pass\n",
        )
        self.assert_failed(self.run_lane())

    def test_import_failure_cannot_become_a_test_pass(self):
        self.write("test_broken", "raise RuntimeError('PRIVATE_SENTINEL')\n")
        result = self.run_lane()
        self.assert_failed(result)
        self.assertEqual(result["code"], "discovery_failed")

    def test_custom_suite_is_rejected_before_any_test_runs(self):
        self.write(
            "test_other",
            """
            import unittest
            class Custom(unittest.TestSuite): pass
            class Other(unittest.TestCase):
                def test_other(self): raise AssertionError('must not run')
            def load_tests(loader, tests, pattern): return Custom(tests)
        """,
        )
        self.assert_failed(self.run_lane())

    def test_duplicate_discovered_ids_are_rejected(self):
        self.write(
            "test_other",
            """
            import unittest
            class Other(unittest.TestCase):
                def test_other(self): pass
            def load_tests(loader, tests, pattern):
                return unittest.TestSuite([Other('test_other'),Other('test_other')])
        """,
        )
        self.assert_failed(self.run_lane())

    def test_empty_partition_is_nonpassing(self):
        (self.root / "tests/test_conversation_agent.py").unlink()
        self.assert_failed(self.run_lane())

    def test_nondeterministic_discovery_does_not_authorize_execution(self):
        self.write(
            "test_other",
            """
            import sys,unittest
            from pathlib import Path
            class Other(unittest.TestCase):
                def test_other(self): Path('executed').write_text('bad')
            if sys.argv[-2]=='sdk':
                class Extra(unittest.TestCase):
                    def test_extra(self): Path('executed').write_text('bad')
        """,
        )
        result = self.run_lane()
        self.assert_failed(result)
        self.assertEqual(result["code"], "discovery_mismatch")
        self.assertFalse((self.root / "executed").exists())

    def test_partial_or_wrong_nonce_manifest_cannot_authorize_execution(self):
        self.write(
            "test_other",
            """
            import os,sys,unittest
            from pathlib import Path
            work=Path(sys.argv[-3]); role=sys.argv[-2]
            fd=os.open(work/(role+'.manifest.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            os.write(fd,b'{"nonce":"PRIVATE_SENTINEL"');os.close(fd)
            class Other(unittest.TestCase):
                def test_other(self): Path('executed').write_text('bad')
        """,
        )
        result = self.run_lane()
        self.assert_failed(result)
        self.assertFalse((self.root / "executed").exists())

    def test_worker_crash_cannot_pass_without_result_and_exact_coverage(self):
        self.write(
            "test_other",
            "import os,unittest\nclass Other(unittest.TestCase):\n def test_other(self): os._exit(7)\n",
        )
        result = self.run_lane()
        self.assert_failed(result)
        self.assertIn(7, [w["returncode"] for w in result["workers"]])
        self.assertFalse(result["cleanup_complete"])

    def test_held_test_uses_one_deadline_through_cleanup(self):
        self.write(
            "test_other",
            "import time,unittest\nclass Other(unittest.TestCase):\n def test_other(self): time.sleep(60)\n",
        )
        began = time.monotonic()
        result = self.run_lane(total=1.2, cleanup=0.45)
        self.assertLess(time.monotonic() - began, 1.6)
        self.assertEqual(result["exitCode"], 124, result)
        self.assertFalse(result["cleanup_complete"])
        self.assertIn("timeoutProgress", result)
        self.assertEqual(result["stderr"], "test suite exceeded 120 seconds")
        self.assertTrue(all(w["returncode"] is not None for w in result["workers"]))

    def test_blocked_discovery_uses_original_deadline(self):
        self.write("test_blocked", "import time\ntime.sleep(60)\n")
        result = self.run_lane(total=1.1, cleanup=0.4)
        self.assertEqual(result["exitCode"], 124, result)
        self.assertTrue(all(w["selectedCount"] == 0 for w in result["workers"]))

    def test_result_before_held_interpreter_exit_cannot_pass(self):
        self.write(
            "test_other",
            "import threading,time,unittest\nclass Other(unittest.TestCase):\n def test_other(self): threading.Thread(target=lambda:time.sleep(60)).start()\n",
        )
        result = self.run_lane(total=1.2, cleanup=0.45)
        self.assertEqual(result["exitCode"], 124, result)
        self.assertTrue((Path(result["retainedWork"]) / "other.result.json").exists())
        self.assertFalse(result["cleanup_complete"])

    def test_capture_overflow_fails_without_exposing_body(self):
        self.write(
            "test_other",
            "import sys,unittest\nclass Other(unittest.TestCase):\n def test_other(self):\n  sys.stdout.write('PRIVATE_SENTINEL'+('x'*2200000));sys.stdout.flush()\n",
        )
        result = self.run_lane()
        self.assert_failed(result)
        self.assertEqual(result["code"], "capture_overflow")
        captures = [v["bytes"] for k, v in result["artifacts"].items() if k.endswith(".bin")]
        self.assertLessEqual(max(captures), m.MAX_STREAM)
        self.assertLessEqual(sum(captures), m.MAX_CAPTURE)

    def test_both_streams_are_drained_and_raw_output_stays_private(self):
        self.write(
            "test_other",
            "import sys,unittest\nclass Other(unittest.TestCase):\n def test_other(self):\n  sys.stdout.write('PRIVATE_SENTINEL'+('x'*300000));sys.stdout.flush()\n  sys.stderr.write('PRIVATE_SENTINEL'+('y'*300000));sys.stderr.flush()\n",
        )
        result = self.run_lane()
        self.assertEqual(result["exitCode"], 0, result)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))
        self.assertGreater(result["artifacts"]["other.stdout.bin"]["bytes"], 300000)
        self.assertGreater(result["artifacts"]["other.stderr.bin"]["bytes"], 300000)

    def test_second_spawn_failure_retains_and_reaps_first_owner(self):
        original = subprocess.Popen
        calls = []

        def spawn(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 2:
                raise OSError("PRIVATE_SENTINEL")
            return original(*args, **kwargs)

        with patch.object(m.subprocess, "Popen", side_effect=spawn):
            result = self.run_lane(total=1.5, cleanup=0.5)
        self.assert_failed(result)
        self.assertEqual(len(result["workers"]), 1)
        self.assertIsNotNone(result["workers"][0]["returncode"])
        self.assertTrue(result["outer_groups_settled"])
        self.assertTrue(calls[0][1]["start_new_session"])
        self.assertNotIn("shell", calls[0][1])

    def test_first_test_failure_remains_primary_when_other_worker_times_out(self):
        self.write(
            "test_conversation_agent",
            "import unittest\nclass SDK(unittest.TestCase):\n def test_sdk(self): self.fail('PRIVATE_SENTINEL')\n",
        )
        self.write(
            "test_other",
            "import time,unittest\nclass Other(unittest.TestCase):\n def test_other(self): time.sleep(60)\n",
        )
        result = self.run_lane(total=1.2, cleanup=0.45)
        self.assertEqual(result["exitCode"], 124, result)
        self.assertEqual(result["code"], "tests_failed")
        self.assertFalse(result["cleanup_complete"])

    def test_new_session_helper_is_not_falsely_claimed_clean(self):
        self.write(
            "test_other",
            """
            import os,subprocess,sys,time,unittest
            from pathlib import Path
            class Other(unittest.TestCase):
                def test_other(self):
                    p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    Path('escaped.pid').write_text(str(p.pid))
                    time.sleep(60)
        """,
        )
        try:
            result = self.run_lane(total=1.3, cleanup=0.45)
            self.assertEqual(result["exitCode"], 124, result)
            self.assertFalse(result["cleanup_complete"])
            self.assertEqual(
                result["nested_cleanup"], "unverified_without_successful_fixture_completion"
            )
            self.assertTrue(Path(result["retainedWork"]).is_dir())
        finally:
            marker = self.root / "escaped.pid"
            if marker.exists():
                try:
                    pid = int(marker.read_text())
                    os.killpg(pid, signal.SIGKILL)
                    until = time.monotonic() + 1
                    while time.monotonic() < until:
                        try:
                            os.killpg(pid, 0)
                        except ProcessLookupError:
                            break
                        time.sleep(0.005)
                    else:
                        self.fail("owned escaped fixture group did not settle")
                except ProcessLookupError:
                    pass

    def test_inherited_helper_holding_capture_cannot_make_leader_exit_a_pass(self):
        self.write(
            "test_other",
            """
            import subprocess,sys,unittest
            class Other(unittest.TestCase):
                def test_other(self):
                    subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
        """,
        )
        result = self.run_lane(total=1.3, cleanup=0.5)
        self.assertEqual(result["exitCode"], 124, result)
        self.assertFalse(result["cleanup_complete"])
        other = next(w for w in result["workers"] if w["role"] == "other")
        self.assertTrue(other["signals"])
        self.assertTrue(result["outer_groups_settled"], result)
        self.assertTrue(result["captures_settled"], result)

    def test_sigint_cannot_become_a_pass_and_both_workers_are_retained(self):
        self.write(
            "test_other",
            "import time,unittest\nfrom pathlib import Path\nclass Other(unittest.TestCase):\n def test_other(self): Path('entered').write_text('yes'); time.sleep(60)\n",
        )
        finished = threading.Event()
        sent = threading.Event()

        def trigger():
            until = time.monotonic() + 2
            while not finished.is_set() and time.monotonic() < until:
                if (self.root / "entered").exists():
                    sent.set()
                    os.kill(os.getpid(), signal.SIGINT)
                    return
                finished.wait(0.005)

        thread = threading.Thread(target=trigger)
        thread.start()
        try:
            result = self.run_lane(total=3, cleanup=0.7)
        finally:
            finished.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertTrue(sent.is_set())
        self.assertEqual(result["exitCode"], 130, result)
        self.assertFalse(result["cleanup_complete"])
        self.assertTrue(all(w["returncode"] is not None for w in result["workers"]))

    def test_worker_requires_exact_go_and_control_eof(self):
        self.write(
            "test_conversation_agent",
            "import unittest\nfrom pathlib import Path\nclass SDK(unittest.TestCase):\n def test_sdk(self): Path('executed').write_text('bad')\n",
        )
        for control in (b"", b"BAD\n", b"GO\nEXTRA"):
            with self.subTest(control=control):
                folder = self.root / ("evidence-" + str(len(list(self.root.glob("evidence-*")))))
                folder.mkdir(mode=0o700)
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-I",
                        str(Path(m.__file__)),
                        "--worker",
                        str(self.root),
                        str(folder),
                        "sdk",
                        "a" * 32,
                    ],
                    cwd=self.root,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                try:
                    until = time.monotonic() + 2
                    while (
                        not (folder / "sdk.manifest.json").exists()
                        and process.poll() is None
                        and time.monotonic() < until
                    ):
                        time.sleep(0.005)
                    self.assertTrue((folder / "sdk.manifest.json").exists())
                    process.communicate(control, timeout=2)
                    self.assertEqual(process.returncode, 2)
                    self.assertFalse((self.root / "executed").exists())
                    self.assertFalse((folder / "sdk.result.json").exists())
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate(timeout=2)

    def test_controller_import_is_stdlib_only_and_does_not_start_io(self):
        repository = Path(m.__file__).resolve().parent.parent
        source = """import sys
sys.path.insert(0,sys.argv[1])
import os,socket,subprocess,asyncio
from unittest.mock import patch
def denied(*a,**k): raise AssertionError('import_started_IO')
with patch('builtins.open',denied),patch('os.open',denied),patch.object(socket.socket,'connect',denied),patch.object(socket.socket,'bind',denied),patch.object(subprocess,'Popen',denied),patch.object(asyncio,'create_task',denied),patch.object(os,'getenv',denied):
 import harness.root_unittest
 assert not any(n=='livekit' or n.startswith('livekit.') or n.startswith('test_') for n in sys.modules)
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", source, str(repository)],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_zero_test_ok_cannot_pass(self):
        for path in (self.root / "tests").glob("test_*.py"):
            path.write_text("# no cases\n")
        self.assert_failed(self.run_lane())

    def test_instance_modified_suite_is_rejected_before_pruning(self):
        suite = unittest.TestSuite()
        suite.run = lambda result: result
        with self.assertRaises(m._Invalid):
            m._prune(suite, "other", [])

    def test_malformed_result_is_not_adopted(self):
        self.write(
            "test_other",
            """
            import os,sys,unittest
            from pathlib import Path
            class Other(unittest.TestCase):
                def test_other(self):
                    fd=os.open(Path(sys.argv[-3])/'other.result.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                    os.write(fd,b'{"PRIVATE_SENTINEL":');os.close(fd)
        """,
        )
        self.assert_failed(self.run_lane())

    def test_signal_cleanup_error_does_not_overwrite_primary_or_skip_other_owner(self):
        self.write(
            "test_conversation_agent",
            "import unittest\nclass SDK(unittest.TestCase):\n def test_sdk(self): self.fail('PRIVATE_SENTINEL')\n",
        )
        self.write(
            "test_other",
            "import time,unittest\nclass Other(unittest.TestCase):\n def test_other(self): time.sleep(60)\n",
        )
        original = os.killpg
        rejected = []

        def killpg(pid, signum):
            if signum == signal.SIGINT and not rejected:
                rejected.append(pid)
                raise PermissionError("PRIVATE_SENTINEL")
            return original(pid, signum)

        with patch.object(m.os, "killpg", side_effect=killpg):
            result = self.run_lane(total=1.4, cleanup=0.6)
        self.assertEqual(result["code"], "tests_failed", result)
        self.assertEqual(result["exitCode"], 124)
        self.assertTrue(any(w["signalErrors"] for w in result["workers"]))
        self.assertTrue(all(w["returncode"] is not None for w in result["workers"]))
        self.assertFalse(result["cleanup_complete"])

    def test_manifest_rejects_missing_duplicate_foreign_changed_and_stale_data(self):
        base = {
            "schemaVersion": 1,
            "nonce": "a" * 32,
            "role": "sdk",
            "pid": 42,
            "full": ["test_conversation_agent.A.test_a", "test_other.B.test_b"],
            "selected": ["test_conversation_agent.A.test_a"],
        }
        variants = [
            dict(base, nonce="b" * 32),
            dict(base, pid=True),
            dict(base, selected=[]),
            dict(base, selected=["test_other.B.test_b"]),
            dict(base, full=base["full"] * 2),
            dict(base, full=["PRIVATE/key"]),
            dict(base, extra=1),
        ]
        missing = dict(base)
        missing.pop("pid")
        variants.append(missing)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(m._Invalid):
                m._manifest(value, "sdk", "a" * 32, 42)
        self.assertEqual(m._manifest(base, "sdk", "a" * 32, 42), base)

    def test_result_rejects_count_start_identity_skip_and_success_inconsistencies(self):
        manifest = {
            "schemaVersion": 1,
            "nonce": "a" * 32,
            "role": "sdk",
            "pid": 42,
            "selected": ["test_conversation_agent.A.test_a"],
        }
        base = {k: manifest[k] for k in ("schemaVersion", "nonce", "role", "pid")}
        base.update(
            started=manifest["selected"],
            testsRun=1,
            failures=0,
            errors=0,
            skips=0,
            unexpectedSuccesses=0,
            expectedFailures=0,
            successful=True,
        )
        for change in [
            {"testsRun": 0},
            {"started": ["test_other.B.test_b"]},
            {"schemaVersion": True},
            {"pid": True},
            {"testsRun": True},
            {"successful": "yes"},
            {"skips": 1},
            {"unexpectedSuccesses": 1},
            {"successful": False},
            {"extra": 1},
        ]:
            with self.subTest(change=change), self.assertRaises(m._Invalid):
                m._result(dict(base, **change), manifest)
        self.assertEqual(m._result(base, manifest), base)

    def test_metadata_rejects_partial_duplicate_nonfinite_oversize_and_wrong_shapes(self):
        for raw in [b"{", b'{"x":1,"x":2}', b'{"x":NaN}', b"[]", b" " * (m.MAX_JSON + 1)]:
            with self.subTest(raw=raw[:20]), self.assertRaises(m._Invalid):
                m._json(raw)

    def test_private_metadata_rejects_links_fifo_permissions_and_exact_publish_window(self):
        folder = self.root / "evidence"
        folder.mkdir(mode=0o700)
        m._publish(folder, "good.json", {"schemaVersion": 1})
        self.assertEqual(m._read(folder, "good.json"), {"schemaVersion": 1})
        (folder / "link.json").symlink_to(folder / "good.json")
        with self.assertRaises(OSError):
            m._read(folder, "link.json")
        os.link(folder / "good.json", folder / "hard.json")
        with self.assertRaises(m._Invalid):
            m._read(folder, "hard.json")
        (folder / "hard.json").unlink()
        os.mkfifo(folder / "fifo.json", 0o600)
        with self.assertRaises(m._Invalid):
            m._read(folder, "fifo.json")
        os.chmod(folder / "good.json", 0o644)
        with self.assertRaises(m._Invalid):
            m._read(folder, "good.json")
        os.chmod(folder / "good.json", 0o600)
        os.link(folder / "good.json", folder / "good.json.pending")
        self.assertIsNone(m._read(folder, "good.json"))
        (folder / "good.json.pending").unlink()
        self.assertEqual(m._read(folder, "good.json"), {"schemaVersion": 1})

    def test_default_deadline_is120_and_test_injection_can_only_shrink(self):
        self.assertEqual(m._Timing(), m._Timing(120, 5))
        for timing in [
            m._Timing(121, 5),
            m._Timing(120, 6),
            m._Timing(1, 1),
            m._Timing(float("nan"), 1),
            m._Timing(True, 0.1),
        ]:
            with self.subTest(timing=timing), self.assertRaises(ValueError):
                timing.validate()


if __name__ == "__main__":
    unittest.main()
