"""One-request-at-a-time local speech engine; no remote calls or content logs."""

from __future__ import annotations

import argparse
import http.client
import io
import json
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import wave
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, BinaryIO, Literal, NoReturn

Mode = Literal["stt", "tts"]
MAX_INPUT_WAV = 16000 * 2 * 12 + 4096
MAX_OUTPUT_WAV = 22050 * 2 * 20 + 4096
MAX_TEXT_BYTES = 1024
MAX_TRANSCRIPT_BYTES = 4096
MAX_CHILD_BYTES = 65536
CHILD_SECONDS = 8.0
REQUEST_SECONDS = 9.0
MODEL_STT = Path("/models/whisper/ggml-base.en.bin")
MODEL_TTS = Path("/models/piper/en_US-ljspeech-medium.onnx")
CONFIG_TTS = Path("/models/piper/en_US-ljspeech-medium.onnx.json")
WHISPER = Path("/opt/whisper/bin/whisper-cli")


class EngineError(RuntimeError):
    CODES = frozenset(
        {
            "invalid_input",
            "input_limit",
            "dependency_unavailable",
            "deadline_exceeded",
            "response_invalid",
            "response_limit",
            "cleanup_incomplete",
        }
    )

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in self.CODES:
            raise ValueError("Unsupported local engine category")
        self.code = code
        self.cleanup_incomplete = False
        super().__init__("The bounded local speech operation did not complete")


def json_object(raw: bytes, maximum: int) -> dict[str, Any]:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise EngineError("input_limit")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise EngineError("invalid_input")
            result[key] = value
        return result

    def constant(_value: str) -> NoReturn:
        raise EngineError("invalid_input")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        if type(value) is not dict:
            raise EngineError("invalid_input")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise EngineError("invalid_input") from None


def pcm_wav(raw: bytes, *, rate: int, seconds: int, maximum: int) -> bytes:
    try:
        if (
            not 44 <= len(raw) <= maximum
            or raw[:4] != b"RIFF"
            or int.from_bytes(raw[4:8], "little") + 8 != len(raw)
        ):
            raise EngineError("response_invalid")
        with wave.open(io.BytesIO(raw), "rb") as stream:
            count = stream.getnframes()
            if (
                stream.getnchannels() != 1
                or stream.getsampwidth() != 2
                or stream.getframerate() != rate
                or stream.getcomptype() != "NONE"
                or not 0 < count <= rate * seconds
            ):
                raise EngineError("response_invalid")
            pcm = stream.readframes(count)
        if len(pcm) != count * 2 or not any(pcm):
            raise EngineError("response_invalid")
        return pcm
    except (wave.Error, EOFError, ValueError, OverflowError):
        raise EngineError("response_invalid") from None


