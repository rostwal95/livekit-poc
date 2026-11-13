"""Versioned private owner profile for the joined local application.

The profile is startup configuration, never an execution queue or an input-selected
authority. Imports perform no I/O. Provider credentials have no fields here.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import cast
from uuid import UUID

from continuity_lab.postgres_api import AuthenticatedActor, BearerToken, PostgresSettings
from delegation_reliability.contracts import (
    ContractError,
    Scope,
    decode,
    identifier,
    integer,
    object_fields,
    text,
)
from delegation_reliability.fixed_policy_contracts import (
    FIXED_POLICY_MINIMUM_DAYS,
    FIXED_POLICY_RULE,
    FIXED_POLICY_VERSION,
    FixedPolicyRequest,
    encode_fixed_policy_request,
    parse_fixed_policy_request,
)
from delegation_reliability.security import EvidenceRecord

from .jobs import EvidenceCatalogue, JobError
from .origin_router import RevisionTemplateCatalog

PROFILE_BYTES = 262144
_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_PROVIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SCHEMA = re.compile(r"[a-z][a-z0-9_]{0,62}")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


class ProfileError(ValueError):
    """A single finite code never includes configuration or dependency text."""

    def __init__(self) -> None:
        super().__init__("invalid_profile")


def _need(condition: bool) -> None:
    if not condition:
        raise ProfileError()


def _text(value: object, pattern: re.Pattern[str]) -> str:
    _need(type(value) is str and pattern.fullmatch(value) is not None)
    try:
        cast(str, value).encode("utf-8", "strict")
    except UnicodeError:
        raise ProfileError() from None
    return cast(str, value)


def _uuid(value: object) -> str:
    _need(type(value) is str and len(value) == 36)
    try:
        parsed = UUID(cast(str, value))
        _need(str(parsed) == value and parsed.version == 4)
    except (ValueError, AttributeError, TypeError):
        raise ProfileError() from None
    return cast(str, value)


def _integer(value: object, minimum: int, maximum: int) -> int:
    _need(type(value) is int and minimum <= value <= maximum)
    return cast(int, value)


def _object(value: object, names: set[str]) -> dict[str, object]:
    _need(type(value) is dict and set(value) == names)
    return cast(dict[str, object], value)


@dataclass(frozen=True, slots=True)
class ProfileRoute:
    profile_id: str
    receiver_id: str
    scope: Scope
    case_id: str
    conversation_id: str
    recipient_id: str

    def __post_init__(self) -> None:
        _uuid(self.profile_id)
        _uuid(self.receiver_id)
        _need(type(self.scope) is Scope)
        object.__setattr__(
            self,
            "scope",
            Scope(_text(self.scope.tenant_id, _ID), _text(self.scope.account_id, _ID)),
        )
        for value in (self.case_id, self.conversation_id, self.recipient_id):
            _text(value, _ID)


@dataclass(frozen=True, slots=True)
class ProfilePorts:
    case: int = 11021
    native_origin: int = 11022
    sms_origin: int = 11023
    native: int = 11024
    sms: int = 11025
    read: int = 11026
    receiver: int = 11027
    specialist: int = 11028

    def __post_init__(self) -> None:
        values = tuple(getattr(self, f.name) for f in fields(self))
        for value in values:
            _integer(value, 1, 65535)
        _need(len(set(values)) == len(values))


@dataclass(frozen=True, slots=True)
class ProfileDatabase:
    port: int
    case_schema: str
    work_schema: str
    channel_schema: str

    def __post_init__(self) -> None:
        _integer(self.port, 1, 65535)
        schemas = (self.case_schema, self.work_schema, self.channel_schema)
        for value in schemas:
            _text(value, _SCHEMA)
        _need(len(set(schemas)) == 3)
        _need(self.work_schema.startswith("p1_work_"))


@dataclass(frozen=True, slots=True)
class ProfileCase:
    actor_id: str
    scope_id: str
    task_id: str
    authority_case_id: str

    def __post_init__(self) -> None:
        _text(self.actor_id, _ID)
        _text(self.scope_id, _ID)
        _uuid(self.task_id)
        _uuid(self.authority_case_id)


@dataclass(frozen=True, slots=True, repr=False)
class ProfileCredentials:
    postgres_password: str = field(repr=False)
    account_token: str = field(repr=False)
    native_publisher_token: str = field(repr=False)
    result_publisher_token: str = field(repr=False)
    worker_bearer: str = field(repr=False)
    native_origin_bearer: str = field(repr=False)
    sms_origin_bearer: str = field(repr=False)
    case_bearer: str = field(repr=False)
    p1_case_token: str = field(repr=False)
    p1_work_token: str = field(repr=False)
    specialist_bearer: str = field(repr=False)

    def __post_init__(self) -> None:
        _text(self.postgres_password, re.compile(r"[^\x00-\x20\x7f]{32,128}"))
        _need(len(self.postgres_password.encode("utf-16-le")) <= 256)
        capabilities = tuple(
            getattr(self, f.name) for f in fields(self) if f.name != "postgres_password"
        )
        for value in capabilities:
            _text(value, _TOKEN)
        _need(len(set(capabilities)) == len(capabilities))

    def node_environment(self) -> dict[str, str]:
        """Secret values for one role-closed child environment; never log this map."""
        return {
            "P2_DEMO_POSTGRES_PASSWORD": self.postgres_password,
            "P2_DEMO_ACCOUNT_TOKEN": self.account_token,
            "P2_DEMO_NATIVE_PUBLISHER_TOKEN": self.native_publisher_token,
            "P2_DEMO_RESULT_PUBLISHER_TOKEN": self.result_publisher_token,
            "P2_DEMO_WORKER_BEARER": self.worker_bearer,
            "P2_DEMO_NATIVE_ORIGIN_BEARER": self.native_origin_bearer,
            "P2_DEMO_SMS_ORIGIN_BEARER": self.sms_origin_bearer,
            "P2_DEMO_CASE_AUTHORIZATION": "Bearer " + self.case_bearer,
        }


def _policy_bodies(template: FixedPolicyRequest, bodies: tuple[bytes, bytes]) -> None:
    """Validate supported startup evidence; this creates no result or authority."""
    policy = object_fields(
        decode(bodies[0], 4096),
        {"schema_version", "kind", "policy_version", "rule_id", "minimum_notice_days", "note"},
    )
    text(policy["note"])
    _need(type(policy["schema_version"]) is int and policy["schema_version"] == 1)
    _need(
        policy["kind"] == "booking.notice_policy"
        and policy["policy_version"]
        == template.context_snapshot.policy_version
        == FIXED_POLICY_VERSION
    )
    _need(
        policy["rule_id"] == FIXED_POLICY_RULE
        and type(policy["minimum_notice_days"]) is int
        and policy["minimum_notice_days"] == FIXED_POLICY_MINIMUM_DAYS
    )
    facts = object_fields(
        decode(bodies[1], 4096), {"schema_version", "kind", "observations", "note"}
    )
    text(facts["note"])
    _need(
        type(facts["schema_version"]) is int
        and facts["schema_version"] == 1
        and facts["kind"] == "booking.notice_facts"
    )
    observations = facts["observations"]
    _need(type(observations) is list and len(observations) <= 2)
    ids = set()
    for item in cast(list[object], observations):
        item = object_fields(item, {"fact_id", "days_before_arrival"})
        fact_id = identifier(item["fact_id"])
        _need(fact_id not in ids)
        ids.add(fact_id)
        integer(item["days_before_arrival"], 0, 3650)


@dataclass(frozen=True, slots=True)
class ProfilePolicy:
    template: FixedPolicyRequest = field(repr=False)
    bodies: tuple[bytes, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        try:
            _need(type(self.template) is FixedPolicyRequest)
            template = parse_fixed_policy_request(encode_fixed_policy_request(self.template))
            _need(type(self.bodies) is tuple and len(self.bodies) == 2)
            for ref, body in zip(template.evidence, self.bodies, strict=True):
                _need(type(body) is bytes and 1 <= len(body) <= 4096)
                _need(
                    ref.byte_length == len(body) and ref.sha256 == hashlib.sha256(body).hexdigest()
                )
            _policy_bodies(template, self.bodies)
            object.__setattr__(self, "template", template)
            EvidenceCatalogue((self.records(),))
        except (ContractError, JobError, ValueError, TypeError, AttributeError):
            raise ProfileError() from None

    def records(self) -> tuple[EvidenceRecord, ...]:
        return tuple(
            EvidenceRecord(self.template.scope, ref, body)
            for ref, body in zip(self.template.evidence, self.bodies, strict=True)
        )


@dataclass(frozen=True, slots=True, repr=False)
class OwnerProfile:
    route: ProfileRoute
    ports: ProfilePorts
    database: ProfileDatabase
    case: ProfileCase
    credentials: ProfileCredentials = field(repr=False)
    app_owner_id: str
    native_provider_account_id: str
    sms_provider_account_id: str
    policies: tuple[ProfilePolicy, ...] = field(repr=False)
    deadline_window_ms: int = 60000

    def __post_init__(self) -> None:
        for value, expected in (
            (self.route, ProfileRoute),
            (self.ports, ProfilePorts),
            (self.database, ProfileDatabase),
            (self.case, ProfileCase),
            (self.credentials, ProfileCredentials),
        ):
            _need(type(value) is expected)
        _uuid(self.app_owner_id)
        _text(self.native_provider_account_id, _PROVIDER_ID)
        _text(self.sms_provider_account_id, _PROVIDER_ID)
        _integer(self.deadline_window_ms, 1000, 60000)
        _need(type(self.policies) is tuple and 1 <= len(self.policies) <= 16)
        copied = []
        for policy in self.policies:
            _need(type(policy) is ProfilePolicy)
            item = ProfilePolicy(policy.template, policy.bodies)
            _need(
                (item.template.scope, item.template.case_id, item.template.conversation_id)
                == (self.route.scope, self.route.case_id, self.route.conversation_id)
            )
            copied.append(item)
        _need(len({p.template.request_revision for p in copied}) == len(copied))
        RevisionTemplateCatalog(tuple(p.template for p in copied))
        object.__setattr__(self, "policies", tuple(copied))
        self.specialist_configuration()

    def case_settings(self) -> PostgresSettings:
        return PostgresSettings(
            port=self.database.port,
            schema=self.database.case_schema,
            password=self.credentials.postgres_password,
        )

    def work_settings(self) -> PostgresSettings:
        return PostgresSettings(
            port=self.database.port,
            schema=self.database.work_schema,
            password=self.credentials.postgres_password,
        )

    def actor(self) -> AuthenticatedActor:
        return AuthenticatedActor(self.case.actor_id, self.case.scope_id)

    def case_token(self) -> BearerToken:
        return BearerToken(self.credentials.p1_case_token)

    def templates(self) -> RevisionTemplateCatalog:
        return RevisionTemplateCatalog(tuple(p.template for p in self.policies))

    def evidence(self) -> EvidenceCatalogue:
        pairs = []
        seen = set()
        for policy in self.policies:
            key = (policy.template.scope, policy.template.evidence)
            if key not in seen:
                pairs.append(policy.records())
                seen.add(key)
        return EvidenceCatalogue(tuple(pairs))

    def specialist_configuration(self) -> dict[str, object]:
        """Return fresh nonsecret evidence for one fixed scripted specialist.

        The public specialist registry keys records by scope and source identity.
        Equal records shared by revision templates are emitted once. Conflicting
        versions or bytes cannot silently shadow the winning request's evidence.
        """
        records: dict[str, EvidenceRecord] = {}
        total = 0
        for policy in self.policies:
            for record in policy.records():
                prior = records.get(record.reference.source_id)
                if prior is not None:
                    _need(prior == record)
                    continue
                records[record.reference.source_id] = record
                total += len(record.body)
        _need(1 <= len(records) <= 32 and total <= 131072)
        evidence: list[dict[str, object]] = []
        for record in records.values():
            reference = record.reference
            evidence.append(
                {
                    "reference": {
                        "source_id": reference.source_id,
                        "version": reference.version,
                        "sha256": reference.sha256,
                        "media_type": reference.media_type,
                        "byte_length": reference.byte_length,
                        "width": reference.width,
                        "height": reference.height,
                    },
                    "bodyBase64": base64.b64encode(record.body).decode("ascii"),
                }
            )
        return {
            "schemaVersion": 1,
            "label": "scripted",
            "scope": {
                "tenantId": self.route.scope.tenant_id,
                "accountId": self.route.scope.account_id,
            },
            "port": self.ports.specialist,
            "evidence": evidence,
        }

    def node_configuration(self) -> dict[str, object]:
        r, p, d = self.route, self.ports, self.database

        def endpoint(port: int) -> dict[str, object]:
            return {"host": "127.0.0.1", "port": port}

        return {
            "schemaVersion": 1,
            "profileInboxLimit": 16,
            "route": {
                "profileId": r.profile_id,
                "receiverId": r.receiver_id,
                "scope": {"tenantId": r.scope.tenant_id, "accountId": r.scope.account_id},
                "caseId": r.case_id,
                "conversationId": r.conversation_id,
                "recipientId": r.recipient_id,
            },
            "postgres": {
                "host": "127.0.0.1",
                "port": d.port,
                "database": "livekit_lab",
                "user": "livekit_lab",
                "schema": d.channel_schema,
            },
            "providers": {
                "native": {
                    "tenantId": r.scope.tenant_id,
                    "provider": "livekit",
                    "providerAccountId": self.native_provider_account_id,
                },
                "sms": {
                    "tenantId": r.scope.tenant_id,
                    "provider": "fake_sms",
                    "providerAccountId": self.sms_provider_account_id,
                },
            },
            "simulationHmac": "public_synthetic_v1",
            "caseEndpoint": endpoint(p.case),
            "originEndpoints": {"native": endpoint(p.native_origin), "sms": endpoint(p.sms_origin)},
            "listen": {
                "nativePort": p.native,
                "smsPort": p.sms,
                "readPort": p.read,
                "receiverPort": p.receiver,
            },
        }


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        _need(key not in result)
        result[key] = value
    return result


def _no_number(_: str) -> object:
    raise ProfileError()


def encode_owner_profile(profile: OwnerProfile) -> bytes:
    """Private serialization includes credentials; write only to a private file."""
    _need(type(profile) is OwnerProfile)
    data = {
        "schemaVersion": 1,
        "kind": "channel.policy_owner_profile",
        "appOwnerId": profile.app_owner_id,
        "route": {
            f.name: getattr(profile.route, f.name)
            for f in fields(profile.route)
            if f.name != "scope"
        }
        | {
            "scope": {
                "tenant_id": profile.route.scope.tenant_id,
                "account_id": profile.route.scope.account_id,
            }
        },
        "ports": {f.name: getattr(profile.ports, f.name) for f in fields(profile.ports)},
        "database": {f.name: getattr(profile.database, f.name) for f in fields(profile.database)},
        "case": {f.name: getattr(profile.case, f.name) for f in fields(profile.case)},
        "credentials": {
            f.name: getattr(profile.credentials, f.name) for f in fields(profile.credentials)
        },
        "nativeProviderAccountId": profile.native_provider_account_id,
        "smsProviderAccountId": profile.sms_provider_account_id,
        "deadlineWindowMs": profile.deadline_window_ms,
        "policies": [
            {
                "template": p.template.to_wire(),
                "bodiesBase64": [base64.b64encode(body).decode("ascii") for body in p.bodies],
            }
            for p in profile.policies
        ],
    }
    try:
        raw = (
            json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise ProfileError() from None
    _need(len(raw) <= PROFILE_BYTES)
    return raw


def parse_owner_profile(raw: bytes) -> OwnerProfile:
    try:
        _need(type(raw) is bytes and 0 < len(raw) <= PROFILE_BYTES)
        value: object = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=_pairs,
            parse_float=_no_number,
            parse_constant=_no_number,
        )
        data = _object(
            value,
            {
                "schemaVersion",
                "kind",
                "appOwnerId",
                "route",
                "ports",
                "database",
                "case",
                "credentials",
                "nativeProviderAccountId",
                "smsProviderAccountId",
                "deadlineWindowMs",
                "policies",
            },
        )
        _need(
            type(data["schemaVersion"]) is int
            and data["schemaVersion"] == 1
            and data["kind"] == "channel.policy_owner_profile"
        )
        route_data = _object(data["route"], {f.name for f in fields(ProfileRoute)})
        scope = _object(route_data["scope"], {"tenant_id", "account_id"})
        route = ProfileRoute(
            _uuid(route_data["profile_id"]),
            _uuid(route_data["receiver_id"]),
            Scope(_text(scope["tenant_id"], _ID), _text(scope["account_id"], _ID)),
            _text(route_data["case_id"], _ID),
            _text(route_data["conversation_id"], _ID),
            _text(route_data["recipient_id"], _ID),
        )
        ports = ProfilePorts(
            **cast(dict[str, int], _object(data["ports"], {f.name for f in fields(ProfilePorts)}))
        )
        database_data = _object(data["database"], {f.name for f in fields(ProfileDatabase)})
        database = ProfileDatabase(
            _integer(database_data["port"], 1, 65535),
            _text(database_data["case_schema"], _SCHEMA),
            _text(database_data["work_schema"], _SCHEMA),
            _text(database_data["channel_schema"], _SCHEMA),
        )
        case = ProfileCase(
            **cast(dict[str, str], _object(data["case"], {f.name for f in fields(ProfileCase)}))
        )
        credentials = ProfileCredentials(
            **cast(
                dict[str, str],
                _object(data["credentials"], {f.name for f in fields(ProfileCredentials)}),
            )
        )
        entries = data["policies"]
        _need(type(entries) is list and 1 <= len(entries) <= 16)
        policies = []
        for entry in cast(list[object], entries):
            entry = _object(entry, {"template", "bodiesBase64"})
            template = parse_fixed_policy_request(
                json.dumps(entry["template"], separators=(",", ":"), ensure_ascii=False).encode()
            )
            bodies = entry["bodiesBase64"]
            _need(type(bodies) is list and len(bodies) == 2)
            decoded = []
            for body in cast(list[object], bodies):
                _need(type(body) is str and 0 < len(body) <= 5464)
                decoded_body = base64.b64decode(cast(str, body), validate=True)
                _need(base64.b64encode(decoded_body).decode("ascii") == body)
                decoded.append(decoded_body)
            policies.append(ProfilePolicy(template, (decoded[0], decoded[1])))
        profile = OwnerProfile(
            route,
            ports,
            database,
            case,
            credentials,
            _uuid(data["appOwnerId"]),
            _text(data["nativeProviderAccountId"], _PROVIDER_ID),
            _text(data["smsProviderAccountId"], _PROVIDER_ID),
            tuple(policies),
            _integer(data["deadlineWindowMs"], 1000, 60000),
        )
        _need(encode_owner_profile(profile) == raw)
        return profile
    except (
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        UnicodeError,
        RecursionError,
        binascii.Error,
        ContractError,
    ):
        raise ProfileError() from None


def read_owner_profile(path: Path) -> OwnerProfile:
    """Trusted startup read of a bounded private regular file, never a dotenv file."""
    try:
        _need(isinstance(path, Path) and path.suffix == ".json")
        _need(path.is_absolute() and path.resolve(strict=True) == path)
        parent = path.parent.stat()
        _need(
            stat.S_ISDIR(parent.st_mode)
            and stat.S_IMODE(parent.st_mode) == 0o700
            and parent.st_uid == os.getuid()
        )
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(descriptor)
            _need(
                stat.S_ISREG(before.st_mode)
                and stat.S_IMODE(before.st_mode) == 0o600
                and before.st_nlink == 1
                and before.st_uid == os.getuid()
                and 0 < before.st_size <= PROFILE_BYTES
            )
            raw = os.read(descriptor, PROFILE_BYTES + 1)
            _need(not os.read(descriptor, 1))
            after = os.fstat(descriptor)
            _need(
                (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_mode,
                    before.st_uid,
                    before.st_nlink,
                    before.st_ctime_ns,
                )
                == (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_mode,
                    after.st_uid,
                    after.st_nlink,
                    after.st_ctime_ns,
                )
                and len(raw) == before.st_size
            )
        finally:
            os.close(descriptor)
        return parse_owner_profile(raw)
    except (OSError, ValueError, TypeError, AttributeError):
        raise ProfileError() from None
