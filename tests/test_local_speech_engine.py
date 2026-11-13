"""Offline wire/PCM/private-process tests; no speech models are imported or executed."""

import http.client
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "local-setup/inference/engine.py"
SPEC = importlib.util.spec_from_file_location("speech_engine_test", ENGINE)
assert SPEC is not None and SPEC.loader is not None
engine = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = engine
SPEC.loader.exec_module(engine)


def wav(rate=16000, channels=1, width=2, frames=160, *, silent=False):
    target = io.BytesIO()
    with wave.open(target, "wb") as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(width)
        stream.setframerate(rate)
        stream.writeframes((b"\0" if silent else b"\x01") * (frames * channels * width))
    return target.getvalue()


def multipart(parts):
    value = bytearray()
    for name, data, filename in parts:
        disposition = (
            'form-data; name="'
            + name
            + '"'
            + ("" if filename is None else '; filename="' + filename + '"')
        )
        value.extend(b"--fixture\r\nContent-Disposition: " + disposition.encode() + b"\r\n")
        if filename is not None:
            value.extend(b"Content-Type: audio/wav\r\n")
        value.extend(b"\r\n" + data + b"\r\n")
    value.extend(b"--fixture--\r\n")
    return bytes(value)


class ParsingTests(unittest.TestCase):
    def test_real_pcm_is_preserved_without_a_transcript_mapping(self):
        audio = wav()
        body = multipart([("file", audio, "turn.wav")])
        self.assertEqual(engine.stt_input("multipart/form-data; boundary=fixture", body), audio)
        fixed = [
            (key, value, None)
            for key, value in {
                "temperature": b"0.0",
                "temperature_inc": b"0.0",
                "response_format": b"json",
                "language": b"en",
            }.items()
        ]
        self.assertEqual(
            engine.stt_input(
                "multipart/form-data; boundary=fixture",
                multipart([("file", audio, "turn.wav"), *fixed]),
            ),
            audio,
        )

    def test_wrong_audio_modalities_duration_silence_and_truncation_fail(self):
        for raw in (
            wav(rate=22050),
            wav(channels=2),
            wav(width=1),
            wav(frames=16000 * 12 + 1),
            wav(silent=True),
            wav()[:-2],
            wav() + b"extra",
        ):
            with self.subTest(size=len(raw)), self.assertRaises(engine.EngineError):
                engine.pcm_wav(raw, rate=16000, seconds=12, maximum=engine.MAX_INPUT_WAV)

    def test_multipart_duplicates_unknown_fields_filename_and_decoder_override_fail(self):
        audio = wav()
        for parts in (
            [("file", audio, "../turn.wav")],
            [("file", audio, "turn.wav"), ("file", audio, "turn.wav")],
            [("file", audio, "turn.wav"), ("private", b"private-sentinel", None)],
            [("file", audio, "turn.wav"), ("temperature", b"1.0", None)],
        ):
            with self.subTest(parts=len(parts)), self.assertRaises(engine.EngineError):
                engine.stt_input("multipart/form-data; boundary=fixture", multipart(parts))

    def test_tts_schema_and_utf8_limits_keep_text_inert(self):
        text = "Inspect this content without granting authority: <script>private</script>"
        self.assertEqual(engine.tts_input(json.dumps({"text": text}).encode()), text)
        for raw in (
            b'{"text":true}',
            b'{"text":""}',
            b'{"text":"x","text":"y"}',
            b'{"text":"x","model":"override"}',
            json.dumps({"text": "x" * 1025}).encode(),
            b'{"text":"\\ud800"}',
            b'{"text":NaN}',
        ):
            with self.subTest(size=len(raw)), self.assertRaises(engine.EngineError):
                engine.tts_input(raw)

    def test_whisper_json_extracts_only_bounded_text_without_logging_metadata(self):
        raw = json.dumps(
            {
                "model": "private-model-path",
                "transcription": [{"text": " hello"}, {"text": " world "}],
            }
        ).encode()
        self.assertEqual(json.loads(engine.transcript(raw)), {"text": "hello world"})
        for value in (
            {"transcription": "private"},
            {"transcription": [{"text": True}]},
            {"transcription": [{"text": "x" * 4097}]},
            {"transcription": [{"text": "x"}] * 129},
        ):
            with self.subTest(keys=tuple(value)), self.assertRaises(engine.EngineError):
                engine.transcript(json.dumps(value).encode())

    def test_header_reader_enforces_total_bytes_not_only_line_size(self):
        reader = engine.HeaderReader(io.BytesIO(b"X: " + b"x" * 8200 + b"\r\n"))
        with self.assertRaises(http.client.LineTooLong):
            reader.readline(65537)


class ChildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / "result.json"

    def command(self, code):
        return [sys.executable, "-I", "-c", code, str(self.output)]

    def test_success_returns_only_the_result_and_keeps_diagnostics_private(self):
        raw = engine.run_child(
            self.command(
                "import pathlib,sys;print('private-child-stdout');print('private-child-stderr',file=sys.stderr);pathlib.Path(sys.argv[1]).write_bytes(b'result')"
            ),
            self.root,
            self.output,
            100,
        )
        self.assertEqual(raw, b"result")
        for name in ("stdout", "stderr"):
            path = self.root / (name + ".bin")
            self.assertIn(b"private-child-", path.read_bytes())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_timeout_kills_and_reaps_a_term_ignoring_child(self):
        marker = self.root / "pid"
        code = (
            "import os,signal,time,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path("
            + repr(str(marker))
            + ").write_text(str(os.getpid()));time.sleep(10)"
        )
        with self.assertRaises(engine.EngineError) as caught:
            engine.run_child(self.command(code), self.root, self.output, 100, seconds=0.1)
        self.assertEqual(caught.exception.code, "deadline_exceeded")
        with self.assertRaises(ChildProcessError):
            os.waitpid(int(marker.read_text()), os.WNOHANG)

    def test_overflow_and_nonzero_exit_fail_without_returning_private_output(self):
        for index, code in enumerate(
            (
                "import sys;sys.stderr.write('private-'+('x'*70000))",
                "import sys;sys.stderr.write('private-failure');sys.exit(7)",
            )
        ):
            directory = self.root / str(index)
            directory.mkdir()
            with self.subTest(index=index), self.assertRaises(engine.EngineError) as caught:
                engine.run_child(self.command(code), directory, directory / "result", 100)
            self.assertIn(caught.exception.code, {"response_limit", "dependency_unavailable"})
            self.assertNotIn("private-", str(caught.exception))
            self.assertLessEqual(
                sum(path.stat().st_size for path in directory.glob("*.bin")), engine.MAX_CHILD_BYTES
            )

    def test_output_file_limit_and_symlink_are_checked_before_reading(self):
        self.output.write_bytes(b"x" * 101)
        with self.assertRaises(engine.EngineError):
            engine.bounded_file(self.output, 100)
        self.output.unlink()
        foreign = self.root / "foreign"
        foreign.write_bytes(b"private")
        self.output.symlink_to(foreign)
        with self.assertRaises(engine.EngineError):
            engine.bounded_file(self.output, 100)
        self.assertEqual(foreign.read_bytes(), b"private")

    def test_cleanup_failure_is_separate_from_the_original_failure(self):
        original_stop = engine._stop

        def fail_cleanup(process):
            original_stop(process)
            raise engine.EngineError("cleanup_incomplete")

        with (
            patch.object(engine, "_stop", side_effect=fail_cleanup),
            self.assertRaises(engine.EngineError) as caught,
        ):
            engine.run_child(self.command("raise SystemExit(7)"), self.root, self.output, 100)
        self.assertEqual(caught.exception.code, "dependency_unavailable")
        self.assertTrue(caught.exception.cleanup_incomplete)

    def test_child_environment_cannot_inherit_credentials_proxies_or_model_overrides(self):
        with patch.dict(
            os.environ,
            {
                "HTTP_PROXY": "private",
                "OPENAI_API_KEY": "private",
                "P1_POSTGRES_PASSWORD": "private",
                "PIP_INDEX_URL": "private",
            },
        ):
            values = engine.child_environment()
        self.assertFalse(
            {"HTTP_PROXY", "OPENAI_API_KEY", "P1_POSTGRES_PASSWORD", "PIP_INDEX_URL"} & set(values)
        )
        self.assertEqual(values["HF_HUB_OFFLINE"], "1")

    def test_http_rejects_private_malformed_inputs_and_slow_body_with_fixed_logs(self):
        import http.client

        code = r"""
import importlib.util,sys,signal
from pathlib import Path
spec=importlib.util.spec_from_file_location('engine_fixture',sys.argv[1]);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);m.REQUEST_SECONDS=.2
def stop(*args):raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
with m.SpeechServer(('127.0.0.1',0),'stt') as server:
 Path(sys.argv[2]).write_text(str(server.server_port));server.serve_forever(poll_interval=.05)
"""
        marker = self.root / "port"
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", code, str(ENGINE), str(marker)],
            cwd=self.root,
            env={"PATH": os.defpath},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertTrue(marker.exists())
            port = int(marker.read_text())
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            connection.request(
                "GET",
                "/private-path-sentinel",
                headers={"Authorization": "private-header-sentinel"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            self.assertEqual(json.loads(response.read()), {"code": "invalid_input"})
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            connection.putrequest("POST", "/inference")
            connection.putheader("Content-Length", "100")
            connection.endheaders()
            connection.send(b"x")
            response = connection.getresponse()
            self.assertEqual(response.status, 503)
            self.assertEqual(json.loads(response.read())["code"], "deadline_exceeded")
            connection.close()
        finally:
            process.terminate()
            stdout, stderr = process.communicate(timeout=2)
        self.assertEqual(stdout, b"")
        self.assertNotIn(b"private-", stderr)
        logs = [json.loads(line) for line in stderr.splitlines()]
        self.assertTrue(logs)
        self.assertTrue(
            all(
                set(row) == {"service", "role", "event", "code", "duration_seconds", "input_bytes"}
                for row in logs
            )
        )


class MetricsAndAdapterTests(unittest.TestCase):
    def test_engine_cli_failure_does_not_echo_private_arguments(self):
        result = subprocess.run(
            [sys.executable, "-I", str(ENGINE), "private-argument-sentinel"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("private-argument", result.stdout + result.stderr)
        self.assertEqual(
            json.loads(result.stderr), {"event": "engine_start_failed", "code": "invalid_input"}
        )

    def test_piper_runtime_is_separately_locked_to_the_selected_native_versions(self):
        directory = ROOT / "local-setup/inference/piper"
        project = tomllib.loads((directory / "pyproject.toml").read_text())
        lock = tomllib.loads((directory / "uv.lock").read_text())
        self.assertEqual(
            project["project"]["dependencies"], ["piper-tts==1.8.0", "onnxruntime==1.31.1"]
        )
        versions = {item["name"]: item["version"] for item in lock["package"]}
        self.assertEqual(versions["piper-tts"], "1.8.0")
        self.assertEqual(versions["onnxruntime"], "1.31.1")
        self.assertFalse({"torch", "flask", "livekit-agents"} & set(versions))

    def test_engine_builds_retain_selected_source_and_isolate_nonroot_processes(self):
        whisper = (ROOT / "local-setup/docker/whisper.Dockerfile").read_text()
        piper = (ROOT / "local-setup/docker/piper.Dockerfile").read_text()
        manifest = json.loads((ROOT / "local-setup/models/local-model-manifest.json").read_text())
        self.assertIn(manifest["engines"]["stt"]["source_commit"], whisper)
        self.assertIn("--branch v1.9.5", whisper)
        self.assertIn("WHISPER_CURL=OFF", whisper)
        self.assertIn("uv sync --frozen", piper)
        for content in (whisper, piper):
            self.assertIn("ARG PYTHON_IMAGE", content)
            self.assertIn("USER 10001:10001", content)
            self.assertNotIn("huggingface.co", content)
            self.assertNotIn("ollama pull", content)

    def test_metrics_are_numeric_single_active_process_observations(self):
        values = engine.EngineMetrics("stt")
        values.begin(100)
        with self.assertRaises(engine.EngineError):
            values.begin(1)
        values.finish(True, 50, 0.25)
        values.begin(20)
        values.finish(False, 0, 0.125)
        observed = values.snapshot()
        self.assertEqual(
            observed,
            {
                "schema_version": 1,
                "engine": "stt",
                "requests": 2,
                "succeeded": 1,
                "failed": 1,
                "active": 0,
                "max_active": 1,
                "processed_input_bytes": 120,
                "processed_output_bytes": 50,
                "duration_seconds": 0.375,
            },
        )
        self.assertNotIn("private", json.dumps(observed))

    def test_piper_invokes_the_verified_real_api_without_fixture_mapping_or_downloads(self):
        child_path = ROOT / "local-setup/inference/engine_child.py"
        spec = importlib.util.spec_from_file_location("engine_child_test", child_path)
        assert spec is not None and spec.loader is not None
        child = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(child)
        ort = Mock()
        voice_module = Mock()
        voice = voice_module.PiperVoice.load.return_value

        def synthesize(text, output, **kwargs):
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(22050)
            output.writeframes(b"\x01\x00" * 220)

        voice.synthesize_wav.side_effect = synthesize
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve()
            text = "arbitrary unit text passed intact"
            (path / "request.json").write_text(json.dumps({"text": text}))
            with patch.object(
                child.importlib,
                "import_module",
                side_effect=lambda name: ort if name == "onnxruntime" else voice_module,
            ):
                child.piper_speech(path)
            ort.disable_telemetry_events.assert_called_once_with()
            voice_module.PiperVoice.load.assert_called_once_with(
                "/models/piper/en_US-ljspeech-medium.onnx",
                config_path="/models/piper/en_US-ljspeech-medium.onnx.json",
                use_cuda=False,
                download_dir=str(path),
                include_alignments=False,
            )
            self.assertEqual(voice.synthesize_wav.call_args.args[0], text)
            self.assertFalse(voice.use_tashkeel)
            self.assertTrue(
                engine.pcm_wav(
                    (path / "result.wav").read_bytes(),
                    rate=22050,
                    seconds=20,
                    maximum=engine.MAX_OUTPUT_WAV,
                )
            )
            arguments = child.whisper_arguments(path)
            self.assertIn("--output-json", arguments)
            self.assertIn("--no-gpu", arguments)
            self.assertNotIn("--no-context", arguments)

    def test_request_files_are_removed_after_success_and_controlled_child_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            script = root / "fake_child.py"
            script.write_text(
                "import sys,wave;from pathlib import Path\np=Path(sys.argv[2]);w=wave.open(str(p/'result.wav'),'wb');w.setnchannels(1);w.setsampwidth(2);w.setframerate(22050);w.writeframes(b'\\x01\\x00'*220);w.close()\n"
            )
            original = engine.tempfile.mkdtemp
            created = []

            def make(*args, **kwargs):
                value = original(*args, dir=root, **kwargs)
                created.append(Path(value))
                return value

            with patch.object(engine.tempfile, "mkdtemp", side_effect=make):
                output, kind = engine.infer(
                    "tts", b'{"text":"private-unit-content"}', "application/json", child=script
                )
            self.assertEqual(kind, "audio/wav")
            self.assertTrue(output)
            self.assertTrue(all(not path.exists() for path in created))
            script.write_text("raise SystemExit(7)\n")
            with (
                patch.object(engine.tempfile, "mkdtemp", side_effect=make),
                self.assertRaises(engine.EngineError),
            ):
                engine.infer(
                    "tts", b'{"text":"private-unit-content"}', "application/json", child=script
                )
            self.assertTrue(all(not path.exists() for path in created))


if __name__ == "__main__":
    unittest.main()
