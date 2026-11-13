"""Explicit pinned model setup; verification and runtime never download weights."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import multiprocessing
import os
import re
import shutil
import signal
import ssl
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

MANIFEST_DIGEST = "b57d52bed5e252bfe868aac75265e5318ce5de19f4a65e86b51125170b7b61e9"
PROFILE = "p1-local-real-v1"
MAX_MODEL_BYTES = 4 * 1024**3
MAX_SECONDS = 1800
CHUNK_BYTES = 1024 * 1024
INITIAL_HOSTS = frozenset({"registry.ollama.ai", "huggingface.co"})
REDIRECT_HOSTS = INITIAL_HOSTS | {
    "cdn-lfs.huggingface.co",
    "cdn-lfs-us-1.hf.co",
    "cas-bridge.xethub.hf.co",
    "transfer.xethub.hf.co",
    "us.aws.cdn.hf.co",
}


class ModelSetupError(ValueError):
    """Only fixed codes cross the tool boundary, never URL/body/exception data."""

    CODES = frozenset(
        {
            "local_model_setup_required",
            "model_cache_busy",
            "model_timeout",
            "model_cleanup_incomplete",
        }
    )

    def __init__(
        self, code: str = "local_model_setup_required", *, cleanup_incomplete: bool = False
    ) -> None:
        if type(code) is not str or code not in self.CODES or type(cleanup_incomplete) is not bool:
            raise ValueError("Unsupported model setup category")
        self.code = code
        self.cleanup_incomplete = cleanup_incomplete
        super().__init__("Pinned local model preparation did not complete")


def validate_url(value: str, *, redirect: bool = False) -> None:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 8192
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise ModelSetupError()
    try:
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname or ""
        hosts = REDIRECT_HOSTS if redirect else INITIAL_HOSTS
        r2 = (
            redirect and re.fullmatch(r"[a-f0-9]{32}\.r2\.cloudflarestorage\.com", host) is not None
        )
        if (
            not value.startswith("https://")
            or parsed.scheme != "https"
            or host not in hosts
            and not r2
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.fragment
            or not parsed.path.startswith("/")
            or not redirect
            and parsed.query
        ):
            raise ModelSetupError()
    except ValueError:
        raise ModelSetupError() from None


@dataclass(frozen=True, slots=True)
class ModelFile:
    relative: str
    url: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if type(self.relative) is not str or not 1 <= len(self.relative) <= 200:
            raise ModelSetupError()
        path = PurePosixPath(self.relative)
        if (
            path.is_absolute()
            or any(part in {".", "..", ""} for part in self.relative.split("/"))
            or str(path) != self.relative
            or "\\" in self.relative
            or ":" in self.relative
            or type(self.size) is not int
            or not 1 <= self.size <= 3 * 1024**3
            or type(self.sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None
        ):
            raise ModelSetupError()
        validate_url(self.url)


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ModelSetupError()
        result[key] = value
    return result


def _no_number(_value: str) -> NoReturn:
    raise ModelSetupError()


def _integer(value: str) -> int:
    if len(value) > 12:
        raise ModelSetupError()
    return int(value)


def files_from_manifest(path: Path) -> tuple[ModelFile, ...]:
    """The reviewed profile is immutable; unknown/changed declarations fail closed."""
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or not 1 <= info.st_size <= 65536
            ):
                raise ModelSetupError()
            raw = stream.read(65537)
        value: Any = json.loads(
            raw,
            object_pairs_hook=_object,
            parse_int=_integer,
            parse_float=_no_number,
            parse_constant=_no_number,
        )
        canonical = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
        if hashlib.sha256(canonical).hexdigest() != MANIFEST_DIGEST:
            raise ModelSetupError()
        llm, stt, tts = (value["models"][kind] for kind in ("llm", "stt", "tts"))
        files = [
            ModelFile(
                llm["cache_manifest"],
                llm["metadata_url"],
                llm["manifest_size_bytes"],
                llm["manifest_sha256"],
            )
        ]
        for layer in (llm["config"], *llm["layers"]):
            digest = layer["digest"]
            files.append(
                ModelFile(
                    "ollama/blobs/" + digest.replace(":", "-"),
                    "https://registry.ollama.ai/v2/library/qwen3/blobs/" + digest,
                    layer["size"],
                    digest[7:],
                )
            )
        files.append(ModelFile(stt["cache_file"], stt["url"], stt["size_bytes"], stt["sha256"]))
        files.extend(
            ModelFile("piper/" + item["file"], item["url"], item["size_bytes"], item["sha256"])
            for item in tts["files"]
        )
        if (
            len(files) != 10
            or len({item.relative for item in files}) != 10
            or sum(item.size for item in files) > MAX_MODEL_BYTES
        ):
            raise ModelSetupError()
        return tuple(files)
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
        raise ModelSetupError() from None


def owned_directory(path: Path, *, private: bool = False) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise ModelSetupError()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            current.mkdir(mode=0o755)
            os.chmod(current, 0o755)
        except FileExistsError:
            pass
        if not stat.S_ISDIR(current.lstat().st_mode):
            raise ModelSetupError()
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & (0o077 if private else 0o022):
        raise ModelSetupError()


@contextmanager
def cache_lock(cache: Path) -> Iterator[None]:
    """Retain the shared inode forever; a failed contender closes only its own FD."""
    owned_directory(cache)
    os.chmod(cache, 0o755)
    path = cache / ".prepare.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise ModelSetupError()
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ModelSetupError("model_cache_busy") from None
        yield
    finally:
        os.close(descriptor)


def prepare_runtime_layout(cache: Path) -> None:
    """Keep the pinned legacy manifest readable by Ollama's read-only v2 lookup.

    Call only under the preparation lock after verifying every declared file.
    An existing v2 manifest could shadow those verified bytes, so accept only an
    owned empty directory. No manifest migration or runtime write is authorized.
    """
    owned_directory(cache / "ollama")
    target = cache / "ollama/manifests-v2"
    owned_directory(target)
    if next(target.iterdir(), None) is not None:
        raise ModelSetupError()
    os.chmod(target, 0o755)


@contextmanager
def scratch_directory(cache: Path) -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix=".prepare-", dir=cache)).resolve()
    identity = path.lstat()
    original: BaseException | None = None
    try:
        yield path
    except BaseException as error:
        original = error
        raise
    finally:
        current: os.stat_result | None
        try:
            try:
                current = path.lstat()
            except FileNotFoundError:
                current = None
            if current is not None:
                if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
                    identity.st_dev,
                    identity.st_ino,
                ):
                    raise ModelSetupError("model_cleanup_incomplete")
                shutil.rmtree(path)
        except (OSError, ModelSetupError):
            if isinstance(original, ModelSetupError):
                original.cleanup_incomplete = True
            elif original is not None:
                original.add_note("Owned model preparation cleanup is incomplete.")
            else:
                raise ModelSetupError("model_cleanup_incomplete", cleanup_incomplete=True) from None


def verified(path: Path, file: ModelFile) -> bool:
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or info.st_mode & 0o022
                or info.st_mode & 0o444 != 0o444
                or info.st_size != file.size
            ):
                raise ModelSetupError()
            digest, count = hashlib.sha256(), 0
            while chunk := stream.read(CHUNK_BYTES):
                count += len(chunk)
                if count > file.size:
                    raise ModelSetupError()
                digest.update(chunk)
            return count == file.size and digest.hexdigest() == file.sha256
    except FileNotFoundError:
        return False
    except OSError:
        raise ModelSetupError() from None


class Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 4
    max_repeats = 1

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> urllib.request.Request | None:
        validate_url(newurl, redirect=True)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(
    file: ModelFile, cache: Path, scratch: Path, open_url: Callable[..., Any], deadline: float
) -> None:
    target = cache / file.relative
    owned_directory(target.parent)
    owned_directory(scratch, private=True)
    if target.exists() or target.is_symlink():
        if verified(target, file):
            return
        raise ModelSetupError()
    temporary = scratch / (hashlib.sha256(file.relative.encode()).hexdigest() + ".partial")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    count, digest, last = 0, hashlib.sha256(), time.monotonic()
    try:
        with os.fdopen(descriptor, "wb") as output:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ModelSetupError("model_timeout")
            request = urllib.request.Request(
                file.url,
                headers={
                    "Accept-Encoding": "identity",
                    "User-Agent": "continuity-local-model-setup/1",
                },
            )
            with open_url(request, timeout=min(30, remaining)) as response:
                if response.status != 200 or response.headers.get(
                    "Content-Encoding", "identity"
                ) not in {"", "identity"}:
                    raise ModelSetupError()
                length = response.headers.get("Content-Length")
                if length is not None and length != str(file.size):
                    raise ModelSetupError()
                while chunk := response.read(CHUNK_BYTES):
                    if type(chunk) is not bytes or len(chunk) > CHUNK_BYTES:
                        raise ModelSetupError()
                    count += len(chunk)
                    if count > file.size or time.monotonic() >= deadline:
                        raise ModelSetupError(
                            "model_timeout"
                            if time.monotonic() >= deadline
                            else "local_model_setup_required"
                        )
                    output.write(chunk)
                    digest.update(chunk)
                    if time.monotonic() - last >= 30:
                        print(
                            json.dumps(
                                {
                                    "event": "model_download_progress",
                                    "family": file.relative.split("/")[0],
                                    "bytes": count,
                                    "expected_bytes": file.size,
                                }
                            ),
                            flush=True,
                        )
                        last = time.monotonic()
            if (
                count != file.size
                or digest.hexdigest() != file.sha256
                or time.monotonic() >= deadline
            ):
                raise ModelSetupError()
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), 0o644)
        os.link(temporary, target, follow_symlinks=False)
        temporary.unlink()
        directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _alarm(_number: int, _frame: object) -> NoReturn:
    raise ModelSetupError("model_timeout")


def _worker(
    files: tuple[ModelFile, ...],
    cache: str,
    scratch: str,
    fetch_requested: bool,
    maximum_seconds: float,
) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, maximum_seconds)
    owned_scratch = Path(scratch)
    identity = None
    primary, cleanup_failed = 0, False
    try:
        identity = owned_scratch.lstat()
        path = Path(cache)
        if fetch_requested:
            missing = sum(item.size for item in files if not (path / item.relative).exists())
            if shutil.disk_usage(path).free < missing + 512 * 1024**2:
                raise ModelSetupError()
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}),
                Redirects(),
                urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            )
            deadline = time.monotonic() + maximum_seconds
            for item in files:
                fetch(item, path, owned_scratch, opener.open, deadline)
        if not all(verified(path / item.relative, item) for item in files):
            raise ModelSetupError()
    except ModelSetupError as error:
        primary = 124 if error.code == "model_timeout" else 1
    except BaseException:  # noqa: BLE001 - child never prints dependency diagnostics
        primary = 1
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        current: os.stat_result | None
        try:
            try:
                current = owned_scratch.lstat()
            except FileNotFoundError:
                current = None
            if current is not None:
                if (
                    identity is None
                    or not stat.S_ISDIR(current.st_mode)
                    or (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino)
                ):
                    raise ModelSetupError("model_cleanup_incomplete")
                shutil.rmtree(owned_scratch)
        except (OSError, ModelSetupError):
            cleanup_failed = True
    # Fixed combined exits preserve primary failure separately from cleanup.
    if cleanup_failed:
        raise SystemExit(126 if primary == 124 else 127 if primary else 125)
    if primary:
        raise SystemExit(primary)


def run_worker(
    files: tuple[ModelFile, ...],
    cache: Path,
    scratch: Path,
    fetch_requested: bool,
    *,
    maximum_seconds: float = MAX_SECONDS,
) -> None:
    if (
        type(maximum_seconds) not in {int, float}
        or not 0 < maximum_seconds <= MAX_SECONDS
        or not math.isfinite(maximum_seconds)
        or threading.active_count() != 1
    ):
        raise ModelSetupError()
    # This standalone POSIX tool forks before network/threads. The child retains
    # the parent's open flock description until exit, including parent loss.
    process = multiprocessing.get_context("fork").Process(
        target=_worker,
        args=(files, str(cache), str(scratch), fetch_requested, maximum_seconds),
        daemon=False,
    )
    process.start()
    original: BaseException | None = None
    try:
        process.join(timeout=maximum_seconds)
        if process.is_alive():
            raise ModelSetupError("model_timeout")
        if process.exitcode == 124:
            raise ModelSetupError("model_timeout")
        if process.exitcode in {125, 126, 127}:
            primary_code = (
                "model_timeout"
                if process.exitcode == 126
                else "local_model_setup_required"
                if process.exitcode == 127
                else "model_cleanup_incomplete"
            )
            raise ModelSetupError(primary_code, cleanup_incomplete=True)
        if process.exitcode != 0:
            raise ModelSetupError()
    except BaseException as error:
        original = error
        raise
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        if process.is_alive():
            if isinstance(original, ModelSetupError):
                original.cleanup_incomplete = True
            elif original is not None:
                original.add_note("Owned model worker cleanup is incomplete.")
            else:
                raise ModelSetupError("model_cleanup_incomplete", cleanup_incomplete=True)
        else:
            process.close()


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, '{"status":"failed","code":"local_model_setup_required"}\n')


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = SafeParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument(
        "--manifest", type=Path, default=root / "local-setup/models/local-model-manifest.json"
    )
    args = parser.parse_args(argv)
    cache = root / "local-setup/.local/models"
    try:
        files = files_from_manifest(args.manifest)
        with cache_lock(cache):
            for item in files:
                current = cache
                for part in PurePosixPath(item.relative).parts[:-1]:
                    current /= part
                    owned_directory(current)
                    os.chmod(current, 0o755)
            with scratch_directory(cache) as directory:
                run_worker(files, cache, directory, args.fetch)
            prepare_runtime_layout(cache)
        print(
            json.dumps(
                {
                    "status": "verified",
                    "profile": PROFILE,
                    "files": len(files),
                    "model_bytes": sum(item.size for item in files),
                    "runtime_downloads": False,
                }
            )
        )
        return 0
    except KeyboardInterrupt:
        print('{"status":"cancelled","code":"local_model_setup_required"}')
        return 130
    except (OSError, ValueError, urllib.error.URLError) as error:
        code = error.code if isinstance(error, ModelSetupError) else "local_model_setup_required"
        payload: dict[str, str | bool] = {"status": "failed", "code": code}
        if isinstance(error, ModelSetupError) and error.cleanup_incomplete:
            payload["cleanup_incomplete"] = True
        print(json.dumps(payload))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
