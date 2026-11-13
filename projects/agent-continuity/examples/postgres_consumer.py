"""Optional-extra import and safe controlled startup failure; no database is provisioned."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import socket

from continuity_lab.api import StorageUnavailable, safe_error_code
from continuity_lab.postgres_api import (
    AuthenticatedActor,
    BearerToken,
    ManagedCaseClient,
    PostgresSettings,
    open_postgres_client,
)


def main() -> int:
    assert importlib.util.find_spec("services") is None
    assert importlib.util.find_spec("harness") is None
    assert not hasattr(ManagedCaseClient, "run")
    actor = AuthenticatedActor("installed-example", "example-traveller")
    token = BearerToken("synthetic-test-token-" + "x" * 32)
    # Keep an owned loopback port bound without listening. No shared database or
    # arbitrary system service is selected by the controlled connection failure.
    with socket.socket() as refused:
        refused.bind(("127.0.0.1", 0))
        settings = PostgresSettings(
            host="127.0.0.1",
            port=refused.getsockname()[1],
            password="private-configuration-sentinel",
        )
        assert "private-configuration-sentinel" not in repr(settings)
        assert token.value not in repr(token)
        try:
            open_postgres_client(actor=actor, token=token, settings=settings)
        except StorageUnavailable as failure:
            code = safe_error_code(failure)
        else:
            raise AssertionError("The explicit absent fixture unexpectedly accepted startup")
    assert code == "storage_unavailable"
    print(
        json.dumps(
            {
                "schema_version": 1,
                "status": "passed",
                "declared_postgres_extra": True,
                "psycopg_version": importlib.metadata.version("psycopg"),
                "prometheus_client_version": importlib.metadata.version("prometheus-client"),
                "typed_client_has_no_callable_endpoint": True,
                "safe_startup_failure_code": code,
                "positive_postgres_store_not_exercised": True,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
