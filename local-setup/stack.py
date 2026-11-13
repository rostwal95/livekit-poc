#!/usr/bin/env python3
"""Manage the isolated local infrastructure without evaluating dotenv as code."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

SETUP = Path(__file__).resolve().parent
PROJECT = "livekit-agent-ecosystem"
OWNER_LABEL = "io.livekit-ecosystem.owner"
VOLUMES = ("postgres_data", "application_data", "worker_data")
LOG_SERVICES = (
    "console",
    "control-api",
    "conversation-agent",
    "jaeger",
    "livekit",
    "p1-migrate",
    "p1-worker",
    "postgres",
    "rtc-agent",
)
MODEL_SERVICES = ("p1-llm", "p1-stt", "p1-tts")
MODEL_PROFILE = "p1-local-real-v1"
CONFIG_SCHEMA_VERSION = 1
CREDENTIAL_SCHEMA_VERSION = 2
PORTS = {
    "UI_PORT",
    "API_PORT",
    "LIVEKIT_HTTP_PORT",
    "LIVEKIT_TCP_PORT",
    "LIVEKIT_UDP_PORT",
    "POSTGRES_PORT",
    "JAEGER_UI_PORT",
}
CONFIG_KEYS = PORTS | {"BIND_ADDRESS", "LIVEKIT_NODE_IP", "P1_WORKER_SCOPE", "P1_WORKER_SCHEMA"}
SECRET_KEYS = {
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "LOCAL_ACCESS_TOKEN",
    "POSTGRES_PASSWORD",
    "POSTGRES_ADMIN_PASSWORD",
    "POSTGRES_MIGRATION_PASSWORD",
}
PROVIDER_KEYS = frozenset({"DEEPGRAM_API_KEY", "OPENAI_API_KEY", "ELEVEN_API_KEY"})
REDACTED_SECRET_KEYS = SECRET_KEYS | PROVIDER_KEYS
LEGACY_SECRET_KEYS = SECRET_KEYS - {"POSTGRES_MIGRATION_PASSWORD"}
IMAGE_KEYS = {
    "LIVEKIT_IMAGE",
    "POSTGRES_IMAGE",
    "PYTHON_IMAGE",
    "NODE_IMAGE",
    "NGINX_IMAGE",
    "JAEGER_IMAGE",
}
ENV_PREFIXES = (
    "LIVEKIT_",
    "POSTGRES_",
    "P1_",
    "LOCAL_",
    "UI_",
    "API_",
    "JAEGER_",
    "COMPOSE_",
    "OPENAI_",
    "DEEPGRAM_",
    "ELEVEN_",
    "ELEVENLABS_",
)


class SetupError(ValueError):
    """A safe, actionable configuration or operation failure."""


def regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise SetupError(f"A regular file is required: {path.name}")


def parse_env(path: Path) -> dict[str, str]:
    regular_file(path)
    result: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*)", line)
        if match is None or match[1] in result:
            raise SetupError(f"Invalid or duplicate setting in {path.name} at line {number}")
        value = match[2]
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise SetupError(f"Unclosed quoted setting in {path.name} at line {number}")
            value = value[1:-1]
        if any(char in value for char in ("\0", "\r", "\n")):
            raise SetupError(f"Invalid setting bytes in {path.name} at line {number}")
        result[match[1]] = value
    return result


def validate_config(values: dict[str, str]) -> None:
    unknown = set(values) - CONFIG_KEYS
    if unknown:
        raise SetupError("Unknown local setting names: " + ", ".join(sorted(unknown)))
    for name, pattern in (
        ("P1_WORKER_SCOPE", r"[A-Za-z0-9_-]{1,64}"),
        ("P1_WORKER_SCHEMA", r"[a-z][a-z0-9_]{0,62}"),
    ):
        if name in values and re.fullmatch(pattern, values[name]) is None:
            raise SetupError("Worker scope/schema must be a bounded local identifier")
    if values.get("P1_WORKER_SCHEMA") in {"public", "information_schema"} or values.get(
        "P1_WORKER_SCHEMA", ""
    ).startswith("pg_"):
        raise SetupError("Worker schema must be an application schema")
    required = PORTS | {"BIND_ADDRESS", "LIVEKIT_NODE_IP"}
    if not required <= values.keys():
        raise SetupError("Required local configuration settings are missing")
    for name in PORTS:
        if not re.fullmatch(r"[0-9]{1,5}", values[name]) or not 1024 <= int(values[name]) <= 65535:
            raise SetupError(f"{name} must be a port between 1024 and 65535")
    # Different UDP and TCP protocols may share numbers, but defaults intentionally do not.
    if len({values[name] for name in PORTS}) != len(PORTS):
        raise SetupError("Configured local service ports must be distinct")
    for name in ("BIND_ADDRESS", "LIVEKIT_NODE_IP"):
        try:
            address = ipaddress.IPv4Address(values[name])
        except ipaddress.AddressValueError as error:
            raise SetupError(f"{name} must be an explicit IPv4 address") from error
        if name == "BIND_ADDRESS" and str(address) != "127.0.0.1":
            raise SetupError("BIND_ADDRESS must remain 127.0.0.1 for the local environment")
        if name == "LIVEKIT_NODE_IP" and (address.is_unspecified or address.is_multicast):
            raise SetupError("LIVEKIT_NODE_IP must identify a reachable host address")


def credential_schema(values: dict[str, str]) -> int:
    """Recognize only the complete legacy/current credential inventories."""
    if set(values) == SECRET_KEYS:
        return CREDENTIAL_SCHEMA_VERSION
    if set(values) == LEGACY_SECRET_KEYS:
        return 1
    raise SetupError("Credential file has an unsupported setting schema")


def validate_secrets(path: Path, values: dict[str, str], *, allow_legacy: bool = False) -> None:
    regular_file(path)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
        raise SetupError(".secrets.env must be owned by the current user with mode 0600")
    schema = credential_schema(values)
    if schema != CREDENTIAL_SCHEMA_VERSION and not allow_legacy:
        raise SetupError("Credential schema upgrade is required; run local setup init")
    if values["LIVEKIT_API_KEY"] != "local-ecosystem":
        raise SetupError("LIVEKIT_API_KEY must be the documented local key identifier")
    for name in set(values) - {"LIVEKIT_API_KEY"}:
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", values[name]):
            raise SetupError(f"{name} must contain 32 to 128 URL-safe characters")


def validate_images(values: dict[str, str]) -> None:
    if set(values) != IMAGE_KEYS:
        raise SetupError(
            "images.env must declare exactly the documented infrastructure image names"
        )
    for name, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*_IMAGE", name):
            raise SetupError("images.env contains an unsupported setting name")
        if (
            not re.fullmatch(r"[A-Za-z0-9._/:@-]+", value)
            or ":latest" in value
            or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._/:-]*:[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[a-f0-9]{64}",
                value,
            )
        ):
            raise SetupError(
                f"{name} must use an explicit version tag and immutable SHA-256 digest"
            )


def write_new(path: Path, content: str, mode: int) -> None:
    if path.is_symlink():
        raise SetupError(f"Refusing symlinked local state: {path.name}")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError:
        regular_file(path)
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)


@contextmanager
def initialization_lock(setup: Path) -> Iterator[None]:
    """Serialize private initialization without locking an atomically replaced inode."""
    if os.name != "posix":
        raise SetupError("Private local initialization requires POSIX file permissions")
    import fcntl

    directory = setup / ".generated"
    if directory.is_symlink():
        raise SetupError("Refusing symlinked generated configuration directory")
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / "initialize.lock"
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as error:
        raise SetupError("Private initialization lock is unavailable") from error
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise SetupError("Initialization lock must be a private regular file")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SetupError("Another local initialization is active") from error
        yield
    finally:
        os.close(descriptor)


def upgrade_credentials(path: Path) -> None:
    """Atomically add the migration secret, preserving every existing credential."""
    values = parse_env(path)
    validate_secrets(path, values, allow_legacy=True)
    if credential_schema(values) == CREDENTIAL_SCHEMA_VERSION:
        return
    values["POSTGRES_MIGRATION_PASSWORD"] = secrets.token_urlsafe(36)
    # Validate before writing; interruption before replace retains the intact v1
    # file, and interruption after replace leaves the complete valid v2 file.
    validate_secrets(path, values)
    temporary = None
    try:
        # A hard kill can leave the private temporary file behind. Keep it in
        # already-ignored generated state so git add cannot collect credentials.
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent / ".generated", prefix="credentials-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            stream.write("\n".join(f"{name}={values[name]}" for name in sorted(values)) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        temporary = None
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def initialize(setup: Path = SETUP) -> None:
    setup = setup.resolve()
    example = setup / ".env.example"
    regular_file(example)
    validate_config(parse_env(example))
    with initialization_lock(setup):
        if (setup / ".env").exists():
            validate_config(parse_env(setup / ".env"))
        write_new(setup / ".env", example.read_text(), 0o600)
        credential_path = setup / ".secrets.env"
        if credential_path.exists() or credential_path.is_symlink():
            upgrade_credentials(credential_path)
        else:
            generated = {
                "LIVEKIT_API_KEY": "local-ecosystem",
                **{
                    name: secrets.token_urlsafe(36)
                    for name in sorted(SECRET_KEYS - {"LIVEKIT_API_KEY"})
                },
            }
            write_new(
                credential_path,
                "\n".join(f"{name}={value}" for name, value in generated.items()) + "\n",
                0o600,
            )
        load_settings(setup)
        render_config(setup)


def load_settings(setup: Path = SETUP) -> dict[str, str]:
    local = parse_env(setup / ".env")
    credentials = parse_env(setup / ".secrets.env")
    images = parse_env(setup / "images.env")
    validate_config(local)
    validate_secrets(setup / ".secrets.env", credentials)
    validate_images(images)
    return {**images, **local, **credentials}


def render_config(setup: Path = SETUP) -> None:
    values = load_settings(setup)
    template = setup / "config/livekit.yaml.tmpl"
    regular_file(template)
    try:
        rendered = template.read_text().format(
            node_ip=values["LIVEKIT_NODE_IP"],
            tcp_port=int(values["LIVEKIT_TCP_PORT"]),
            udp_port=int(values["LIVEKIT_UDP_PORT"]),
        )
    except (KeyError, ValueError) as error:
        raise SetupError("LiveKit configuration template uses unsupported fields") from error
    directory = setup / ".generated"
    if directory.is_symlink():
        raise SetupError("Refusing symlinked generated configuration directory")
    directory.mkdir(mode=0o700, exist_ok=True)
    destination = directory / "livekit.yaml"
    if destination.is_symlink():
        raise SetupError("Refusing symlinked generated configuration")
    with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(rendered)
    temporary.chmod(0o644)
    temporary.replace(destination)


def child_environment(values: dict[str, str]) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in values and not key.startswith(ENV_PREFIXES) and not key.endswith("_IMAGE")
    }
    environment.update(values)
    environment["LOCAL_STACK_OWNER"] = stack_owner(values)
    return environment


def stack_owner(values: dict[str, str]) -> str:
    """Identify persistent local state without exposing the operator credential."""
    return hashlib.sha256(values["LOCAL_ACCESS_TOKEN"].encode("utf-8")).hexdigest()


def compose_arguments(setup: Path, observability: bool = False) -> list[str]:
    argv = ["docker", "compose", "--project-name", PROJECT, "--project-directory", str(setup)]
    for name in ("images.env", ".env", ".secrets.env"):
        argv.extend(["--env-file", str(setup / name)])
    argv.extend(["-f", str(setup / "docker-compose.yaml")])
    if observability:
        argv.extend(["--profile", "observability"])
    return argv


def redact(text: str, values: dict[str, str]) -> str:
    for name in REDACTED_SECRET_KEYS:
        value = values.get(name, "")
        if value:
            text = text.replace(value, "[redacted]")
    return text[-8000:]


def run(
    argv: list[str],
    values: dict[str, str],
    setup: Path,
    timeout: int = 30,
    *,
    merge_output: bool = False,
) -> str:
    # Spool output instead of retaining unbounded build/container output in memory.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            completed = subprocess.run(
                argv,
                cwd=setup,
                env=child_environment(values),
                stdout=stdout,
                # Diagnostic commands may send useful events to stderr.
                # Merge only for diagnostics; parsers keep stdout-only results.
                stderr=stdout if merge_output else stderr,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise SetupError("Operation exceeded its declared deadline") from error
        except OSError as error:
            raise SetupError("Required executable is unavailable") from error

        def tail(stream):
            credentials = [
                values[name].encode("utf-8") for name in REDACTED_SECRET_KEYS if values.get(name)
            ]
            overlap = max(map(len, credentials), default=0)
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - 8000 - overlap))
            data = stream.read()
            start = max(0, len(data) - 8000)
            # Match against the overlap but emit only the requested tail. A
            # credential crossing its boundary becomes one complete marker.
            parts: list[bytes] = []
            cursor = start
            if credentials:
                pattern = b"|".join(
                    re.escape(value) for value in sorted(credentials, key=len, reverse=True)
                )
                for match in re.finditer(pattern, data):
                    if match.end() <= start:
                        continue
                    parts.extend((data[cursor : max(cursor, match.start())], b"[redacted]"))
                    cursor = match.end()
            parts.append(data[cursor:])
            return b"".join(parts).decode("utf-8", errors="replace")

        output = redact(tail(stdout), values)
        if completed.returncode:
            detail = redact(tail(stderr), values).strip() or output.strip()
            raise SetupError(
                f"Operation failed with exit {completed.returncode}"
                + (f": {detail}" if detail else "")
            )
        return output


def assert_owned_containers(setup: Path, values: dict[str, str]) -> None:
    """Guard both live containers and persistent volumes before mutation."""
    identifiers = run(
        [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
        ],
        values,
        setup,
    ).split()
    for identifier in identifiers:
        owner = run(
            [
                "docker",
                "inspect",
                "--format",
                '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}',
                identifier,
            ],
            values,
            setup,
        ).strip()
        if not owner or Path(owner).resolve() != setup.resolve():
            raise SetupError(
                "This project name is owned by another checkout; refusing container mutation"
            )
    expected_owner = stack_owner(values)
    for logical_name in VOLUMES:
        name = f"{PROJECT}_{logical_name}"
        existing = run(
            ["docker", "volume", "ls", "--quiet", "--filter", f"name=^{name}$"],
            values,
            setup,
        ).split()
        if name not in existing:
            continue
        owner = run(
            [
                "docker",
                "volume",
                "inspect",
                "--format",
                f'{{{{ index .Labels "{OWNER_LABEL}" }}}}',
                name,
            ],
            values,
            setup,
        ).strip()
        if owner != expected_owner:
            raise SetupError(
                "Persistent local state has a different or missing owner; refusing volume reuse or mutation"
            )


def check_ports(values: dict[str, str], observability: bool = False) -> None:
    names = PORTS if observability else PORTS - {"JAEGER_UI_PORT"}
    for name in sorted(names):
        kind = socket.SOCK_DGRAM if name == "LIVEKIT_UDP_PORT" else socket.SOCK_STREAM
        with socket.socket(socket.AF_INET, kind) as probe:
            try:
                probe.bind((values["BIND_ADDRESS"], int(values[name])))
            except OSError as error:
                raise SetupError(f"Configured host port is unavailable: {name}") from error


def wait_for_http(
    url: str,
    *,
    timeout_seconds: float = 20,
    opener=urllib.request.urlopen,
    clock=time.monotonic,
    pause=time.sleep,
) -> None:
    """Require an actual HTTP 200 within a finite local readiness budget."""
    deadline = clock() + timeout_seconds
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise SetupError("Jaeger UI did not become ready within its declared deadline")
        try:
            with opener(url, timeout=min(2.0, remaining)) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        remaining = deadline - clock()
        if remaining <= 0:
            raise SetupError("Jaeger UI did not become ready within its declared deadline")
        pause(min(0.25, remaining))


def doctor(setup: Path = SETUP, observability: bool = False) -> dict:
    if sys.version_info < (3, 11):  # noqa: UP036 - standalone bootstrap may run outside the venv
        raise SetupError("Python 3.11 or newer is required")
    values = load_settings(setup)
    for relative in ("docker-compose.yaml", "config/livekit.yaml.tmpl", "scripts/smoke.py"):
        regular_file(setup / relative)
    render_config(setup)
    version = run(["docker", "compose", "version", "--short"], values, setup)
    match = re.search(r"v?(\d+)\.", version)
    if not match or int(match[1]) < 2:
        raise SetupError("Docker Compose 2 or newer is required")
    run(["docker", "info", "--format", "{{.ServerVersion}}"], values, setup, 15)
    base = compose_arguments(setup, observability)
    assert_owned_containers(setup, values)
    if (setup.parent / ".git").exists() and run(
        ["git", "ls-files", "--", ".env", ".secrets.env"], values, setup
    ).strip():
        raise SetupError("Local environment and credential files must not be tracked")
    run(base + ["config", "--quiet"], values, setup)
    own_running = bool(run(base + ["ps", "--status", "running", "--quiet"], values, setup).strip())
    if not own_running:
        check_ports(values, observability)
    return {
        "status": "ready",
        "project": PROJECT,
        "runningProjectDetected": own_running,
        "composeVersion": version.strip(),
        "productAcceptance": "not_certified",
    }


def prepare_models(
    setup: Path, values: dict[str, str], *, fetch: bool = False
) -> dict[str, object]:
    """Run only the explicit pinned host helper; startup always verifies without fetch."""
    helper = setup / "scripts/local_models.py"
    manifest = setup / "models/local-model-manifest.json"
    regular_file(helper)
    regular_file(manifest)
    command = [sys.executable, str(helper), "--manifest", str(manifest)]
    if fetch:
        command.append("--fetch")
    try:
        output = run(command, values, setup, 1805)
        if len(output.encode("utf-8")) > 4096:
            raise ValueError
        result = json.loads(output)
        if (
            type(result) is not dict
            or set(result) != {"status", "profile", "files", "model_bytes", "runtime_downloads"}
            or result["status"] != "verified"
            or result["profile"] != MODEL_PROFILE
            or type(result["files"]) is not int
            or result["files"] != 10
            or type(result["model_bytes"]) is not int
            or not 0 < result["model_bytes"] <= 4 * 1024**3
            or result["runtime_downloads"] is not False
        ):
            raise ValueError
    except (SetupError, ValueError, TypeError, UnicodeError):
        raise SetupError(
            "Pinned local model preparation is required; run models-fetch or models-verify"
        ) from None
    return result


def start_models(base: list[str], setup: Path, values: dict[str, str]) -> str:
    """The caller must own the checkout and verify the cache before this bounded start."""
    model_base = base + ["--profile", "p1-models"]
    # Initial image transfer has its own bounded preparation budget. Readiness
    # starts only after that transfer and never downloads model weights.
    run(model_base + ["pull", "--policy", "missing", "p1-llm"], values, setup, 1800)
    run(model_base + ["build", "p1-stt", "p1-tts"], values, setup, 1200)
    return run(
        model_base + ["up", "-d", "--no-deps", "--wait", "--wait-timeout", "90", *MODEL_SERVICES],
        values,
        setup,
        120,
        merge_output=True,
    )


def stop_models(base: list[str], setup: Path, values: dict[str, str]) -> str:
    """Stop only the owned engines and retain all host model files."""
    return run(
        base + ["--profile", "p1-models", "stop", "-t", "15", *MODEL_SERVICES],
        values,
        setup,
        60,
        merge_output=True,
    )


class ProviderStopError(SetupError):
    """A fixed provider boundary; the original cause stays private."""

    def __init__(self, *, cleanup_incomplete: bool) -> None:
        self.cleanup_incomplete = cleanup_incomplete
        super().__init__("provider_stop_failed")


def stop_provider(base: list[str], values: dict[str, str], setup: Path) -> str:
    """Attempt all owned shutdown steps without preserving container credentials."""
    primary: Exception | None = None
    cleanup_failure: Exception | None = None
    output = ""
    try:
        try:
            run(
                base + ["stop", "-t", "35", "conversation-agent", "p1-worker"],
                values,
                setup,
                90,
                merge_output=True,
            )
        except Exception as error:  # noqa: BLE001 - preserve cause without rendering dependency data
            primary = error
        try:
            output = run(
                base + ["up", "-d", "--no-deps", "--wait", "--wait-timeout", "60", "control-api"],
                values,
                setup,
                90,
                merge_output=True,
            )
        except Exception as error:  # noqa: BLE001 - API reversion is independent of credential removal
            if primary is None:
                primary = error
    finally:
        try:
            run(
                base + ["rm", "--force", "conversation-agent"], values, setup, 30, merge_output=True
            )
        except Exception as error:  # noqa: BLE001 - secondary cleanup cannot replace the primary cause
            cleanup_failure = error
    if primary is not None:
        raise ProviderStopError(cleanup_incomplete=cleanup_failure is not None) from primary
    if cleanup_failure is not None:
        raise ProviderStopError(cleanup_incomplete=True) from cleanup_failure
    return output


def provider_configuration(setup: Path) -> ModuleType:
    path = setup / "provider_config.py"
    regular_file(path)
    spec = importlib.util.spec_from_file_location("local_provider_credentials", path)
    if spec is None or spec.loader is None:
        raise SetupError("Provider credential setup is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def provider_values(setup: Path, *, complete: bool) -> dict[str, str]:
    module = provider_configuration(setup)
    try:
        return dict(
            module.read_credentials(setup / ".env.providers", complete=complete).environment()
        )
    except ValueError:
        raise SetupError(
            "Private provider credentials require init-providers and valid populated fields"
        ) from None


def provider_ca_snapshot(setup: Path, source: Path) -> Path:
    """Freeze explicitly selected public trust data outside image/build contexts."""
    module = provider_configuration(setup)
    temporary = None
    try:
        bundle = module.read_ca_bundle(source)
        with initialization_lock(setup):
            target = setup / ".generated" / "provider-ca.pem"
            if target.exists() or target.is_symlink():
                module.read_ca_bundle(target)
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=".provider-ca-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                os.fchmod(stream.fileno(), 0o644)
                stream.write(bundle)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        return target
    except (OSError, ValueError):
        raise SetupError(
            "The explicitly selected provider CA bundle is unsafe or invalid"
        ) from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None, setup: Path = SETUP) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "init",
            "doctor",
            "config",
            "start",
            "status",
            "logs",
            "smoke",
            "stop",
            "reset",
            "token",
            "prepare-postgres",
            "prepare-business",
            "migrate-postgres",
            "upgrade-postgres",
            "upgrade-effects",
            "upgrade-coordination",
            "start-business",
            "stop-business",
            "models-fetch",
            "models-verify",
            "start-models",
            "stop-models",
            "start-local-real",
            "stop-local-real",
            "init-providers",
            "check-providers",
            "start-provider",
            "stop-provider",
            "start-workers",
            "stop-workers",
            "init-worker-fixtures",
            "worker-status",
        ],
    )
    parser.add_argument("--observability", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--service", choices=LOG_SERVICES, help="Select one service for logs only")
    parser.add_argument(
        "--provider-ca-bundle",
        type=Path,
        help="Explicit approved public CA bundle for start-provider only",
    )
    args = parser.parse_args(argv)
    setup = setup.resolve()
    try:
        if args.provider_ca_bundle is not None and args.action != "start-provider":
            raise SetupError("--provider-ca-bundle is only supported for start-provider")
        if args.service is not None and args.action != "logs":
            raise SetupError("--service is only supported for the logs action")
        if args.action == "reset" and args.confirm != "RESET_LOCAL_STACK":
            raise SetupError(
                "Reset requires --confirm RESET_LOCAL_STACK; it removes this local project's data volumes"
            )
        if args.action == "init":
            initialize(setup)
            report = {
                "status": "initialized",
                "credentials": "preserved_or_created",
                "configurationSchema": CONFIG_SCHEMA_VERSION,
                "credentialSchema": CREDENTIAL_SCHEMA_VERSION,
                "productAcceptance": "not_certified",
            }
        else:
            values = load_settings(setup)
            base = compose_arguments(setup, args.observability)
            if args.action == "token":
                print(values["LOCAL_ACCESS_TOKEN"])
                return 0
            if args.action == "doctor":
                report = doctor(setup, args.observability)
            elif args.action == "config":
                render_config(setup)
                run(base + ["config", "--quiet"], values, setup)
                report = {"status": "configuration_valid", "project": PROJECT}
            elif args.action == "start":
                doctor(setup, args.observability)
                run(base + ["up", "--build", "--wait", "--wait-timeout", "120"], values, setup, 600)
                if args.observability:
                    wait_for_http(f"http://{values['BIND_ADDRESS']}:{values['JAEGER_UI_PORT']}/")
                report = {
                    "status": "started",
                    "project": PROJECT,
                    "observabilityReady": args.observability,
                    "productAcceptance": "not_certified",
                }
            elif args.action == "prepare-business":
                assert_owned_containers(setup, values)
                interpreter = setup.parent / ".venv/bin/python"
                helper = setup / "scripts/prepare_business.py"
                if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
                    raise SetupError(
                        "Prepare the frozen repository environment with make bootstrap"
                    )
                regular_file(helper)
                output = run([str(interpreter), str(helper)], values, setup, 120)
                report = {
                    "status": "business_prepared",
                    "schemaActivation": "explicit_empty_bootstrap_or_read_only_ready",
                    "fixtureInitialization": False,
                    "servingM1Unchanged": True,
                    "productAcceptance": "not_certified",
                    "output": output.strip(),
                }
            elif args.action == "prepare-postgres":
                assert_owned_containers(setup, values)
                output = run(
                    base + ["exec", "-T", "postgres", "sh", "/etc/continuity/prepare-postgres.sh"],
                    values,
                    setup,
                    45,
                    merge_output=True,
                )
                report = {
                    "status": "postgres_prepared",
                    "migrationRole": "continuity_migrator",
                    "runtimeRole": "livekit_lab",
                    "credentialRotation": False,
                    "productAcceptance": "not_certified",
                    "output": output.strip(),
                }
            elif args.action in {"init-providers", "check-providers"}:
                module = provider_configuration(setup)
                try:
                    created = (
                        module.create_template(setup / ".env.providers")
                        if args.action == "init-providers"
                        else False
                    )
                    credentials = module.read_credentials(setup / ".env.providers", complete=False)
                except ValueError:
                    raise SetupError(
                        "Private provider credential file requires owned mode0600 and the three declared fields"
                    ) from None
                presence = credentials.presence()
                report = {
                    "status": "provider_credentials_ready"
                    if all(presence.values())
                    else "provider_credentials_incomplete",
                    "created": created,
                    "present": presence,
                    "providerCalls": False,
                    "productAcceptance": "not_certified",
                }
                if args.action == "check-providers" and not all(presence.values()):
                    print(json.dumps(report))
                    return 2
            elif args.action in {"models-fetch", "models-verify"}:
                report = prepare_models(setup, values, fetch=args.action == "models-fetch")
            elif args.action in {"start-models", "stop-models"}:
                assert_owned_containers(setup, values)
                if args.action == "start-models":
                    prepare_models(setup, values)
                    output = start_models(base, setup, values)
                else:
                    output = stop_models(base, setup, values)
                report = {
                    "status": args.action.replace("-", "_"),
                    "schemaActivation": False,
                    "fixtureInitialization": False,
                    "runtimeDownloads": False,
                    "productAcceptance": "not_certified",
                    "output": output.strip(),
                }
            elif args.action in {
                "start-business",
                "stop-business",
                "start-local-real",
                "stop-local-real",
                "start-provider",
                "stop-provider",
            }:
                starting = args.action in {"start-business", "start-local-real", "start-provider"}
                local_real = args.action == "start-local-real"
                provider_real = args.action == "start-provider"
                credentials = provider_values(setup, complete=True) if provider_real else {}
                ca_snapshot = (
                    provider_ca_snapshot(setup, args.provider_ca_bundle)
                    if provider_real and args.provider_ca_bundle is not None
                    else None
                )
                assert_owned_containers(setup, values)
                mode = (
                    "provider_real" if provider_real else "local_real" if local_real else "scripted"
                )
                business_values = {
                    **values,
                    "P1_BUSINESS_ENABLED": "1" if starting else "0",
                    "P1_CONVERSATION_INFERENCE": mode,
                    "P1_TRACE_MODE": mode,
                    "P1_TRACE_ENDPOINT": "http://jaeger:4318/v1/traces",
                }
                business_base = base + [
                    "--profile",
                    "p1-business",
                    "--profile",
                    "p1-workers",
                    "--profile",
                    "observability",
                ]
                if starting:
                    if local_real:
                        # This host-only verification cannot download or mutate
                        # schema/fixtures. A cache miss precedes all model startup.
                        prepare_models(setup, business_values)
                    # Build the shared runtime before invoking its new preflight
                    # entry point. Image creation changes no application state.
                    run(business_base + ["build", "control-api"], business_values, setup, 600)
                    # Verify existing ACTIVE state and fixture authority before
                    # replacing the serving API. This never installs or seeds.
                    run(
                        business_base
                        + [
                            "run",
                            "--rm",
                            "--no-deps",
                            "control-api",
                            "python",
                            "/app/local-setup/scripts/business_preflight.py",
                        ],
                        business_values,
                        setup,
                        45,
                        merge_output=True,
                    )
                    if local_real:
                        start_models(base, setup, business_values)
                    serving_base = business_base
                    serving_values = business_values
                    if provider_real:
                        regular_file(setup / "docker-compose.providers.yaml")
                        serving_base = business_base + [
                            "-f",
                            str(setup / "docker-compose.providers.yaml"),
                        ]
                        serving_values = {**business_values, **credentials}
                        if ca_snapshot is not None:
                            regular_file(setup / "docker-compose.provider-ca.yaml")
                            serving_base += ["-f", str(setup / "docker-compose.provider-ca.yaml")]
                            serving_values = {
                                **serving_values,
                                "P1_PROVIDER_CA_SNAPSHOT": str(ca_snapshot),
                            }
                    output = run(
                        serving_base
                        + [
                            "up",
                            "-d",
                            "--no-deps",
                            *(["--force-recreate"] if ca_snapshot is not None else []),
                            "--wait",
                            "--wait-timeout",
                            "60",
                            "jaeger",
                            "p1-worker",
                            "conversation-agent",
                            "control-api",
                        ],
                        serving_values,
                        setup,
                        120,
                        merge_output=True,
                    )
                elif args.action == "stop-provider":
                    output = stop_provider(business_base, business_values, setup)
                else:
                    run(
                        business_base + ["stop", "-t", "35", "conversation-agent", "p1-worker"],
                        business_values,
                        setup,
                        90,
                        merge_output=True,
                    )
                    output = run(
                        business_base
                        + [
                            "up",
                            "-d",
                            "--no-deps",
                            "--wait",
                            "--wait-timeout",
                            "60",
                            "control-api",
                        ],
                        business_values,
                        setup,
                        90,
                        merge_output=True,
                    )
                    if args.action == "stop-local-real":
                        stop_models(base, setup, business_values)
                report = {
                    "status": args.action.replace("-", "_"),
                    "inferenceMode": mode,
                    "schemaActivation": False,
                    "fixtureInitialization": False,
                    "productAcceptance": "not_certified",
                    "output": output.strip(),
                }
            elif args.action in {
                "start-workers",
                "stop-workers",
                "init-worker-fixtures",
                "worker-status",
            }:
                assert_owned_containers(setup, values)
                worker_base = base + ["--profile", "p1-workers"]
                operations = {
                    "start-workers": [
                        "up",
                        "-d",
                        "--no-deps",
                        "--wait",
                        "--wait-timeout",
                        "30",
                        "p1-worker",
                    ],
                    "stop-workers": ["stop", "-t", "35", "p1-worker"],
                    "init-worker-fixtures": [
                        "run",
                        "--rm",
                        "--no-deps",
                        "p1-worker",
                        "python",
                        "-m",
                        "continuity_lab.worker_cli",
                        "init-fixtures",
                    ],
                    "worker-status": [
                        "ps",
                        "--format",
                        "{{.Service}}\t{{.State}}\t{{.Health}}",
                        "p1-worker",
                    ],
                }
                output = run(
                    worker_base + operations[args.action], values, setup, 60, merge_output=True
                )
                report = {
                    "status": args.action.replace("-", "_"),
                    "schemaActivation": False,
                    "productAcceptance": "not_certified",
                    "output": output.strip(),
                }
            elif args.action in {
                "migrate-postgres",
                "upgrade-postgres",
                "upgrade-effects",
                "upgrade-coordination",
            }:
                assert_owned_containers(setup, values)
                command = base + [
                    "--profile",
                    "migrations",
                    "run",
                    "--rm",
                    "--no-deps",
                    "p1-migrate",
                ]
                if args.action in {"upgrade-postgres", "upgrade-effects", "upgrade-coordination"}:
                    operation = "upgrade" if args.action == "upgrade-postgres" else args.action
                    command += ["python", "-m", "continuity_lab.postgres_cli", operation]
                output = run(
                    command,
                    values,
                    setup,
                    60,
                    merge_output=True,
                )
                report = {
                    "status": "postgres_schema_prepared",
                    "migrationRole": "continuity_migrator",
                    "sourceCutover": False,
                    "productAcceptance": "not_certified",
                    "output": output.strip(),
                }
            else:
                commands = {
                    "status": ["ps", "--format", "{{.Service}}\t{{.State}}\t{{.Health}}"],
                    "logs": ["logs", "--no-color", "--tail", "100"],
                    "smoke": [
                        "exec",
                        "-T",
                        "control-api",
                        "python",
                        "/app/local-setup/scripts/smoke.py",
                    ],
                    "stop": ["down", "--timeout", "35"],
                    "reset": ["down", "--timeout", "35", "--volumes"],
                }
                if args.action == "logs" and args.service is not None:
                    commands["logs"].append(args.service)
                if args.action in {"stop", "reset"}:
                    assert_owned_containers(setup, values)
                output = run(
                    (
                        base
                        + [
                            "--profile",
                            "p1-workers",
                            "--profile",
                            "p1-business",
                            "--profile",
                            "observability",
                            "--profile",
                            "p1-models",
                        ]
                        if args.action in {"stop", "reset"}
                        else base
                    )
                    + commands[args.action],
                    values,
                    setup,
                    180 if args.action == "smoke" else 60,
                    merge_output=args.action == "logs",
                )
                report = {
                    "status": args.action + "_completed",
                    "project": PROJECT,
                    "productAcceptance": "not_certified",
                }
                if args.action == "status":
                    services = []
                    for line in output.splitlines():
                        parts = line.split("\t")
                        if len(parts) != 3:
                            raise SetupError("Docker returned an invalid service status")
                        service, state, health = parts
                        services.append(
                            {"service": service, "state": state, "health": health or "unreported"}
                        )
                    report["services"] = services
                else:
                    report["output"] = output.strip()
        print(json.dumps(report, indent=2))
        return 0
    except (SetupError, OSError) as error:
        if args.action == "stop-provider":
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "code": "provider_stop_failed",
                        "cleanup_incomplete": error.cleanup_incomplete
                        if isinstance(error, ProviderStopError)
                        else True,
                    }
                )
            )
        elif args.action == "start-provider":
            print(json.dumps({"status": "failed", "code": "provider_start_failed"}))
        else:
            print(json.dumps({"status": "failed", "error": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
