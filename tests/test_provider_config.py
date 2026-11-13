"""No provider calls or real keys: strict private-file and literal-data contracts."""

import importlib.util
import os
import ssl
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import certifi

SPEC = importlib.util.spec_from_file_location(
    "provider_config", Path.cwd() / "local-setup/provider_config.py"
)
module = importlib.util.module_from_spec(SPEC)
__import__("sys").modules[SPEC.name] = module
SPEC.loader.exec_module(module)
SENTINEL = "private-credential-sentinel"


class ProviderConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / ".env.providers"

    def write(self, body):
        self.path.write_bytes(body)
        self.path.chmod(0o600)

    def valid(self, value=SENTINEL):
        return "\n".join(name + "=" + value for name in sorted(module.KEYS)).encode()

    def test_template_is_private_incomplete_and_never_replaces_populated_credentials(self):
        self.assertTrue(module.create_template(self.path))
        self.assertEqual(0o600, stat.S_IMODE(self.path.stat().st_mode))
        self.assertFalse(
            any(module.read_credentials(self.path, complete=False).presence().values())
        )
        with self.assertRaises(module.ProviderConfigError) as caught:
            module.read_credentials(self.path)
        self.assertEqual("provider_setup_required", caught.exception.code)
        self.write(self.valid())
        original = self.path.read_bytes()
        inode = self.path.stat().st_ino
        self.assertFalse(module.create_template(self.path))
        self.assertEqual(original, self.path.read_bytes())
        self.assertEqual(inode, self.path.stat().st_ino)

    def test_quoted_literal_values_are_not_interpolated_and_repr_never_includes_them(self):
        literal = "$(must-not-execute)-$HOME-" + SENTINEL
        self.write(self.valid("'" + literal + "'"))
        result = module.read_credentials(self.path)
        self.assertEqual(set(result.environment().values()), {literal})
        self.assertTrue(all(result.presence().values()))
        self.assertNotIn(SENTINEL, repr(result))
        self.assertNotIn(literal, repr(result.presence()))
        detached = result.environment()
        detached.clear()
        self.assertEqual(3, len(result.environment()))

    def test_unknown_duplicate_missing_invalid_encoding_and_large_data_fail_without_values(self):
        for body in (
            b"UNKNOWN=" + SENTINEL.encode(),
            self.valid() + b"\nOPENAI_API_KEY=" + SENTINEL.encode(),
            b"OPENAI_API_KEY=" + SENTINEL.encode(),
            self.valid("short"),
            self.valid("x" * 513),
            self.valid("paste_your_api_key_here"),
            self.valid("value with spaces " + SENTINEL),
            self.valid("'unclosed"),
            self.valid() + b"\xff",
            b"x" * 8193,
        ):
            with self.subTest(size=len(body)):
                self.write(body)
                with self.assertRaises(module.ProviderConfigError) as caught:
                    module.read_credentials(self.path)
                self.assertNotIn(SENTINEL, str(caught.exception))

    def test_missing_public_symlink_hardlink_and_fifo_paths_refuse_without_modification(self):
        with self.assertRaises(module.ProviderConfigError):
            module.read_credentials(self.path)
        self.write(self.valid())
        original = self.path.read_bytes()
        self.path.chmod(0o644)
        with self.assertRaises(module.ProviderConfigError):
            module.read_credentials(self.path)
        self.path.chmod(0o600)
        link = self.path.with_name("link")
        link.symlink_to(self.path)
        with self.assertRaises(module.ProviderConfigError):
            module.read_credentials(link)
        link.unlink()
        os.link(self.path, link)
        with self.assertRaises(module.ProviderConfigError):
            module.read_credentials(self.path)
        link.unlink()
        fifo = self.path.with_name("fifo")
        os.mkfifo(fifo)
        with self.assertRaises(module.ProviderConfigError):
            module.read_credentials(fifo)
        self.assertEqual(original, self.path.read_bytes())


class ProviderCATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A public packaged Mozilla CA is a real offline parser fixture. Do not
        # inspect or extract the operator's OS/private trust store or credentials.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=certifi.where())
        public_ca = context.get_ca_certs(binary_form=True)[0]
        cls.public_pem = ssl.DER_cert_to_PEM_cert(public_ca).encode("ascii")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / "public-ca.pem"

    def write_ca(self, raw=None, mode=0o644):
        self.path.write_bytes(self.public_pem if raw is None else raw)
        self.path.chmod(mode)

    def test_actual_public_ca_is_verified_and_exact_bytes_return_without_global_tls_changes(self):
        default_factory = ssl._create_default_https_context
        for mode in (0o644, 0o640, 0o600):
            with self.subTest(mode=mode):
                self.write_ca(mode=mode)
                info = self.path.stat()
                self.assertEqual(module.read_ca_bundle(self.path), self.public_pem)
                self.assertEqual(self.path.stat().st_ino, info.st_ino)
                self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), mode)
        self.assertIs(ssl._create_default_https_context, default_factory)
        self.assertEqual(module.read_ca_bundle(self.path), self.path.read_bytes())

    def test_certificate_only_bundles_allow_duplicates_and_whitespace_but_reject_other_data(self):
        raw = b"\n" + self.public_pem + b"\n" + self.public_pem + b"\n\t"
        self.write_ca(raw)
        self.assertEqual(module.read_ca_bundle(self.path), raw)
        for raw in (
            self.public_pem + b"PRIVATE-GARBAGE",
            b"# PRIVATE-COMMENT\n" + self.public_pem,
            self.public_pem + b"\n# trailing-label",
            b"-----BEGIN PRIVATE KEY-----\nPRIVATE-SYNTHETIC\n-----END PRIVATE KEY-----\n",
            self.public_pem + b"-----BEGIN PRIVATE KEY-----\nPRIVATE\n-----END PRIVATE KEY-----",
            b"\n ",
            b"-----BEGIN CERTIFICATE-----\nnotbase64!\n-----END CERTIFICATE-----\n",
            b"-----BEGIN CERTIFICATE-----\nYWJjZA==\n-----END CERTIFICATE-----\n",
            self.public_pem + b"\x00",
        ):
            with self.subTest(bytes=len(raw)):
                self.write_ca(raw)
                with self.assertRaises(module.ProviderCAError) as caught:
                    module.read_ca_bundle(self.path)
                self.assertEqual(caught.exception.code, "provider_ca_invalid")
                self.assertNotIn("PRIVATE", str(caught.exception))

    def test_missing_relative_symlink_hardlink_fifo_directory_and_large_files_fail_closed(self):
        with self.assertRaises(module.ProviderCAError):
            module.read_ca_bundle(self.path)
        with self.assertRaises(module.ProviderCAError):
            module.read_ca_bundle(Path("relative-ca.pem"))
        self.write_ca()
        link = self.root / "link.pem"
        link.symlink_to(self.path)
        with self.assertRaises(module.ProviderCAError):
            module.read_ca_bundle(link)
        link.unlink()
        os.link(self.path, link)
        with self.assertRaises(module.ProviderCAError):
            module.read_ca_bundle(self.path)
        link.unlink()
        fifo = self.root / "fifo.pem"
        os.mkfifo(fifo)
        for path in (fifo, self.root):
            with self.subTest(kind=path.name), self.assertRaises(module.ProviderCAError):
                module.read_ca_bundle(path)
        self.write_ca(self.public_pem + b" " * module.MAX_CA_BYTES)
        with self.assertRaises(module.ProviderCAError) as caught:
            module.read_ca_bundle(self.path)
        self.assertEqual(caught.exception.code, "provider_ca_unsafe")

    def test_unsafe_permissions_or_foreign_owner_are_rejected_without_modification(self):
        for mode in (0o666, 0o664, 0o646, 0o622):
            self.write_ca(mode=mode)
            before = self.path.read_bytes()
            with self.subTest(mode=mode), self.assertRaises(module.ProviderCAError):
                module.read_ca_bundle(self.path)
            self.assertEqual(self.path.read_bytes(), before)
        self.write_ca()
        before = self.path.stat()
        fields = {
            name: getattr(before, name)
            for name in (
                "st_dev",
                "st_ino",
                "st_uid",
                "st_mode",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        }
        foreign = SimpleNamespace(**{**fields, "st_uid": os.getuid() + 1})
        with (
            patch.object(module.os, "fstat", return_value=foreign),
            self.assertRaises(module.ProviderCAError),
        ):
            module.read_ca_bundle(self.path)
        root_owned = SimpleNamespace(**{**fields, "st_uid": 0})
        with patch.object(module.os, "fstat", return_value=root_owned):
            self.assertEqual(module.read_ca_bundle(self.path), self.public_pem)

    def test_changed_descriptor_metadata_is_rejected_before_trusting_the_bundle(self):
        self.write_ca()
        before = self.path.stat()
        fields = {
            name: getattr(before, name)
            for name in (
                "st_dev",
                "st_ino",
                "st_uid",
                "st_mode",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
        }
        changed = SimpleNamespace(**{**fields, "st_mtime_ns": before.st_mtime_ns + 1})
        with (
            patch.object(module.os, "fstat", side_effect=[before, changed]),
            self.assertRaises(module.ProviderCAError) as caught,
        ):
            module.read_ca_bundle(self.path)
        self.assertEqual(caught.exception.code, "provider_ca_unsafe")

    def test_ssl_context_requires_real_ca_anchors_and_certificate_verification(self):
        self.write_ca()
        context = Mock()
        context.get_ca_certs.return_value = []
        with (
            patch.object(module.ssl, "SSLContext", return_value=context) as constructor,
            self.assertRaises(module.ProviderCAError) as caught,
        ):
            module.read_ca_bundle(self.path)
        constructor.assert_called_once_with(ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        context.load_verify_locations.assert_called_once_with(
            cadata=self.public_pem.decode("ascii")
        )
        self.assertEqual(caught.exception.code, "provider_ca_invalid")

    def test_credential_loader_does_not_accept_ca_configuration_or_change_its_private_file_contract(
        self,
    ):
        self.write_ca()
        self.assertEqual(module.KEYS, {"DEEPGRAM_API_KEY", "OPENAI_API_KEY", "ELEVEN_API_KEY"})
        self.assertEqual(module.MAX_BYTES, 8192)
        with self.assertRaises(module.ProviderConfigError):
            module.read_credentials(self.path)
        with self.assertRaises(ValueError):
            module.ProviderConfigError("provider_ca_invalid")
        for code in ("PRIVATE", None, True):
            with self.subTest(code=code), self.assertRaises(ValueError):
                module.ProviderCAError(code)
