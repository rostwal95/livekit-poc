"""No downloads: pinned declarations, atomic bytes, lock and real child lifetime."""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "local-setup/scripts/local_models.py"
SPEC = importlib.util.spec_from_file_location("local_model_setup_test", HELPER)
assert SPEC is not None and SPEC.loader is not None
models = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = models
SPEC.loader.exec_module(models)
MANIFEST = ROOT / "local-setup/models/local-model-manifest.json"


class Response(io.BytesIO):
    def __init__(self, data, *, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = {} if headers is None else headers


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.cache = self.root / "cache"
        self.scratch = self.root / "scratch"
        self.scratch.mkdir(mode=0o700)
        self.body = b"synthetic-weight-bytes"
        self.file = models.ModelFile(
            "whisper/fixture.bin",
            "https://huggingface.co/approved/file",
            len(self.body),
            hashlib.sha256(self.body).hexdigest(),
        )

    def fetch(self, response=None, *, deadline=None):
        opener = Mock(return_value=Response(self.body) if response is None else response)
        models.fetch(
            self.file,
            self.cache,
            self.scratch,
            opener,
            time.monotonic() + 5 if deadline is None else deadline,
        )
        return opener

    def test_frozen_manifest_expands_only_reviewed_ten_files_and_finite_total(self):
        files = models.files_from_manifest(MANIFEST)
        self.assertEqual(len(files), 10)
        self.assertEqual(len({item.relative for item in files}), 10)
        self.assertLess(sum(item.size for item in files), 4 * 1024**3)
        value = json.loads(MANIFEST.read_text())
        path = self.root / "reordered.json"
        path.write_text(json.dumps(value, sort_keys=True))
        self.assertEqual(models.files_from_manifest(path), files)

    def test_changed_unknown_boolean_float_duplicate_nonfinite_and_deep_manifest_reject(self):
        original = json.loads(MANIFEST.read_text())
        variants = []
        for key, value in (
            ("schema_version", True),
            ("unknown", "private-manifest-sentinel"),
            ("download_limit_bytes", 4294967296.0),
        ):
            variants.append(json.dumps({**original, key: value}))
        variants.extend(
            (
                MANIFEST.read_text().replace(
                    '"schema_version": 1', '"schema_version": 1, "schema_version": 1'
                ),
                '{"schema_version":NaN}',
                "[" * 2000 + "0" + "]" * 2000,
            )
        )
        path = self.root / "bad.json"
        for value in variants:
            path.write_text(value)
            with (
                self.subTest(length=len(value)),
                self.assertRaises(models.ModelSetupError) as caught,
            ):
                models.files_from_manifest(path)
            self.assertNotIn("private-manifest-sentinel", str(caught.exception))

    def test_manifest_symlink_hardlink_fifo_and_byte_limit_reject(self):
        for name, kind in (
            ("link", "symlink"),
            ("hard", "hardlink"),
            ("pipe", "fifo"),
            ("large", "large"),
        ):
            path = self.root / name
            if kind == "symlink":
                path.symlink_to(MANIFEST)
            elif kind == "hardlink":
                os.link(MANIFEST, path)
            elif kind == "fifo":
                os.mkfifo(path)
            else:
                path.write_bytes(b" " * 65537)
            with self.subTest(kind=kind), self.assertRaises(models.ModelSetupError):
                models.files_from_manifest(path)
            path.unlink()

    def test_model_paths_urls_and_numeric_types_are_bounded(self):
        baseline = {
            "relative": self.file.relative,
            "url": self.file.url,
            "size": self.file.size,
            "sha256": self.file.sha256,
        }
        for changes in (
            {"relative": "../outside"},
            {"relative": "a//b"},
            {"relative": "/absolute"},
            {"relative": "a\\b"},
            {"size": True},
            {"size": 1.0},
            {"size": 4 * 1024**3},
            {"url": "http://huggingface.co/file"},
            {"url": "https://huggingface.co@127.0.0.1/private"},
            {"url": "https://huggingface.co/file?private=secret"},
            {"url": "https://huggingface.co:bad/file"},
            {"url": "https://huggingface.co/\nfile"},
            {"sha256": "X" * 64},
        ):
            with self.subTest(changes=tuple(changes)), self.assertRaises(models.ModelSetupError):
                models.ModelFile(**{**baseline, **changes})

    def test_redirects_allow_only_reviewed_https_hosts_and_bounded_r2_names(self):
        for url in (
            "https://cas-bridge.xethub.hf.co/path?signature=opaque",
            "https://us.aws.cdn.hf.co/path?signature=opaque",
            "https://" + "a" * 32 + ".r2.cloudflarestorage.com/blob?signature=opaque",
        ):
            models.validate_url(url, redirect=True)
        for url in (
            "http://huggingface.co/path",
            "https://huggingface.co.spoof.test/path",
            "https://user:private@huggingface.co/path",
            "https://127.0.0.1/path",
            "https://unreviewed.r2.cloudflarestorage.com/path",
            "https://huggingface.co/path#private",
        ):
            with self.subTest(url=url), self.assertRaises(models.ModelSetupError):
                models.validate_url(url, redirect=True)

    def test_failed_lock_contender_preserves_original_inode_bytes_and_exclusion(self):
        with models.cache_lock(self.cache):
            path = self.cache / ".prepare.lock"
            path.write_bytes(b"owner-record")
            before = path.stat().st_ino
            with self.assertRaises(models.ModelSetupError) as caught, models.cache_lock(self.cache):
                self.fail("Second lock acquired")
            self.assertEqual(caught.exception.code, "model_cache_busy")
            self.assertEqual(path.stat().st_ino, before)
            self.assertEqual(path.read_bytes(), b"owner-record")
        with models.cache_lock(self.cache):
            self.assertEqual(path.stat().st_ino, before)

    def test_lock_rejects_foreign_aliases_without_unlinking_them(self):
        models.owned_directory(self.cache)
        foreign = self.root / "foreign"
        foreign.write_bytes(b"foreign-private-marker")
        foreign.chmod(0o600)
        lock = self.cache / ".prepare.lock"
        for kind in ("symlink", "hardlink", "fifo"):
            if kind == "symlink":
                lock.symlink_to(foreign)
            elif kind == "hardlink":
                os.link(foreign, lock)
            else:
                os.mkfifo(lock, 0o600)
            with (
                self.subTest(kind=kind),
                self.assertRaises((models.ModelSetupError, OSError)),
                models.cache_lock(self.cache),
            ):
                self.fail("Unsafe lock accepted")
            self.assertTrue(lock.exists() or lock.is_symlink())
            self.assertEqual(foreign.read_bytes(), b"foreign-private-marker")
            lock.unlink()

    def test_atomic_download_has_exact_digest_size_permissions_and_no_partials(self):
        self.fetch()
        path = self.cache / self.file.relative
        self.assertEqual(path.read_bytes(), self.body)
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        self.assertTrue(models.verified(path, self.file))
        self.assertEqual(list(self.scratch.iterdir()), [])
        opener = Mock()
        models.fetch(self.file, self.cache, self.scratch, opener, time.monotonic() + 5)
        opener.assert_not_called()

    def test_wrong_existing_file_is_preserved_and_no_fetch_occurs(self):
        target = self.cache / self.file.relative
        target.parent.mkdir(parents=True)
        target.write_bytes(b"wrong")
        target.chmod(0o644)
        opener = Mock()
        with self.assertRaises(models.ModelSetupError):
            models.fetch(self.file, self.cache, self.scratch, opener, time.monotonic() + 5)
        opener.assert_not_called()
        self.assertEqual(target.read_bytes(), b"wrong")

    def test_bad_status_compression_size_digest_and_deadline_leave_no_target_or_partial(self):
        variants = [
            Response(self.body, status=302),
            Response(self.body, headers={"Content-Encoding": "gzip"}),
            Response(self.body, headers={"Content-Length": "1"}),
            Response(self.body + b"overflow"),
            Response(b"short"),
            Response(b"x" * len(self.body)),
        ]
        for response in variants:
            with self.subTest(status=response.status), self.assertRaises(models.ModelSetupError):
                self.fetch(response)
            self.assertFalse((self.cache / self.file.relative).exists())
            self.assertEqual(list(self.scratch.iterdir()), [])
        with self.assertRaises(models.ModelSetupError):
            self.fetch(deadline=time.monotonic() - 1)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_target_symlink_never_replaces_or_modifies_foreign_file(self):
        target = self.cache / self.file.relative
        target.parent.mkdir(parents=True)
        foreign = self.root / "private-target"
        foreign.write_bytes(self.body)
        target.symlink_to(foreign)
        with self.assertRaises(models.ModelSetupError):
            self.fetch()
        self.assertTrue(target.is_symlink())
        self.assertEqual(foreign.read_bytes(), self.body)

    def test_runtime_layout_adds_only_empty_traversable_v2_root_and_preserves_pinned_files(self):
        self.fetch()
        legacy = self.cache / "ollama/manifests/registry.ollama.ai/library/qwen3/4b-instruct"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"verified-legacy-manifest")
        legacy.chmod(0o644)
        before = {
            path.relative_to(self.cache): (path.stat().st_ino, path.read_bytes())
            for path in self.cache.rglob("*")
            if path.is_file()
        }
        models.prepare_runtime_layout(self.cache)
        v2 = self.cache / "ollama/manifests-v2"
        self.assertEqual(v2.stat().st_mode & 0o777, 0o755)
        self.assertEqual(list(v2.iterdir()), [])
        after = {
            path.relative_to(self.cache): (path.stat().st_ino, path.read_bytes())
            for path in self.cache.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)
        self.assertTrue(models.verified(self.cache / self.file.relative, self.file))
        inode = v2.stat().st_ino
        v2.chmod(0o700)
        models.prepare_runtime_layout(self.cache)
        self.assertEqual(v2.stat().st_ino, inode)
        self.assertEqual(v2.stat().st_mode & 0o777, 0o755)

    def test_runtime_layout_rejects_shadow_content_and_unsafe_aliases_without_deleting_them(self):
        models.owned_directory(self.cache / "ollama")
        target = self.cache / "ollama/manifests-v2"
        foreign = self.root / "foreign-models"
        foreign.mkdir()
        marker = foreign / "private-model-marker"
        marker.write_bytes(b"preserved")
        for kind in ("symlink", "file", "fifo", "nonempty", "writable"):
            if kind == "symlink":
                target.symlink_to(foreign, target_is_directory=True)
            elif kind == "file":
                target.write_bytes(b"preserved-file")
            elif kind == "fifo":
                os.mkfifo(target)
            else:
                target.mkdir()
                if kind == "nonempty":
                    (target / "unverified-manifest").write_bytes(b"shadow")
                else:
                    target.chmod(0o777)
            with self.subTest(kind=kind), self.assertRaises(models.ModelSetupError) as caught:
                models.prepare_runtime_layout(self.cache)
            self.assertNotIn("private-model-marker", str(caught.exception))
            self.assertEqual(marker.read_bytes(), b"preserved")
            if kind == "nonempty":
                self.assertEqual((target / "unverified-manifest").read_bytes(), b"shadow")
                shutil.rmtree(target)
            elif kind == "writable":
                self.assertEqual(target.stat().st_mode & 0o777, 0o777)
                target.rmdir()
            else:
                self.assertTrue(target.exists() or target.is_symlink())
                target.unlink()

    def test_runtime_layout_rejects_a_symlinked_ollama_parent(self):
        models.owned_directory(self.cache)
        foreign = self.root / "foreign-cache"
        foreign.mkdir()
        (self.cache / "ollama").symlink_to(foreign, target_is_directory=True)
        with self.assertRaises(models.ModelSetupError):
            models.prepare_runtime_layout(self.cache)
        self.assertEqual(list(foreign.iterdir()), [])
        self.assertTrue((self.cache / "ollama").is_symlink())

    def test_main_verifies_without_fetch_then_prepares_empty_v2_before_reporting_success(self):
        fake_file = self.root / "local-setup/scripts/local_models.py"
        cache = self.root / "local-setup/.local/models"
        target = cache / self.file.relative
        target.parent.mkdir(parents=True)
        target.write_bytes(self.body)
        target.chmod(0o644)
        # The production helper owns a standalone POSIX fork. Exercise that
        # real path in a fresh interpreter instead of inheriting SDK C threads
        # from the full unit suite; Python's thread count need not include them.
        code = r"""
import importlib.util,io,json,sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('models_fixture',sys.argv[1]);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
file=m.ModelFile(*json.loads(sys.argv[4]))
output=io.StringIO()
real_worker=m.run_worker
def bounded_worker(*args,**kwargs):return real_worker(*args,maximum_seconds=2,**kwargs)
with patch.object(m,'__file__',sys.argv[2]),patch.object(m,'files_from_manifest',return_value=(file,)),patch.object(m,'run_worker',wraps=bounded_worker) as worker,patch.object(m.urllib.request,'build_opener',side_effect=AssertionError('Network setup is forbidden')),redirect_stdout(output):
 result=m.main(['--manifest',sys.argv[3]])
assert result==0
worker.assert_called_once()
assert worker.call_args.args[3] is False
assert not m.multiprocessing.active_children()
print(output.getvalue(),end='')
"""
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-W",
                "error::DeprecationWarning",
                "-c",
                code,
                str(HELPER),
                str(fake_file),
                str(MANIFEST),
                json.dumps([self.file.relative, self.file.url, self.file.size, self.file.sha256]),
            ],
            cwd=self.root,
            env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(list((cache / "ollama/manifests-v2").iterdir()), [])
        value = json.loads(result.stdout)
        self.assertEqual(
            value,
            {
                "status": "verified",
                "profile": models.PROFILE,
                "files": 1,
                "model_bytes": self.file.size,
                "runtime_downloads": False,
            },
        )

    def test_failed_file_verification_never_prepares_runtime_layout_or_claims_success(self):
        fake_file = self.root / "local-setup/scripts/local_models.py"
        cache = self.root / "local-setup/.local/models"
        output = io.StringIO()
        with (
            patch.object(models, "__file__", str(fake_file)),
            patch.object(models, "files_from_manifest", return_value=(self.file,)),
            patch.object(models, "run_worker", side_effect=models.ModelSetupError()),
            redirect_stdout(output),
        ):
            result = models.main(["--manifest", str(MANIFEST)])
        self.assertEqual(result, 1)
        self.assertFalse((cache / "ollama/manifests-v2").exists())
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "failed", "code": "local_model_setup_required"},
        )

    def test_invalid_child_budgets_fail_before_process_creation(self):
        for seconds in (True, 0, -1, float("inf"), float("nan"), 1801, 10**1000):
            with (
                self.subTest(seconds=seconds),
                patch.object(models.multiprocessing, "get_context") as context,
            ):
                with self.assertRaises(models.ModelSetupError):
                    models.run_worker(
                        (self.file,), self.cache, self.scratch, False, maximum_seconds=seconds
                    )
                context.assert_not_called()

    def test_child_alarm_releases_inherited_lock_after_parent_descriptor_loss(self):
        # A fresh single-threaded supervisor retains ownership/reaps its child.
        # Closing its own lock FD models descriptor loss without orphaning a test.
        code = r"""
import importlib.util,sys,time,multiprocessing,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('models_fixture',sys.argv[1]);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
root=Path(sys.argv[2]);cache=root/'cache';scratch=root/'child-scratch';scratch.mkdir(mode=0o700);marker=root/'entered'
def slow(*args):marker.write_text('ready');time.sleep(10);return True
m.verified=slow
file=m.ModelFile('whisper/a','https://huggingface.co/a',1,'a'*64)
p=None
try:
 with m.cache_lock(cache):
  inode=(cache/'.prepare.lock').stat().st_ino
  p=multiprocessing.get_context('fork').Process(target=m._worker,args=((file,),str(cache),str(scratch),False,.3));p.start()
  deadline=time.monotonic()+1
  while not marker.exists() and time.monotonic()<deadline:time.sleep(.005)
  assert marker.exists()
 try:
  with m.cache_lock(cache):raise AssertionError('Inherited lock was lost')
 except m.ModelSetupError as e:assert e.code=='model_cache_busy'
 p.join(timeout=2);assert not p.is_alive();assert p.exitcode==124
 with m.cache_lock(cache):assert (cache/'.prepare.lock').stat().st_ino==inode
 assert not scratch.exists()
 print(json.dumps({'status':'passed','child_timeout':True,'lock_retained':True,'reaped':True}))
finally:
 if p is not None:
  if p.is_alive():p.kill();p.join(timeout=1)
  p.close()
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", code, str(HELPER), str(self.root)],
            cwd=self.root,
            env={"PATH": os.defpath},
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"status": "passed", "child_timeout": True, "lock_retained": True, "reaped": True},
        )

    def test_main_contender_never_unlinks_the_running_preparer_lock(self):
        fake_file = self.root / "local-setup/scripts/local_models.py"
        cache = self.root / "local-setup/.local/models"
        with models.cache_lock(cache):
            lock = cache / ".prepare.lock"
            lock.write_bytes(b"original-running-owner")
            inode = lock.stat().st_ino
            output = io.StringIO()
            with (
                patch.object(models, "__file__", str(fake_file)),
                patch.object(models, "run_worker") as worker,
                redirect_stdout(output),
            ):
                result = models.main(["--fetch", "--manifest", str(MANIFEST)])
            self.assertEqual(result, 1)
            self.assertEqual(
                json.loads(output.getvalue()), {"status": "failed", "code": "model_cache_busy"}
            )
            worker.assert_not_called()
            self.assertEqual(lock.stat().st_ino, inode)
            self.assertEqual(lock.read_bytes(), b"original-running-owner")

    def test_removed_owned_scratch_never_suppresses_the_original_error(self):
        models.owned_directory(self.cache)
        original = models.ModelSetupError("model_timeout")
        with (
            self.assertRaises(models.ModelSetupError) as caught,
            models.scratch_directory(self.cache) as scratch,
        ):
            shutil.rmtree(scratch)
            raise original
        self.assertIs(caught.exception, original)

    def test_replaced_scratch_is_not_deleted_as_if_still_owned(self):
        models.owned_directory(self.cache)
        with (
            self.assertRaises(models.ModelSetupError) as caught,
            models.scratch_directory(self.cache) as scratch,
        ):
            scratch.rename(self.root / "original-scratch")
            scratch.mkdir(mode=0o700)
            (scratch / "foreign").write_bytes(b"preserved")
        self.assertEqual(caught.exception.code, "model_cleanup_incomplete")
        self.assertEqual((scratch / "foreign").read_bytes(), b"preserved")

    def test_parent_timeout_kills_and_reaps_a_child_ignoring_term(self):
        code = r"""