def stt_input(content_type: str, body: bytes) -> bytes:
    if (
        not re.fullmatch(r"multipart/form-data; boundary=[A-Za-z0-9_.-]{1,70}", content_type)
        or not 0 < len(body) <= MAX_INPUT_WAV + 8192
    ):
        raise EngineError("invalid_input")
    try:
        message = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: "
            + content_type.encode("ascii")
            + b"\r\nMIME-Version: 1.0\r\n\r\n"
            + body
        )
        if message.defects or not message.is_multipart():
            raise EngineError("invalid_input")
        parts = list(message.iter_parts())
        if not 1 <= len(parts) <= 5:
            raise EngineError("invalid_input")
        fields: dict[str, bytes] = {}
        for part in parts:
            name = part.get_param("name", header="content-disposition")
            if part.defects or part.is_multipart() or type(name) is not str or name in fields:
                raise EngineError("invalid_input")
            value = part.get_payload(decode=True)
            if type(value) is not bytes:
                raise EngineError("invalid_input")
            if name == "file" and (
                part.get_filename() != "turn.wav" or part.get_content_type() != "audio/wav"
            ):
                raise EngineError("invalid_input")
            fields[name] = value
        fixed = {
            "temperature": b"0.0",
            "temperature_inc": b"0.0",
            "response_format": b"json",
            "language": b"en",
        }
        if set(fields) not in ({"file"}, {"file", *fixed}) or any(
            fields[key] != value for key, value in fixed.items() if key in fields
        ):
            raise EngineError("invalid_input")
        pcm = pcm_wav(fields["file"], rate=16000, seconds=12, maximum=MAX_INPUT_WAV)
        target = io.BytesIO()
        with wave.open(target, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(pcm)
        return target.getvalue()
    except (KeyError, ValueError, UnicodeError, TypeError):
        raise EngineError("invalid_input") from None


def tts_input(body: bytes) -> str:
    value = json_object(body, MAX_TEXT_BYTES * 6 + 64)
    text = value.get("text")
    try:
        if (
            set(value) != {"text"}
            or type(text) is not str
            or not text.strip()
            or len(text.encode("utf-8")) > MAX_TEXT_BYTES
            or any(ord(char) < 32 and char not in "\n\t\r" for char in text)
        ):
            raise EngineError("invalid_input")
        return text
    except UnicodeError:
        raise EngineError("invalid_input") from None


def transcript(raw: bytes) -> bytes:
    value = json_object(raw, MAX_CHILD_BYTES)
    segments = value.get("transcription")
    if type(segments) is not list or len(segments) > 128:
        raise EngineError("response_invalid")
    text = ""
    for segment in segments:
        if type(segment) is not dict or type(segment.get("text")) is not str:
            raise EngineError("response_invalid")
        text += segment["text"]
        try:
            if len(text.encode("utf-8")) > MAX_TRANSCRIPT_BYTES:
                raise EngineError("response_limit")
        except UnicodeError:
            raise EngineError("response_invalid") from None
    result = json.dumps({"text": text.strip()}, ensure_ascii=False, allow_nan=False).encode()
    if len(result) > 16384:
        raise EngineError("response_limit")
    return result


def bounded_file(path: Path, maximum: int) -> bytes:
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or not 0 < info.st_size <= maximum
            ):
                raise EngineError("response_limit")
            raw = stream.read(maximum + 1)
            if len(raw) != info.st_size:
                raise EngineError("response_invalid")
            return raw
    except OSError:
        raise EngineError("dependency_unavailable") from None


def child_environment() -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "HOME": "/tmp",
        "XDG_CACHE_HOME": "/tmp",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "1",
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }


def _stop(process: subprocess.Popen[bytes]) -> None:
    for number in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, number)
        except ProcessLookupError:
            pass
        except OSError:
            raise EngineError("cleanup_incomplete") from None
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            continue
    if process.poll() is None:
        raise EngineError("cleanup_incomplete")


def run_child(
    argv: Sequence[str],
    directory: Path,
    output: Path,
    maximum: int,
    *,
    seconds: float = CHILD_SECONDS,
) -> bytes:
    if (
        type(seconds) not in {int, float}
        or not 0 < seconds <= CHILD_SECONDS
        or not math.isfinite(seconds)
        or type(maximum) is not int
        or not 0 < maximum <= MAX_OUTPUT_WAV
    ):
        raise EngineError("invalid_input")
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=directory,
            env=child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            close_fds=True,
        )
    except OSError:
        raise EngineError("dependency_unavailable") from None
    selector = selectors.DefaultSelector()
    count = 0
    deadline = time.monotonic() + seconds
    streams: dict[int, BinaryIO] = {}
    original: BaseException | None = None
    try:
        for name, source in (("stdout", process.stdout), ("stderr", process.stderr)):
            assert source is not None
            os.set_blocking(source.fileno(), False)
            destination = os.fdopen(
                os.open(
                    directory / (name + ".bin"),
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                ),
                "wb",
            )
            streams[source.fileno()] = destination
            selector.register(source, selectors.EVENT_READ)
        while selector.get_map() or process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineError("deadline_exceeded")
            if output.exists() and output.lstat().st_size > maximum:
                raise EngineError("response_limit")
            for key, _events in selector.select(min(0.02, remaining)):
                part = os.read(key.fd, min(16384, MAX_CHILD_BYTES - count + 1))
                if not part:
                    selector.unregister(key.fileobj)
                    continue
                count += len(part)
                if count > MAX_CHILD_BYTES:
                    raise EngineError("response_limit")
                streams[key.fd].write(part)
        if process.returncode != 0:
            raise EngineError("dependency_unavailable")
        return bounded_file(output, maximum)
    except BaseException as error:
        original = error
        raise
    finally:
        try:
            try:
                _stop(process)
            except EngineError:
                if isinstance(original, EngineError):
                    original.cleanup_incomplete = True
                elif original is not None:
                    original.add_note("Owned local speech child cleanup is incomplete.")
                else:
                    raise
        finally:
            selector.close()
            for stream in streams.values():
                stream.close()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()


