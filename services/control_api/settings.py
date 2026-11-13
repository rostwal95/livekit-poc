"""Validated local configuration; secret fields never appear in repr output."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

AGENT_NAME = "local-transport-agent"
SCOPE_ID = "local-lab"
ConversationInference = Literal["scripted", "local_real", "provider_real"]


@dataclass(frozen=True, slots=True)
class Settings:
    livekit_url: str
    livekit_public_url: str
    livekit_api_key: str
    livekit_api_secret: str = field(repr=False)
    local_access_token: str = field(repr=False)
    postgres_password: str = field(repr=False)
    intake_database: Path = Path("/data/intake.sqlite3")
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "livekit_lab"
    postgres_user: str = "livekit_lab"
    business_enabled: bool = False
    business_scope: str = "demo-traveller"
    business_actor: str = "local-operator"
    business_supplier: Path = Path("/business/supplier.sqlite3")
    trace_endpoint: str | None = None
    business_worker_url: str = "http://conversation-agent:8082"
    conversation_inference_mode: ConversationInference = "scripted"

    def __post_init__(self) -> None:
        from .business_availability import validate_worker_url

        validate_worker_url(self.business_worker_url)
        _inference_mode(self.conversation_inference_mode)
        if type(self.business_enabled) is not bool:
            raise ValueError("Business activation must be explicit")
        from continuity_lab.authorization import AuthenticatedActor, BearerToken

        AuthenticatedActor(self.business_actor, self.business_scope)
        if self.business_enabled:
            BearerToken(self.local_access_token)
        for value in (self.livekit_url, self.livekit_public_url):
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"ws", "wss"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("LiveKit URLs must be credential-free ws/wss endpoints")
        if not self.livekit_api_key or len(self.livekit_api_secret) < 32:
            raise ValueError("LiveKit credentials are missing or too short")
        if len(self.local_access_token) < 32 or len(self.postgres_password) < 24:
            raise ValueError("Local credentials are missing or too short")
        if not 1 <= self.postgres_port <= 65535:
            raise ValueError("Invalid PostgreSQL port")
        if not all((self.postgres_host, self.postgres_db, self.postgres_user)):
            raise ValueError("PostgreSQL identity is incomplete")

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            return cls(
                livekit_url=os.environ.get("LIVEKIT_URL", "ws://livekit:7880"),
                livekit_public_url=os.environ.get("LIVEKIT_PUBLIC_URL", "ws://localhost:17880"),
                livekit_api_key=os.environ["LIVEKIT_API_KEY"],
                livekit_api_secret=os.environ["LIVEKIT_API_SECRET"],
                local_access_token=os.environ["LOCAL_ACCESS_TOKEN"],
                postgres_password=os.environ["POSTGRES_PASSWORD"],
                intake_database=Path(os.environ.get("INTAKE_DATABASE", "/data/intake.sqlite3")),
                postgres_host=os.environ.get("POSTGRES_HOST", "postgres"),
                postgres_port=int(os.environ.get("POSTGRES_PORT", "5432")),
                postgres_db=os.environ.get("POSTGRES_DB", "livekit_lab"),
                postgres_user=os.environ.get("POSTGRES_USER", "livekit_lab"),
                business_enabled=_enabled(os.environ.get("P1_BUSINESS_ENABLED", "0")),
                conversation_inference_mode=_inference_mode(
                    os.environ.get("P1_CONVERSATION_INFERENCE", "scripted")
                ),
                business_scope=os.environ.get("P1_WORKER_SCOPE", "demo-traveller"),
                business_actor="local-operator",
                business_supplier=Path(
                    os.environ.get("P1_BUSINESS_SUPPLIER_DB", "/business/supplier.sqlite3")
                ),
                trace_endpoint=os.environ.get("P1_TRACE_ENDPOINT") or None,
                business_worker_url=os.environ.get(
                    "P1_BUSINESS_WORKER_URL", "http://conversation-agent:8082"
                ),
            )
        except (KeyError, ValueError) as error:
            raise ValueError("Local service configuration is incomplete or invalid") from error


def _enabled(value: str) -> bool:
    if value not in {"0", "1"}:
        raise ValueError("Business activation must be zero or one")
    return value == "1"


def _inference_mode(value: object) -> ConversationInference:
    if type(value) is str:
        if value == "scripted":
            return "scripted"
        if value == "local_real":
            return "local_real"
        if value == "provider_real":
            return "provider_real"
    raise ValueError("Conversation inference mode must be scripted, local_real or provider_real")