import importlib.util,sys,time,signal,os,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('models_fixture',sys.argv[1]);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
root=Path(sys.argv[2]);cache=root/'parent-cache';marker=root/'child-pid'
def stuck(*args):
 signal.signal(signal.SIGTERM,signal.SIG_IGN);signal.signal(signal.SIGALRM,signal.SIG_IGN)
 marker.write_text(str(os.getpid()));time.sleep(10)
m._worker=stuck
file=m.ModelFile('whisper/a','https://huggingface.co/a',1,'a'*64)
with m.cache_lock(cache),m.scratch_directory(cache) as scratch:
 try:m.run_worker((file,),cache,scratch,False,maximum_seconds=.15)
 except m.ModelSetupError as e:assert e.code=='model_timeout'
 else:raise AssertionError('Unbounded child passed')
 assert marker.exists()
 try:os.waitpid(int(marker.read_text()),os.WNOHANG)
 except ChildProcessError:pass
 else:raise AssertionError('Owned child was not reaped')
assert not scratch.exists()
print(json.dumps({'status':'passed','parent_timeout':True,'killed_reaped':True,'scratch_removed':True}))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", code, str(HELPER), str(self.root)],
            cwd=self.root,
            env={"PATH": os.defpath},
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "status": "passed",
                "parent_timeout": True,
                "killed_reaped": True,
                "scratch_removed": True,
            },
        )

    def test_scratch_cleanup_failure_retains_primary_timeout_separately(self):
        models.owned_directory(self.cache)
        original = models.ModelSetupError("model_timeout")
        with (
            self.assertRaises(models.ModelSetupError) as caught,
            patch.object(models.shutil, "rmtree", side_effect=OSError("private-cleanup-sentinel")),
            models.scratch_directory(self.cache),
        ):
            raise original
        self.assertIs(caught.exception, original)
        self.assertEqual(caught.exception.code, "model_timeout")
        self.assertTrue(caught.exception.cleanup_incomplete)
        self.assertNotIn("private-cleanup", str(caught.exception))

    def test_real_child_combines_timeout_and_cleanup_failure_without_losing_either(self):
        code = r"""
import importlib.util,sys,json
from pathlib import Path
spec=importlib.util.spec_from_file_location('models_fixture',sys.argv[1]);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
root=Path(sys.argv[2]);cache=root/'combined-cache'
def fail_cleanup(*args):raise OSError('private-cleanup-sentinel')
def timeout(*args):m.shutil.rmtree=fail_cleanup;raise m.ModelSetupError('model_timeout')
m.verified=timeout
file=m.ModelFile('whisper/a','https://huggingface.co/a',1,'a'*64)
with m.cache_lock(cache),m.scratch_directory(cache) as scratch:
 try:m.run_worker((file,),cache,scratch,False,maximum_seconds=1)
 except m.ModelSetupError as e:
  assert e.code=='model_timeout' and e.cleanup_incomplete is True
 else:raise AssertionError('Combined failure passed')
assert not scratch.exists()
print(json.dumps({'status':'passed','code':'model_timeout','cleanup_incomplete':True,'parent_cleanup':True}))
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", code, str(HELPER), str(self.root)],
            cwd=self.root,
            env={"PATH": os.defpath},
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            json.loads(result.stdout),
            {
                "status": "passed",
                "code": "model_timeout",
                "cleanup_incomplete": True,
                "parent_cleanup": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
