"""Real owned subprocesses and typed fixtures prove bounded worker ownership."""

from __future__ import annotations

import io
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from continuity_lab import worker_cli, worker_runtime
from continuity_lab.execution_cli import _SafeFormatter
from continuity_lab.lease_models import CoordinationPolicy, LeaseGrant, WorkClaim, WorkKind
from continuity_lab.postgres_work import QueueSnapshot
from continuity_lab.worker_cli import WorkerHealth, WorkerSettings
from continuity_lab.worker_runtime import (
    ProcessStepLauncher,
    RuntimePolicy,
    StepOutcome,
    WorkerCleanupIncomplete,
    WorkerRuntime,
    WorkerRuntimeError,
    WorkerTelemetry,
    encode_work_claim,
    parse_work_claim,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = "2030-12-01T00:00:30+00:00"


def claim(kind=WorkKind.INQUIRY):
    return WorkClaim(
        LeaseGrant("account-a", str(uuid4()), str(uuid4()), 1, NOW),
        kind,
        "owner-a" if kind == WorkKind.WAIT else None,
    )


class Queue:
    def __init__(self, value=None):
        self.value = value
        self.claims = []
        self.releases = []
        self.snapshots = 0
        self.before_claim = None
        self.before_release = None

    def policy(self):
        return CoordinationPolicy()

    def snapshot(self, *, scope_id):
        self.snapshots += 1
        return QueueSnapshot(1, 0, 100, 2, 3.0, 0.0)

    def claim_next(self, *, scope_id, owner_id):
        self.claims.append((scope_id, owner_id))
        if self.before_claim:
            self.before_claim()
        result, self.value = self.value, None
        return result

    def release(self, grant):
        if self.before_release:
            self.before_release()
        self.releases.append(grant)


class Launcher(ProcessStepLauncher):
    def start(self, value, *, maximum_output_bytes):
        self.child = super().start(value, maximum_output_bytes=maximum_output_bytes)
        return self.child


class WorkerRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()
        self.environment = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}

    def launcher(self, script, **kwargs):
        return Launcher(
            (sys.executable, "-c", script), environment=self.environment, cwd=self.folder, **kwargs
        )

    def runtime(self, queue, launcher, **kwargs):
        return WorkerRuntime(queue, launcher, scope_id="account-a", lease_seconds=30, **kwargs)

    def test_policy_rejects_nonfinite_bool_and_out_of_range_bounds(self):
        for name, value in (
            ("poll_seconds", True),
            ("poll_seconds", 0),
            ("step_timeout_seconds", float("inf")),
            ("step_timeout_seconds", float("nan")),
            ("step_timeout_seconds", 10**1000),
            ("drain_timeout_seconds", 6),
            ("maximum_output_bytes", True),
            ("maximum_output_bytes", 1048577),
            ("maximum_consecutive_failures", 0),
        ):
            with (
                self.subTest(name=name, value_type=type(value).__name__),
                self.assertRaises(ValueError),
            ):
                RuntimePolicy(**{name: value})

    def test_work_claim_canonical_roundtrip_all_kinds(self):
        for kind in WorkKind:
            with self.subTest(kind=kind):
                value = claim(kind)
                self.assertEqual(parse_work_claim(encode_work_claim(value)), value)
        unicode_claim = WorkClaim(
            LeaseGrant("😀" * 128, "🦊" * 128, str(uuid4()), 1, NOW), WorkKind.WAIT, "🦉" * 128
        )
        self.assertLessEqual(len(encode_work_claim(unicode_claim).encode("utf-8")), 2048)
        self.assertEqual(parse_work_claim(encode_work_claim(unicode_claim)), unicode_claim)
        raw = json.loads(encode_work_claim(claim()))
        invalid = []
        for epoch in (True, 1.5, 0, "1"):
            changed = json.loads(json.dumps(raw))
            changed["grant"]["epoch"] = epoch
            invalid.append(json.dumps(changed, sort_keys=True, separators=(",", ":")))
        invalid += [
            json.dumps(raw),
            encode_work_claim(claim()).replace('"schema_version":1', '"schema_version":true'),
            encode_work_claim(claim()).replace(
                '"kind":"inquiry"', '"kind":"inquiry","kind":"delivery"'
            ),
            "x" * 2049,
        ]
        for text in invalid:
            with self.subTest(text_length=len(text)), self.assertRaises(ValueError):
                parse_work_claim(text)

    def test_stop_before_acquisition_never_reads_or_claims(self):
        queue = Queue(claim())
        runtime = self.runtime(queue, self.launcher("raise AssertionError()"))
        runtime.request_stop()
        self.assertIsNone(runtime.run_once())
        self.assertEqual(queue.claims, [])
        self.assertEqual(queue.snapshots, 0)

    def test_stop_during_observation_does_not_claim_more_work(self):
        queue = Queue(claim())
        runtime = self.runtime(queue, self.launcher("raise AssertionError()"))

        def snapshot(**kwargs):
            runtime.request_stop()
            return QueueSnapshot(1, 0, 100, 2, 0.0, 0.0)

        queue.snapshot = snapshot
        self.assertIsNone(runtime.run_once())
        self.assertEqual(queue.claims, [])

    def test_partial_process_initialization_reaps_before_propagating_failure(self):
        real_popen = subprocess.Popen
        children = []

        def spawn(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            children.append(child)
            return child

        selector = worker_runtime.selectors.DefaultSelector()
        with (
            patch.object(worker_runtime.subprocess, "Popen", side_effect=spawn),
            patch.object(worker_runtime.selectors, "DefaultSelector", return_value=selector),
            patch.object(selector, "register", side_effect=OSError("registration failed")),
            self.assertRaises(OSError),
        ):
            self.launcher("import time;time.sleep(60)").start(claim(), maximum_output_bytes=512)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        with self.assertRaises(ChildProcessError):
            os.waitpid(children[0].pid, os.WNOHANG)

    def test_stop_during_acquisition_releases_without_starting_child(self):
        value = claim()
        queue = Queue(value)
        launcher = self.launcher("raise AssertionError()")
        runtime = self.runtime(queue, launcher)
        queue.before_claim = runtime.request_stop
        self.assertIsNone(runtime.run_once())
        self.assertEqual(queue.releases, [value.grant])
        self.assertFalse(hasattr(launcher, "child"))

    def test_normal_child_progress_reaps_before_lease_release_and_metrics_are_real(self):
        value = claim()
        queue = Queue(value)
        launcher = self.launcher(
            "import os; os.write(1,b'safe stdout'); os.write(2,b'safe stderr')"
        )

        def released():
            with self.assertRaises(ChildProcessError):
                os.waitpid(launcher.child.pid, os.WNOHANG)

        queue.before_release = released
        runtime = self.runtime(queue, launcher)
        result = runtime.run_once()
        self.assertEqual(result.outcome, StepOutcome.COMPLETED)
        self.assertTrue(result.reaped)
        self.assertEqual(queue.releases, [value.grant])
        registry = runtime.telemetry.registry
        self.assertEqual(
            registry.get_sample_value(
                "continuity_worker_steps_total", {"kind": "inquiry", "outcome": "completed"}
            ),
            1,
        )
        self.assertEqual(
            registry.get_sample_value(
                "continuity_worker_step_duration_seconds_count",
                {"kind": "inquiry", "outcome": "completed"},
            ),
            1,
        )
        self.assertEqual(registry.get_sample_value("continuity_worker_active_children"), 0)
        self.assertEqual(registry.get_sample_value("continuity_worker_outstanding"), 1)
        self.assertNotIn(value.grant.task_id, runtime.telemetry.render().decode())
        self.assertIsNone(
            WorkerTelemetry().registry.get_sample_value(
                "continuity_worker_steps_total", {"kind": "inquiry", "outcome": "completed"}
            )
        )

    def test_nonzero_process_outcome_is_not_a_business_failure_write(self):
        value = claim()
        queue = Queue(value)
        runtime = self.runtime(queue, self.launcher("import os; os._exit(71)"))
        result = runtime.run_once()
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertEqual(result.returncode, 71)
        self.assertEqual(queue.releases, [value.grant])
        self.assertIsNone(runtime.run_once())

    def test_slow_child_is_killed_reaped_and_durable_lease_released(self):
        value = claim()
        queue = Queue(value)
        launcher = self.launcher(
            "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)"
        )
        runtime = self.runtime(queue, launcher, policy=RuntimePolicy(step_timeout_seconds=0.2))
        started = time.monotonic()
        result = runtime.run_once()
        self.assertEqual(result.outcome, StepOutcome.TIMED_OUT)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(queue.releases, [value.grant])
        self.assertIsNotNone(launcher.child.poll())
        with self.assertRaises(ChildProcessError):
            os.waitpid(launcher.child.pid, os.WNOHANG)

    def test_output_flood_is_bounded_and_cannot_be_reported_completed(self):
        queue = Queue(claim())
        launcher = self.launcher(
            "import os; os.write(1,b'x'*65536); os.write(2,b'SECRET_SENTINEL'*4000)"
        )
        result = self.runtime(
            queue, launcher, policy=RuntimePolicy(maximum_output_bytes=512)
        ).run_once()
        self.assertEqual(result.outcome, StepOutcome.FAILED)
        self.assertTrue(result.reaped)
        self.assertEqual(len(queue.releases), 1)

    def test_only_registered_safe_child_log_fields_are_reconstructed(self):
        sentinel = "SECRET_SENTINEL"
        record = {
            "service": "continuity-execution",
            "timestamp": sentinel,
            "severity": "info",
            "event": "attempt_started",
            "code": "ok",
            "operation": sentinel,
        }
        unknown = {**record, "event": sentinel}
        extra = {**record, "message": sentinel}
        script = "import json\n" + "\n".join(
            "print(" + repr(json.dumps(row)) + ")" for row in (record, unknown, extra)
        )
        with self.assertLogs("continuity_lab.worker_runtime", level="INFO") as logs:
            self.runtime(Queue(claim()), self.launcher(script)).run_once()
        safe = "".join(_SafeFormatter().format(row) for row in logs.records)
        self.assertIn("attempt_started", safe)
        self.assertNotIn(sentinel, safe)
        self.assertEqual(
            sum(getattr(row, "event", None) == "attempt_started" for row in logs.records), 1
        )

    def test_forwarded_success_retains_info_and_unknown_severity_is_dropped(self):
        record = {
            "service": "continuity-execution",
            "timestamp": "PRIVATE_TIMESTAMP",
            "severity": "info",
            "event": "mutation_finished",
            "code": "succeeded",
        }
        unknown = {**record, "severity": "SECRET_SENTINEL"}
        malformed = {**record, "severity": ["info"]}
        script = "\n".join(
            "print(" + repr(json.dumps(value)) + ")" for value in (record, unknown, malformed)
        )
        with self.assertLogs("continuity_lab.worker_runtime", level="INFO") as logs:
            self.runtime(Queue(claim()), self.launcher(script)).run_once()
        forwarded = [
            row for row in logs.records if getattr(row, "event", None) == "mutation_finished"
        ]
        self.assertEqual(len(forwarded), 1)
        self.assertEqual(forwarded[0].levelname, "INFO")
        rendered = "".join(_SafeFormatter().format(row) for row in logs.records)
        self.assertNotIn("PRIVATE_TIMESTAMP", rendered)
        self.assertNotIn("SECRET_SENTINEL", rendered)

    def test_descendant_is_terminated_before_exited_leader_is_reaped(self):
        marker = self.folder / "descendant.pid"
        script = (
            "import subprocess,sys,pathlib\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\npathlib.Path("
            + repr(str(marker))
            + ").write_text(str(p.pid))\n"
        )
        launcher = self.launcher(script)
        result = self.runtime(Queue(claim()), launcher).run_once()
        self.assertEqual(result.outcome, StepOutcome.COMPLETED)
        descendant = int(marker.read_text())
        # PID can remain a short-lived zombie until init reaps it. A zombie cannot
        # perform work; observe state rather than treating kill(pid,0) as liveness.
        due = time.monotonic() + 2
        while True:
            try:
                os.kill(descendant, 0)
            except ProcessLookupError:
                break
            proc = Path("/proc") / str(descendant) / "stat"
            if proc.is_file() and proc.read_text().split(")", 1)[1].strip().startswith("Z"):
                break
            if time.monotonic() >= due:
                self.fail("Owned descendant remained live after the step ended")
            time.sleep(0.01)

    def test_consecutive_process_failures_stop_at_configured_bound(self):
        values = [claim(), claim()]
        queue = Queue()

        def next_claim(**kwargs):
            return values.pop(0)

        queue.claim_next = next_claim
        runtime = self.runtime(
            queue,
            self.launcher("raise SystemExit(2)"),
            policy=RuntimePolicy(maximum_consecutive_failures=2),
        )
        self.assertEqual(runtime.run_once().outcome, StepOutcome.FAILED)
        with self.assertRaises(WorkerRuntimeError):
            runtime.run_once()
        self.assertEqual(len(queue.releases), 2)

    def test_completed_work_pulls_next_claim_after_reap_and_release_without_idle_delay(self):
        values = [claim(), claim(WorkKind.DELIVERY)]
        queue = Queue()
        launcher = self.launcher("pass")
        idle_pauses = []

        def pause(seconds):
            if runtime._child is None:
                idle_pauses.append(seconds)
            time.sleep(seconds)

        runtime = self.runtime(queue, launcher, pause=pause)

        def next_claim(**kwargs):
            self.assertEqual(len(queue.releases), len(queue.claims))
            queue.claims.append((kwargs["scope_id"], kwargs["owner_id"]))
            if values:
                return values.pop(0)
            runtime.request_stop()
            return None

        def released():
            # No following claim may precede reaping of the actual owned child.
            with self.assertRaises(ChildProcessError):
                os.waitpid(launcher.child.pid, os.WNOHANG)

        queue.claim_next = next_claim
        queue.before_release = released
        runtime.run()
        self.assertEqual(len(queue.releases), 2)
        self.assertEqual(len(queue.claims), 3)
        self.assertEqual(idle_pauses, [])
        self.assertIsNone(runtime._child)
        self.assertTrue(runtime.stopping)
        for kind in ("inquiry", "delivery"):
            self.assertEqual(
                runtime.telemetry.registry.get_sample_value(
                    "continuity_worker_steps_total", {"kind": kind, "outcome": "completed"}
                ),
                1,
            )

    def test_empty_queue_preserves_poll_backoff_instead_of_busy_claiming(self):
        queue = Queue()
        launcher = self.launcher("raise AssertionError('No empty-queue child may start')")
        clock = [0.0]
        observed_claim_times = []

        def pause(seconds):
            self.assertGreater(seconds, 0)
            self.assertLessEqual(seconds, 0.1)
            clock[0] += seconds

        runtime = self.runtime(queue, launcher, clock=lambda: clock[0], pause=pause)

        def next_claim(**kwargs):
            observed_claim_times.append(clock[0])
            queue.claims.append((kwargs["scope_id"], kwargs["owner_id"]))
            if len(observed_claim_times) == 3:
                runtime.request_stop()

        queue.claim_next = next_claim
        runtime.run()
        self.assertEqual(len(observed_claim_times), 3)
        for actual, expected in zip(observed_claim_times, (0.0, 1.0, 2.0), strict=True):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(queue.releases, [])
        self.assertFalse(hasattr(launcher, "child"))

    def test_failed_and_timed_out_work_retain_backoff_and_consecutive_failure_limit(self):
        for script, step_seconds, expected_outcome in (
            ("raise SystemExit(2)", 1, "failed"),
            ("import time;time.sleep(60)", 0.03, "timed_out"),
        ):
            with self.subTest(outcome=expected_outcome):
                values = [claim(), claim()]
                queue = Queue()
                launcher = self.launcher(script)
                idle_pauses = []

                runtime = self.runtime(
                    queue,
                    launcher,
                    policy=RuntimePolicy(
                        poll_seconds=0.05,
                        step_timeout_seconds=step_seconds,
                        maximum_consecutive_failures=2,
                    ),
                )

                def pause(seconds, owned_runtime=runtime, owned_pauses=idle_pauses):
                    if owned_runtime._child is None:
                        owned_pauses.append(seconds)
                    time.sleep(seconds)

                runtime.pause = pause

                def next_claim(owned_queue=queue, owned_values=values, **kwargs):
                    owned_queue.claims.append((kwargs["scope_id"], kwargs["owner_id"]))
                    return owned_values.pop(0)

                queue.claim_next = next_claim
                with self.assertRaises(WorkerRuntimeError):
                    runtime.run()
                self.assertTrue(idle_pauses)
                self.assertTrue(all(0 < seconds <= 0.05 for seconds in idle_pauses))
                self.assertEqual(len(queue.claims), 2)
                self.assertEqual(len(queue.releases), 2)
                self.assertIsNone(runtime._child)
                self.assertTrue(runtime.stopping)
                self.assertEqual(
                    runtime.telemetry.registry.get_sample_value(
                        "continuity_worker_steps_total",
                        {"kind": "inquiry", "outcome": expected_outcome},
                    ),
                    2,
                )
                with self.assertRaises(ChildProcessError):
                    os.waitpid(launcher.child.pid, os.WNOHANG)

    def test_stop_after_completed_child_release_never_acquires_another_claim(self):
        queue = Queue(claim())
        launcher = self.launcher("pass")
        runtime = self.runtime(queue, launcher)
        queue.before_release = runtime.request_stop
        runtime.run()
        self.assertEqual(len(queue.claims), 1)
        self.assertEqual(len(queue.releases), 1)
        self.assertIsNone(runtime._child)
        self.assertTrue(runtime.stopping)
        with self.assertRaises(ChildProcessError):
            os.waitpid(launcher.child.pid, os.WNOHANG)

    def test_observer_and_metrics_failure_cannot_change_process_truth(self):
        runtime = self.runtime(
            Queue(claim()),
            self.launcher("pass"),
            observe=lambda *_: (_ for _ in ()).throw(OSError("SECRET_SENTINEL")),
        )
        with patch.object(
            runtime.telemetry.steps, "labels", side_effect=OSError("SECRET_SENTINEL")
        ):
            self.assertEqual(runtime.run_once().outcome, StepOutcome.COMPLETED)

    def test_launcher_failure_preserves_original_when_release_also_fails(self):
        class LaunchError(RuntimeError):
            pass

        class Broken:
            def start(self, *_, **__):
                raise LaunchError()

        queue = Queue(claim())
        queue.before_release = lambda: (_ for _ in ()).throw(OSError("private"))
        with self.assertRaises(LaunchError):
            self.runtime(queue, Broken()).run_once()

    def test_failed_reap_does_not_release_current_lease(self):
        class BrokenChild:
            def drain(self):
                pass

            def poll(self):
                return None

            def kill_and_reap(self, **kwargs):
                raise WorkerCleanupIncomplete()

            def close(self):
                raise WorkerCleanupIncomplete()

        class Broken:
            def start(self, *_, **__):
                return BrokenChild()

        queue = Queue(claim())
        runtime = self.runtime(queue, Broken(), policy=RuntimePolicy(step_timeout_seconds=0.01))
        with self.assertRaises(WorkerCleanupIncomplete):
            runtime.run_once()
        self.assertEqual(queue.releases, [])

    def test_quiescence_ack_waits_for_post_step_query_and_has_no_parked_queue_calls(self):
        queue = Queue(claim())
        launcher = self.launcher("pass")
        query_entered, query_return, parked, leave_park, resumed = (
            threading.Event() for _ in range(5)
        )
        observations, errors = [], []
        original_snapshot = queue.snapshot

        def snapshot(**kwargs):
            value = original_snapshot(**kwargs)
            if queue.snapshots == 2:
                query_entered.set()
                if not query_return.wait(3):
                    raise AssertionError("Post-step query was not released")
            return value

        def observe(ready, active):
            observations.append((ready, active, runtime.quiescent))
            if ready and parked.is_set():
                resumed.set()

        def pause(seconds):
            if runtime.quiescent:
                parked.set()
                leave_park.wait(3)
            else:
                time.sleep(seconds)

        queue.snapshot = snapshot
        runtime = self.runtime(queue, launcher, observe=observe, pause=pause)

        def next_claim(**kwargs):
            queue.claims.append((kwargs["scope_id"], kwargs["owner_id"]))
            value, queue.value = queue.value, None
            if value is None:
                runtime.request_stop()
            return value

        def run():
            try:
                runtime.run()
            except BaseException as error:  # noqa: BLE001 - retain owned thread failures for assertions
                errors.append(error)

        queue.claim_next = next_claim
        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(query_entered.wait(3))
            self.assertEqual(len(queue.releases), 1)
            runtime.request_quiesce()
            runtime._publish(force=True)
            self.assertFalse(runtime.quiescent)
            self.assertEqual(observations[-1], (True, 0, False))
            self.assertFalse(parked.is_set())
            query_return.set()
            self.assertTrue(parked.wait(3))
            self.assertTrue(runtime.quiescent)
            self.assertEqual(observations[-1], (False, 0, True))
            self.assertEqual(queue.snapshots, 2)
            self.assertEqual(len(queue.claims), 1)
            with self.assertRaises(ChildProcessError):
                os.waitpid(launcher.child.pid, os.WNOHANG)
            runtime.request_resume()
            leave_park.set()
            self.assertTrue(resumed.wait(3))
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertFalse(runtime.quiescent)
            self.assertEqual(len(queue.claims), 2)
        finally:
            runtime.request_stop()
            query_return.set()
            leave_park.set()
            thread.join(3)

    def test_active_child_finishes_before_quiescence_and_stop_wins_over_resume(self):
        marker = self.folder / "finish-child"
        script = (
            "from pathlib import Path;import time\n"
            f"while not Path({str(marker)!r}).exists():time.sleep(.005)\n"
        )
        queue, launcher = Queue(claim()), self.launcher(script)
        active, parked, leave_park = (threading.Event() for _ in range(3))
        observations, errors = [], []

        def observe(ready, children):
            observations.append((ready, children, runtime.quiescent))
            if children == 1:
                active.set()

        def pause(seconds):
            if runtime.quiescent:
                parked.set()
                leave_park.wait(3)
            else:
                time.sleep(seconds)

        runtime = self.runtime(queue, launcher, observe=observe, pause=pause)

        def run():
            try:
                runtime.run()
            except BaseException as error:  # noqa: BLE001 - retain owned thread failures for assertions
                errors.append(error)

        thread = threading.Thread(target=run)
        thread.start()
        try:
            self.assertTrue(active.wait(3))
            runtime.request_quiesce()
            runtime._publish(force=True)
            self.assertEqual(observations[-1], (True, 1, False))
            self.assertFalse(parked.is_set())
            marker.touch()
            self.assertTrue(parked.wait(3))
            self.assertEqual(len(queue.releases), 1)
            self.assertEqual(observations[-1], (False, 0, True))
            runtime.request_stop()
            runtime.request_resume()
            runtime.request_quiesce()
            leave_park.set()
            thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(runtime.stopping)
            self.assertFalse(runtime.quiescent)
            self.assertEqual(len(queue.claims), 1)
            self.assertEqual(observations[-1], (False, 0, False))
        finally:
            runtime.request_stop()
            marker.touch(exist_ok=True)
            leave_park.set()
            thread.join(3)

    def test_failed_owned_cleanup_never_acknowledges_pending_quiescence(self):
        observations = []

        class BrokenChild:
            def drain(self):
                pass

            def poll(self):
                return None

            def kill_and_reap(self, **_kwargs):
                raise WorkerCleanupIncomplete()

            def close(self):
                raise WorkerCleanupIncomplete()

        class BrokenLauncher:
            def start(self, *_args, **_kwargs):
                runtime.request_quiesce()
                return BrokenChild()

        queue = Queue(claim())
        runtime = self.runtime(
            queue,
            BrokenLauncher(),
            policy=RuntimePolicy(step_timeout_seconds=0.01),
            observe=lambda ready, active: observations.append((ready, active)),
        )
        with self.assertRaises(WorkerCleanupIncomplete):
            runtime.run()
        self.assertTrue(runtime.stopping)
        self.assertFalse(runtime.quiescent)
        self.assertEqual(queue.releases, [])
        self.assertNotIn((False, 0), observations)
        self.assertEqual(observations[-1], (False, 1))

    def _signal_parent(self, *, slow):
        marker = self.folder / ("slow.json" if slow else "drain.json")
        result_path = self.folder / ("slow-result.json" if slow else "drain-result.json")
        child_code = "import time;time.sleep(" + ("60" if slow else "0.2") + ")"
        helper = r"""
import json,os,pathlib,signal,sys,time
import continuity_lab
continuity_lab.__path__.insert(0,os.environ["WORKER_TEST_MODULE_DIR"])
from continuity_lab.lease_models import LeaseGrant,WorkClaim,WorkKind
from continuity_lab.postgres_work import QueueSnapshot
from continuity_lab.worker_runtime import WorkerRuntime,RuntimePolicy,ProcessStepLauncher
class Queue:
    def claim_next(self,**kwargs):
        return WorkClaim(LeaseGrant("account-a","task-a","00000000-0000-4000-8000-000000000001",1,"2030-12-01T00:00:30+00:00"),WorkKind.INQUIRY)
    def release(self,grant): pass
    def snapshot(self,**kwargs): return QueueSnapshot(1,0,100,2,0.0,0.0)
class Launcher(ProcessStepLauncher):
    def start(self,*args,**kwargs):
        self.child=super().start(*args,**kwargs)
        return self.child
marker=pathlib.Path(sys.argv[1]); result=pathlib.Path(sys.argv[2])
launcher=Launcher((sys.executable,"-c",sys.argv[3]),environment={"PATH":os.defpath},cwd=marker.parent)
runtime=None
signalled=False
def stop(*_):
    global signalled
    signalled=True
    runtime.request_stop()
def observe(ready,active):
    if active and not marker.exists(): marker.write_text(json.dumps({"child":launcher.child.pid,"parent":os.getpid()}))
runtime=WorkerRuntime(Queue(),launcher,scope_id="account-a",lease_seconds=30,policy=RuntimePolicy(step_timeout_seconds=5,drain_timeout_seconds=float(sys.argv[4])),observe=observe)
signal.signal(signal.SIGTERM,stop)
observed=runtime.run_once()
result.write_text(json.dumps({"outcome":observed.outcome.value,"stopping":runtime.stopping,"signalled":signalled}))
"""
        environment = {
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT),
            "WORKER_TEST_MODULE_DIR": str(Path(worker_runtime.__file__).parent),
        }
        parent = subprocess.Popen(
            [
                sys.executable,
                "-c",
                helper,
                str(marker),
                str(result_path),
                child_code,
                "0.1" if slow else "1",
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        child = None
        try:
            due = time.monotonic() + 5
            while not marker.exists():
                if parent.poll() is not None:
                    self.fail("Owned parent exited before the required live child")
                if time.monotonic() >= due:
                    self.fail("Owned child barrier was not observed")
                time.sleep(0.01)
            child = int(json.loads(marker.read_text())["child"])
            os.kill(parent.pid, signal.SIGTERM)
            _, errors = parent.communicate(timeout=3)
            self.assertEqual(parent.returncode, 0, errors[-4096:].decode("utf-8", errors="replace"))
            value = json.loads(result_path.read_text())
            self.assertTrue(value["stopping"])
            self.assertTrue(value["signalled"])
            self.assertEqual(value["outcome"], "stopped" if slow else "completed")
            with self.assertRaises(ProcessLookupError):
                os.kill(child, 0)
        finally:
            if parent.poll() is None:
                os.killpg(parent.pid, signal.SIGKILL)
                parent.wait(timeout=2)
            if child is not None:
                try:
                    os.kill(child, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_actual_sigterm_drains_eligible_child_and_reaps(self):
        self._signal_parent(slow=False)

    def test_actual_sigterm_kills_slow_child_without_orphan(self):
        self._signal_parent(slow=True)


class WorkerConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name).resolve()

    def settings(self):
        return {
            "P1_WORKER_SCOPE": "account-a",
            "P1_WORKER_SUPPLIER_DB": str(self.folder / "supplier.sqlite3"),
            "P1_WORKER_SINK_DB": str(self.folder / "sink.sqlite3"),
            "P1_WORKER_STATE_FILE": str(self.folder / "health.json"),
        }

    def test_settings_reject_unknown_secret_and_unbounded_values(self):
        for changes in (
            {"P1_MIGRATION_PASSWORD": "SECRET_SENTINEL"},
            {"P1_WORKER_EXTRA": "x"},
            {"P1_WORKER_POLL_SECONDS": "nan"},
            {"P1_WORKER_STEP_SECONDS": "16"},
            {"P1_WORKER_OUTPUT_BYTES": "0"},
            {"P1_WORKER_SUPPLIER_MODE": "unsafe"},
            {"P1_WORKER_SCOPE": "a\nsecret"},
            {"P1_WORKER_SUPPLIER_DB": "relative.sqlite3"},
        ):
            with self.subTest(keys=list(changes)), self.assertRaises(ValueError):
                WorkerSettings.from_env({**self.settings(), **changes})

    def test_settings_prevent_health_or_metrics_from_overwriting_fixtures(self):
        for changes in (
            {"P1_WORKER_STATE_FILE": str(self.folder / "supplier.sqlite3")},
            {"P1_WORKER_STATE_FILE": str(self.folder / "status.prom")},
            {"P1_WORKER_SINK_DB": str(self.folder / "supplier.sqlite3")},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                WorkerSettings.from_env({**self.settings(), **changes})

    def test_health_file_is_private_atomic_and_fails_closed_for_stale_or_unknown(self):
        current = [10.0]
        health = WorkerHealth(self.folder / "health.json", clock=lambda: current[0])
        health.publish(True, 1)
        self.assertEqual(stat.S_IMODE(health.path.stat().st_mode), 0o600)
        self.assertTrue(health.ready())
        self.assertEqual(list(self.folder.glob("*.pending")), [])
        current[0] = 21
        self.assertFalse(health.ready())
        current[0] = 9
        self.assertFalse(health.ready())
        current[0] = 10
        health.publish(False, 0)
        self.assertFalse(health.ready())
        health.path.write_text('{"schema_version":99}')
        self.assertFalse(health.ready())
        health.path.chmod(0o644)
        self.assertFalse(health.ready())

    def test_quiescence_health_requires_fresh_private_live_inactive_not_ready_record(self):
        current = [10.0]
        health = WorkerHealth(self.folder / "health.json", clock=lambda: current[0])
        for ready, active, expected in (
            (False, 0, True),
            (False, 1, False),
            (True, 0, False),
            (True, 1, False),
        ):
            with self.subTest(ready=ready, active=active):
                health.publish(ready, active)
                self.assertIs(health.is_quiescent(), expected)
                self.assertIs(health.ready(), ready)
        health.publish(False, 0)
        original = json.loads(health.path.read_text())
        for changes in (
            {"ready": 0},
            {"active_children": False},
            {"schema_version": True},
            {"extra": "PRIVATE"},
            {"monotonic_seconds": -1},
            {"monotonic_seconds": 11},
        ):
            with self.subTest(changes=changes):
                health.path.write_text(json.dumps({**original, **changes}))
                self.assertFalse(health.is_quiescent())
        health.path.write_text(json.dumps(original))
        with patch.object(worker_cli.os, "kill", side_effect=ProcessLookupError):
            self.assertFalse(health.is_quiescent())
        health.path.chmod(0o644)
        self.assertFalse(health.is_quiescent())
        for age in (0, True, float("nan"), 61):
            with self.subTest(age=age), self.assertRaises(ValueError):
                health.is_quiescent(maximum_age_seconds=age)

    def test_worker_handlers_are_installed_before_readiness_and_restored(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        settings = WorkerSettings.from_env(self.settings())
        installed, callbacks, publications = {}, {}, []
        previous = lambda *_args: None
        runtime = Mock()
        health = Mock()

        def bind(sig, handler):
            installed[sig] = handler
            if handler is not previous:
                callbacks[sig] = handler

        def publish(ready, active):
            if ready:
                self.assertEqual(
                    set(callbacks), {signal.SIGTERM, signal.SIGINT, signal.SIGUSR1, signal.SIGUSR2}
                )
            publications.append((ready, active))

        def run():
            self.assertIs(callbacks[signal.SIGTERM], callbacks[signal.SIGINT])
            callbacks[signal.SIGUSR1](signal.SIGUSR1, None)
            callbacks[signal.SIGUSR2](signal.SIGUSR2, None)
            callbacks[signal.SIGTERM](signal.SIGTERM, None)
            callbacks[signal.SIGINT](signal.SIGINT, None)

        runtime.run.side_effect = run
        health.publish.side_effect = publish
        queue = Mock(policy=Mock(return_value=SimpleNamespace(lease_seconds=30)))
        with (
            patch.object(worker_cli, "_supplier"),
            patch("continuity_lab.completion_sink.CompletionSink"),
            patch("continuity_lab.postgres_settings.PostgresSettings.from_env"),
            patch("continuity_lab.postgres_store.PostgresExecutionStore"),
            patch("continuity_lab.postgres_work.PostgresWorkQueue", return_value=queue),
            patch.object(worker_cli, "_child_environment", return_value={}),
            patch.object(worker_cli, "ProcessStepLauncher"),
            patch.object(worker_cli, "WorkerHealth", return_value=health),
            patch.object(worker_cli, "WorkerRuntime", return_value=runtime),
            patch.object(worker_cli.signal, "getsignal", return_value=previous),
            patch.object(worker_cli.signal, "signal", side_effect=bind),
        ):
            worker_cli._run(settings, once=False)
        self.assertEqual(publications, [(True, 0), (False, 0)])
        runtime.request_quiesce.assert_called_once_with()
        runtime.request_resume.assert_called_once_with()
        self.assertEqual(runtime.request_stop.call_count, 3)
        self.assertTrue(all(value is previous for value in installed.values()))

    def test_health_symlink_cannot_overwrite_an_unrelated_file(self):
        target = self.folder / "target"
        target.write_text("unchanged")
        link = self.folder / "health"
        link.symlink_to(target)
        with self.assertRaises(ValueError):
            WorkerHealth(link).publish(True, 0)
        self.assertEqual(target.read_text(), "unchanged")

    def test_explicit_fixture_initialization_preserves_progressed_booking(self):
        settings = WorkerSettings.from_env(self.settings())
        with redirect_stdout(io.StringIO()):
            worker_cli._initialize(settings)
        import sqlite3

        with closing(sqlite3.connect(settings.supplier_db)) as connection, connection:
            connection.execute("UPDATE bookings SET revision=1,check_in='2030-12-10'")
        with redirect_stdout(io.StringIO()):
            worker_cli._initialize(settings)
        supplier = worker_cli._supplier(settings)
        booking = supplier.booking(scope_id=settings.scope_id, booking_reference="DEMO-BK-001")
        self.assertEqual(booking.revision, 1)
        self.assertEqual(booking.check_in.isoformat(), "2030-12-10")

    def test_delivery_step_does_not_require_managed_inquiry_control(self):
        from types import SimpleNamespace

        from continuity_lab.effect_models import DeliveryState

        value = claim(WorkKind.DELIVERY)
        settings = WorkerSettings.from_env(self.settings())
        with (
            patch.dict(os.environ, {"P1_WORKER_CLAIM": encode_work_claim(value)}, clear=True),
            patch("continuity_lab.postgres_settings.PostgresSettings.from_env"),
            patch("continuity_lab.postgres_store.PostgresExecutionStore"),
            patch("continuity_lab.postgres_lifecycle.PostgresLifecycle") as lifecycle,
            patch("continuity_lab.postgres_effects.PostgresEffects") as effects,
            patch("continuity_lab.completion_sink.CompletionSink"),
            patch("continuity_lab.outbox_delivery.CompletionDeliveryWorker") as delivery,
            redirect_stdout(io.StringIO()) as output,
        ):
            lifecycle.return_value.get.side_effect = AssertionError(
                "A cancellation delivery needs no inquiry control"
            )
            effects.return_value.delivery_for_scope.return_value = SimpleNamespace(
                state=DeliveryState.PENDING
            )
            worker_cli._step(settings)
        lifecycle.return_value.get.assert_not_called()
        delivery.return_value.run_one.assert_called_once_with(
            scope_id=settings.scope_id, task_id=value.grant.task_id
        )
        effects.assert_called_once_with(unittest.mock.ANY, worker_lease=value.grant)
        self.assertEqual(json.loads(output.getvalue())["kind"], "delivery")

    def test_cli_configuration_and_unexpected_error_never_render_private_text(self):
        class PrivateError(RuntimeError):
            def __str__(self):
                raise AssertionError("Never render dependency errors")

        with (
            patch.object(worker_cli, "configure_logging"),
            patch.object(worker_cli.WorkerSettings, "from_env", side_effect=PrivateError()),
            redirect_stdout(io.StringIO()) as output,
            self.assertLogs("continuity_lab.worker_runtime", level="ERROR"),
        ):
            self.assertEqual(worker_cli.main(["run"]), 1)
        self.assertEqual(json.loads(output.getvalue())["code"], "unexpected_error")
        self.assertNotIn("Traceback", output.getvalue())

    def test_private_error_code_property_cannot_escape_or_replace_original(self):
        from continuity_lab.execution_models import ExecutionError

        class PrivateCode(ExecutionError):
            @property
            def code(self):
                raise RuntimeError("SECRET_SENTINEL")

            def __str__(self):
                raise AssertionError("Do not render private dependency text")

        error = PrivateCode()
        with (
            patch.object(worker_cli, "configure_logging"),
            patch.object(worker_cli.WorkerSettings, "from_env", side_effect=error),
            redirect_stdout(io.StringIO()) as output,
            self.assertLogs("continuity_lab.worker_runtime", level="ERROR") as logs,
        ):
            self.assertEqual(worker_cli.main(["run"]), 2)
        self.assertEqual(json.loads(output.getvalue())["code"], "unexpected_error")
        self.assertNotIn(
            "SECRET_SENTINEL",
            output.getvalue() + "".join(_SafeFormatter().format(row) for row in logs.records),
        )
        queue = Queue()

        def fail(**kwargs):
            raise error

        queue.claim_next = fail
        runtime = WorkerRuntime(queue, None, scope_id="account-a", lease_seconds=30)
        with self.assertRaises(PrivateCode) as observed:
            runtime.run_once()
        self.assertIs(observed.exception, error)

    def test_child_environment_excludes_admin_migration_and_application_credentials(self):
        settings = WorkerSettings.from_env(self.settings())
        environment = {
            "P1_POSTGRES_PASSWORD": "runtime-secret",
            "P1_MIGRATION_PASSWORD": "migration-secret",
            "POSTGRES_ADMIN_PASSWORD": "admin-secret",
            "LOCAL_ACCESS_TOKEN": "api-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            child = worker_cli._child_environment(settings)
        self.assertEqual(child["P1_POSTGRES_PASSWORD"], "runtime-secret")
        self.assertFalse(any(key.startswith("P1_MIGRATION_") for key in child))
        self.assertNotIn("admin-secret", json.dumps(child))
        self.assertNotIn("api-secret", json.dumps(child))