@contextmanager
def request_directory() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="local-speech-")).resolve()
    identity = directory.lstat()
    original: BaseException | None = None
    try:
        yield directory
    except BaseException as error:
        original = error
        raise
    finally:
        try:
            current = directory.lstat()
            if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
                identity.st_dev,
                identity.st_ino,
            ):
                raise EngineError("cleanup_incomplete")
            import shutil

            shutil.rmtree(directory)
        except FileNotFoundError:
            pass
        except (OSError, EngineError):
            if isinstance(original, EngineError):
                original.cleanup_incomplete = True
            elif original is not None:
                original.add_note("Private local speech request cleanup is incomplete.")
            else:
                raise EngineError("cleanup_incomplete") from None


def infer(
    mode: Mode,
    body: bytes,
    content_type: str,
    *,
    child: Path = Path("/opt/inference/engine_child.py"),
) -> tuple[bytes, str]:
    parsed: bytes | str = stt_input(content_type, body) if mode == "stt" else tts_input(body)
    with request_directory() as directory:
        if mode == "stt":
            (directory / "turn.wav").write_bytes(parsed if isinstance(parsed, bytes) else b"")
            output = directory / "result.json"
            maximum = MAX_CHILD_BYTES
        else:
            (directory / "request.json").write_text(
                json.dumps({"text": parsed}, ensure_ascii=False)
            )
            output = directory / "result.wav"
            maximum = MAX_OUTPUT_WAV
        raw = run_child(
            (sys.executable, "-I", str(child), mode, str(directory)), directory, output, maximum
        )
        if mode == "stt":
            return transcript(raw), "application/json"
        pcm_wav(raw, rate=22050, seconds=20, maximum=MAX_OUTPUT_WAV)
        return raw, "audio/wav"


class HeaderReader:
    def __init__(self, stream: Any) -> None:
        self.stream, self.count = stream, 0

    def readline(self, size: int = -1) -> bytes:
        raw: bytes = self.stream.readline(8193 if size < 0 else min(8193, max(1, size)))
        self.count += len(raw)
        if self.count > 8192:
            raise http.client.LineTooLong("headers")
        return raw


def alarm(_number: int, _frame: object) -> NoReturn:
    raise EngineError("deadline_exceeded")


class EngineMetrics:
    mode: Mode
    requests: int
    succeeded: int
    failed: int
    active: int
    max_active: int
    processed_input_bytes: int
    processed_output_bytes: int
    duration_seconds: float

    def __init__(self, mode: Mode) -> None:
        if type(mode) is not str or mode not in {"stt", "tts"}:
            raise EngineError("invalid_input")
        self.mode = mode
        self.requests = self.succeeded = self.failed = self.active = self.max_active = 0
        self.processed_input_bytes = self.processed_output_bytes = 0
        self.duration_seconds = 0.0

    def begin(self, body_bytes: int) -> None:
        if self.requests >= 1000000 or self.active != 0:
            raise EngineError("dependency_unavailable")
        self.requests += 1
        self.active = 1
        self.max_active = max(self.max_active, 1)
        self.processed_input_bytes += body_bytes

    def finish(self, success: bool, output_bytes: int, duration: float) -> None:
        self.active = 0
        if success:
            self.succeeded += 1
        else:
            self.failed += 1
        self.processed_output_bytes += output_bytes
        self.duration_seconds += duration

    def snapshot(self) -> dict[str, str | int | float]:
        return {
            "schema_version": 1,
            "engine": self.mode,
            "requests": self.requests,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "active": self.active,
            "max_active": self.max_active,
            "processed_input_bytes": self.processed_input_bytes,
            "processed_output_bytes": self.processed_output_bytes,
            "duration_seconds": self.duration_seconds,
        }


