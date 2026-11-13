"""Fixed opt-in provider identities; credentials stay inside the native factory."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Final

from .inference_settings import LOCAL_INSTRUCTIONS, LocalInferenceError

PROVIDER_MODE: Final = "provider_real"
PROVIDER_STT_MODEL: Final = "nova-3"
PROVIDER_LLM_MODEL: Final = "gpt-5.4-mini"
PROVIDER_TTS_MODEL: Final = "eleven_v4_turbo"
PROVIDER_VOICE: Final = "JBFqnCBsd6RMkjVDRZzb"
PROVIDER_SAMPLE_RATE: Final = 24000
OPENAI_BASE_URL: Final = "https://api.openai.com/v1"
DEEPGRAM_URL: Final = "https://api.deepgram.com/v1/listen"
ELEVEN_BASE_URL: Final = "https://api.elevenlabs.io/v1"
PROVIDER_GREETING = (
    "This session uses configured cloud speech and language providers. "
    "Exact booking changes still require confirmation in the workflow panel."
)
PROVIDER_INSTRUCTIONS = LOCAL_INSTRUCTIONS.replace("local workflow assistant", "workflow assistant")


class ProviderInferenceError(LocalInferenceError):
    """Finite shared boundary categories; no provider message or credential text."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in self.CODES:
            raise ValueError("Invalid provider inference category")
        self.code = code
        RuntimeError.__init__(self, "The bounded provider inference operation did not complete")


@dataclass(frozen=True, repr=False)
class ProviderCredentials:
    openai: str = field(repr=False, compare=False)
    deepgram: str = field(repr=False, compare=False)
    eleven: str = field(repr=False, compare=False)

    @classmethod
    def from_environment(cls) -> ProviderCredentials:
        # Called only inside create_provider_runtime after explicit mode validation.
        values = []
        for name in ("OPENAI_API_KEY", "DEEPGRAM_API_KEY", "ELEVEN_API_KEY"):
            value = os.environ.get(name)
            if (
                type(value) is not str
                or not 16 <= len(value) <= 512
                or any(not 33 <= ord(char) <= 126 for char in value)
            ):
                raise ProviderInferenceError("invalid_configuration")
            values.append(value)
        return cls(*values)
