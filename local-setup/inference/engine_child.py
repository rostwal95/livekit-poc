"""A single real inference attempt; all text/audio/output remains request-private."""

from __future__ import annotations

import importlib
import json
import os
import resource
import signal
import sys
import wave
from pathlib import Path


def whisper_arguments(directory: Path) -> list[str]:
    return [
        "/opt/whisper/bin/whisper-cli",
        "--model",
        "/models/whisper/ggml-base.en.bin",
        "--file",
        str(directory / "turn.wav"),
        "--threads",
        "4",
        "--processors",
        "1",
        "--no-gpu",
        "--no-fallback",
        "--temperature",
        "0",
        "--temperature-inc",
        "0",
        "--language",
        "en",
        "--output-json",
        "--output-file",
        str(directory / "result"),
        "--no-timestamps",
        "--suppress-nst",
    ]


def piper_speech(directory: Path) -> None:
    # Optional packages belong only to the isolated frozen Piper image. Dynamic
    # import confines their untyped interface to this short process boundary.
    onnxruntime = importlib.import_module("onnxruntime")
    PiperVoice = importlib.import_module("piper.voice").PiperVoice

    onnxruntime.disable_telemetry_events()
    text = json.loads((directory / "request.json").read_bytes())["text"]
    voice = PiperVoice.load(
        "/models/piper/en_US-ljspeech-medium.onnx",
        config_path="/models/piper/en_US-ljspeech-medium.onnx.json",
        use_cuda=False,
        download_dir=str(directory),
        include_alignments=False,
    )
    voice.use_tashkeel = False
    with wave.open(str(directory / "result.wav"), "wb") as output:
        voice.synthesize_wav(text, output, include_alignments=False)


def main() -> int:
    try:
        signal.setitimer(signal.ITIMER_REAL, 8)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
        mode, directory = sys.argv[1:]
        path = Path(directory)
        if mode == "stt":
            arguments = whisper_arguments(path)
            os.execv(arguments[0], arguments)
        elif mode == "tts":
            piper_speech(path)
        else:
            return 2
        return 0
    except BaseException:  # noqa: BLE001 - request entrypoint never prints dependency diagnostics
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
