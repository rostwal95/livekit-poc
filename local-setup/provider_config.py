"""Explicit owner-only provider credentials; never emit their values."""

from __future__ import annotations

import base64
import os
import re
import ssl
import stat
from dataclasses import dataclass, field
from pathlib import Path

KEYS = frozenset({"DEEPGRAM_API_KEY", "OPENAI_API_KEY", "ELEVEN_API_KEY"})
MAX_BYTES = 8192


class ProviderConfigError(ValueError):
    def __init__(self, code: str) -> None:
        if code not in {
            "provider_file_unsafe",
            "provider_values_invalid",
            "provider_setup_required",
        }:
            raise ValueError("Unsupported provider configuration category")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class ProviderCredentials:
    _values: tuple[tuple[str, str], ...] = field(repr=False)

    def environment(self) -> dict[str, str]:
        return dict(self._values)

    def presence(self) -> dict[str, bool]:
        return {name: bool(value) for name, value in self._values}


def read_credentials(path: Path, *, complete: bool = True) -> ProviderCredentials:
    """Read bounded validated dotenv data; do not evaluate or interpolate it."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1
                or not 1 <= info.st_size <= MAX_BYTES
            ):
                raise ProviderConfigError("provider_file_unsafe")
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ProviderConfigError("provider_file_unsafe")
    except (OSError, ValueError) as error:
        if isinstance(error, ProviderConfigError):
            raise
        raise ProviderConfigError("provider_file_unsafe") from None
    values: dict[str, str] = {}
    try:
        for line in raw.decode("utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            found = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*)", line)
            if found is None or found[1] not in KEYS or found[1] in values:
                raise ProviderConfigError("provider_values_invalid")
            value = found[2]
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ProviderConfigError("provider_values_invalid")
                value = value[1:-1]
            if value and (
                not 16 <= len(value) <= 512
                or any(not 33 <= ord(character) <= 126 for character in value)
                or value.lower()
                in {"replace_with_your_api_key", "your_api_key_here", "paste_your_api_key_here"}
            ):
                raise ProviderConfigError("provider_values_invalid")
            values[found[1]] = value
    except (UnicodeError, RecursionError):
        raise ProviderConfigError("provider_values_invalid") from None
    if set(values) != KEYS:
        raise ProviderConfigError("provider_values_invalid")
    if complete and not all(values.values()):
        raise ProviderConfigError("provider_setup_required")
    return ProviderCredentials(tuple(sorted(values.items())))


def create_template(path: Path) -> bool:
    """Never replace an existing credential file or modify a user's keys."""
    if path.exists() or path.is_symlink():
        read_credentials(path, complete=False)
        return False
    raw = (
        b"# Optional provider demo credentials. Paste values locally; never commit this file.\n"
        b"# Normal scripted/local-model startup does not enable cloud providers.\n"
        b"DEEPGRAM_API_KEY=\nOPENAI_API_KEY=\nELEVEN_API_KEY=\n"
    )
    try:
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
        ) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise ProviderConfigError("provider_file_unsafe") from None
    return True


MAX_CA_BYTES = 512 * 1024
_CA_BLOCK = re.compile(
    rb"-----BEGIN CERTIFICATE-----\r?\n([A-Za-z0-9+/=\r\n]+)-----END CERTIFICATE-----"
)


class ProviderCAError(ValueError):
    """Finite public-trust configuration failure; never include certificate content."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in {"provider_ca_unsafe", "provider_ca_invalid"}:
            raise ValueError("Unsupported provider CA category")
        self.code = code
        super().__init__(code)


def _ca_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_uid,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def read_ca_bundle(path: Path) -> bytes:
    """Validate an explicit public CA snapshot; return exact verified bytes only.

    This does not read provider credentials, trust ambient CA/proxy options or
    configure TLS globally. The caller owns an immutable read-only runtime copy.
    """
    if not isinstance(path, Path) or not path.is_absolute():
        raise ProviderCAError("provider_ca_unsafe")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid not in {0, os.getuid()}
                or stat.S_IMODE(before.st_mode) & 0o022
                or before.st_nlink != 1
                or not 1 <= before.st_size <= MAX_CA_BYTES
            ):
                raise ProviderCAError("provider_ca_unsafe")
            raw = stream.read(MAX_CA_BYTES + 1)
            after = os.fstat(stream.fileno())
            if (
                len(raw) != before.st_size
                or len(raw) > MAX_CA_BYTES
                or _ca_identity(before) != _ca_identity(after)
            ):
                raise ProviderCAError("provider_ca_unsafe")
    except (OSError, ValueError) as error:
        if isinstance(error, ProviderCAError):
            raise
        raise ProviderCAError("provider_ca_unsafe") from None
    try:
        cursor = 0
        certificates = set()
        for found in _CA_BLOCK.finditer(raw):
            if raw[cursor : found.start()].strip():
                raise ProviderCAError("provider_ca_invalid")
            encoded = found[1].replace(b"\r", b"").replace(b"\n", b"")
            certificates.add(base64.b64decode(encoded, validate=True))
            cursor = found.end()
        if not certificates or raw[cursor:].strip():
            raise ProviderCAError("provider_ca_invalid")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = True
        context.load_verify_locations(cadata=raw.decode("ascii"))
        anchors = set(context.get_ca_certs(binary_form=True))
        if (
            context.verify_mode != ssl.CERT_REQUIRED
            or context.check_hostname is not True
            or not anchors
            or not certificates <= anchors
        ):
            raise ProviderCAError("provider_ca_invalid")
    except (OSError, ValueError) as error:
        if isinstance(error, ProviderCAError):
            raise
        raise ProviderCAError("provider_ca_invalid") from None
    return raw