class SpeechServer(HTTPServer):
    request_queue_size = 1
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], mode: Mode) -> None:
        self.mode = mode
        self.metrics = EngineMetrics(mode)
        super().__init__(address, Handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        print(
            '{"event":"engine_request_failed","code":"dependency_unavailable"}',
            file=sys.stderr,
            flush=True,
        )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: SpeechServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(1)

    def parse_request(self) -> bool:
        source = self.rfile
        self.rfile = HeaderReader(source)  # type: ignore[assignment]
        try:
            return super().parse_request()
        finally:
            self.rfile = source

    def handle_one_request(self) -> None:
        self._responded = False
        self._input_bytes = 0
        self._code = "ok"
        started = time.monotonic()
        previous = signal.signal(signal.SIGALRM, alarm)
        signal.setitimer(signal.ITIMER_REAL, REQUEST_SECONDS)
        try:
            super().handle_one_request()
        except EngineError as error:
            self._code = error.code
            self.reply(
                503
                if error.code
                in {"deadline_exceeded", "dependency_unavailable", "cleanup_incomplete"}
                else 400,
                json.dumps(
                    {
                        "code": error.code,
                        **({"cleanup_incomplete": True} if error.cleanup_incomplete else {}),
                    }
                ).encode(),
                "application/json",
            )
        except OSError:
            self._code = "dependency_unavailable"
            if not self._responded:
                self.reply(503, b'{"code":"dependency_unavailable"}', "application/json")
        except ValueError:
            self._code = "invalid_input"
            if not self._responded:
                self.reply(400, b'{"code":"invalid_input"}', "application/json")
        except Exception:  # noqa: BLE001 - HTTP entrypoint never renders dependency diagnostics
            self._code = "dependency_unavailable"
            if not self._responded:
                self.reply(503, b'{"code":"dependency_unavailable"}', "application/json")
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
            self.close_connection = True
            print(
                json.dumps(
                    {
                        "service": "local-speech",
                        "role": self.server.mode,
                        "event": "request_finished",
                        "code": self._code,
                        "duration_seconds": time.monotonic() - started,
                        "input_bytes": self._input_bytes,
                    }
                ),
                file=sys.stderr,
                flush=True,
            )

    def log_message(self, format: str, *args: object) -> None:
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self.reply(code, b'{"code":"invalid_input"}', "application/json")

    def reply(self, status: int, body: bytes, content_type: str) -> None:
        if self._responded:
            return
        self._responded = True
        if status >= 400 and self._code == "ok":
            self._code = "dependency_unavailable" if status == 503 else "invalid_input"
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass

    def do_GET(self) -> None:
        if self.path == "/metrics":
            self.reply(
                200,
                json.dumps(self.server.metrics.snapshot(), allow_nan=False).encode(),
                "application/json",
            )
            return
        if self.path != "/health":
            self.reply(404, b'{"code":"invalid_input"}', "application/json")
            return
        paths = (MODEL_STT, WHISPER) if self.server.mode == "stt" else (MODEL_TTS, CONFIG_TTS)
        ready = all(path.is_file() for path in paths)
        self.reply(
            200 if ready else 503,
            b'{"status":"ready"}' if ready else b'{"status":"not_ready"}',
            "application/json",
        )

    def do_POST(self) -> None:
        expected = "/inference" if self.server.mode == "stt" else "/synthesize"
        lengths = self.headers.get_all("Content-Length", [])
        if (
            self.path != expected
            or self.headers.get("Transfer-Encoding") is not None
            or len(lengths) != 1
            or not re.fullmatch("[0-9]{1,7}", lengths[0])
        ):
            raise EngineError("invalid_input")
        length = int(lengths[0])
        maximum = MAX_INPUT_WAV + 8192 if self.server.mode == "stt" else MAX_TEXT_BYTES * 6 + 64
        if not 0 < length <= maximum:
            raise EngineError("input_limit")
        body = self.rfile.read(length)
        self._input_bytes = len(body)
        if len(body) != length:
            raise EngineError("invalid_input")
        content_types = self.headers.get_all("Content-Type", [])
        if len(content_types) != 1:
            raise EngineError("invalid_input")
        content_type = content_types[0]
        if self.server.mode == "tts" and content_type != "application/json":
            raise EngineError("invalid_input")
        self.server.metrics.begin(len(body))
        started = time.monotonic()
        success = False
        output_bytes = 0
        try:
            result, kind = infer(self.server.mode, body, content_type)
            success = True
            output_bytes = len(result)
        finally:
            self.server.metrics.finish(success, output_bytes, time.monotonic() - started)
        self.reply(200, result, kind)


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, '{"event":"engine_start_failed","code":"invalid_input"}\n')


def main() -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("mode", choices=("stt", "tts"))
    args = parser.parse_args()

    def stop(_number: int, _frame: object) -> NoReturn:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    with SpeechServer(("0.0.0.0", 8080 if args.mode == "stt" else 5000), args.mode) as server:
        server.serve_forever(poll_interval=0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
