"""Offline artifact-contract fixtures; the explicit gate owns actual builds."""

from __future__ import annotations

import io
import stat
import tarfile
import tempfile
import tomllib
import unittest
import warnings
import zipfile
from pathlib import Path

from harness.package_check import (
    PackageCheckError,
    Runner,
    archive_name,
    metadata,
    retain_artifacts,
    sdist_payload,
    wheel_payload,
)

ROOT = Path(__file__).resolve().parents[3]
MEMBER = ROOT / "projects/agent-continuity/python"
METADATA = b"""Metadata-Version: 2.4
Name: agent-continuity
Version: 0.1.0
Requires-Python: <3.15,>=3.14
Provides-Extra: postgres
Requires-Dist: psycopg[binary]==3.3.8; extra == "postgres"
Requires-Dist: prometheus-client==0.26.0; extra == "postgres"
Provides-Extra: telemetry
Requires-Dist: opentelemetry-api==1.45.2; extra == "telemetry"
Requires-Dist: opentelemetry-sdk==1.45.2; extra == "telemetry"
Requires-Dist: opentelemetry-exporter-otlp-proto-http==1.45.2; extra == "telemetry"

"""
PAYLOAD = {"continuity_lab/__init__.py": b'"""Fixture."""\n', "continuity_lab/py.typed": b""}


class ArtifactContracts(unittest.TestCase):
    def test_only_member_owns_continuity_and_root_dependency_is_explicit(self):
        root = tomllib.loads((ROOT / "pyproject.toml").read_text())
        member = tomllib.loads((MEMBER / "pyproject.toml").read_text())
        self.assertEqual(root["tool"]["setuptools"]["packages"]["find"]["include"], ["services*"])
        self.assertIn("agent-continuity==0.1.0", root["project"]["dependencies"])
        self.assertEqual(root["tool"]["uv"]["sources"]["agent-continuity"], {"workspace": True})
        self.assertEqual(member["project"]["dependencies"], [])
        self.assertEqual(member["tool"]["setuptools"]["packages"]["find"]["where"], ["src"])
        self.assertFalse((ROOT / "continuity_lab").exists())
        self.assertTrue((MEMBER / "src/continuity_lab/py.typed").is_file())

    def test_archive_names_reject_traversal_absolute_and_cross_platform_aliases(self):
        for value in ("../secret", "/tmp/secret", "a/../b", "a\\b", "C:/secret", "a//b", "./a"):
            with self.subTest(value=value), self.assertRaises(PackageCheckError):
                archive_name(value)
        archive_name("agent_continuity-0.1.0/src/continuity_lab/api.py")

    def test_metadata_has_no_undeclared_base_dependencies_or_extra_drift(self):
        metadata(METADATA)
        for raw in (
            METADATA.replace(b"Version: 0.1.0", b"Version: 0.2.0"),
            METADATA.replace(b"Provides-Extra: postgres", b"Provides-Extra: hidden"),
            METADATA.replace(b"\n\n", b"\nRequires-Dist: fastapi==0.162.2\n\n"),
            METADATA.replace(
                b"Provides-Extra: postgres", b"Provides-Extra: postgres\nProvides-Extra: postgres"
            ),
        ):
            with self.subTest(raw=raw[:40]), self.assertRaises(PackageCheckError):
                metadata(raw)

    def wheel(self, path, extra=None):
        entries = {
            **PAYLOAD,
            "agent_continuity-0.1.0.dist-info/METADATA": METADATA,
            "agent_continuity-0.1.0.dist-info/top_level.txt": b"continuity_lab\n",
            "agent_continuity-0.1.0.dist-info/entry_points.txt": b"[console_scripts]\nagent-continuity-inquiry = continuity_lab.execution_cli:main\nagent-continuity-worker = continuity_lab.worker_cli:main\n",
        }
        entries.update(extra or {})
        with zipfile.ZipFile(path, "w") as archive:
            for name, raw in entries.items():
                archive.writestr(name, raw)

    def test_wheel_requires_exact_namespace_marker_and_installed_entrypoints(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.whl"
            self.wheel(path)
            self.assertEqual(wheel_payload(path), PAYLOAD)
            for name in ("services/__init__.py", "harness/__init__.py", "../outside.py"):
                self.wheel(path, {name: b"private"})
                with self.subTest(name=name), self.assertRaises(PackageCheckError):
                    wheel_payload(path)

    def test_wheel_rejects_symlink_and_duplicate_payload_before_consumption(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.whl"
            self.wheel(path)
            with zipfile.ZipFile(path, "a") as archive:
                info = zipfile.ZipInfo("continuity_lab/alias.py")
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, b"outside")
            with self.assertRaises(PackageCheckError):
                wheel_payload(path)
            self.wheel(path)
            with warnings.catch_warnings(record=True) as observed:
                warnings.simplefilter("always")
                with zipfile.ZipFile(path, "a") as archive:
                    archive.writestr("continuity_lab/__init__.py", b"duplicate")
            self.assertEqual(len(observed), 1)
            with self.assertRaises(PackageCheckError):
                wheel_payload(path)

    def test_retained_artifacts_are_private_exact_copies_and_never_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "fixture.whl"
            self.wheel(source)
            target = root / "artifacts"
            paths = {label: source for label in ("wheel", "sdist", "rebuilt_wheel")}
            retain_artifacts(target, paths)
            for label in paths:
                retained = target / label / source.name
                self.assertEqual(retained.read_bytes(), source.read_bytes())
                self.assertEqual(retained.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(PackageCheckError):
                retain_artifacts(target, paths)

    def test_command_diagnostics_never_accept_a_private_fixture_sentinel_on_stderr(self):
        import sys

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runner = Runner(root, Path(sys.executable), root)
            with self.assertRaises(PackageCheckError):
                runner.command(
                    [
                        sys.executable,
                        "-I",
                        "-c",
                        "import sys;print('private-configuration-sentinel',file=sys.stderr)",
                    ],
                    code="consumer_failed",
                )

    def sdist(self, path, *, link=False, omit_metadata=False):
        entries = {"src/" + name: raw for name, raw in PAYLOAD.items()}
        entries.update({"README.md": b"Fixture\n", "pyproject.toml": b"[project]\n"})
        if not omit_metadata:
            entries["PKG-INFO"] = METADATA
        with tarfile.open(path, "w:gz") as archive:
            for name, raw in entries.items():
                info = tarfile.TarInfo("agent_continuity-0.1.0/" + name)
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
            if link:
                info = tarfile.TarInfo("agent_continuity-0.1.0/src/continuity_lab/alias.py")
                info.type = tarfile.SYMTYPE
                info.linkname = "../../outside"
                archive.addfile(info)

    def test_sdist_retains_source_payload_and_refuses_links_and_missing_build_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.tar.gz"
            self.sdist(path)
            self.assertEqual(sdist_payload(path), PAYLOAD)
            for kwargs in ({"link": True}, {"omit_metadata": True}):
                self.sdist(path, **kwargs)
                with self.subTest(kwargs=kwargs), self.assertRaises(PackageCheckError):
                    sdist_payload(path)


if __name__ == "__main__":
    unittest.main()
