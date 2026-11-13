"""Installed-runtime inspection for the isolated Phase F worker demonstration."""

import hashlib
import importlib
import json
import os
import re
import sys
from pathlib import Path

from continuity_lab.completion_sink import CompletionSink
from continuity_lab.mutation_supplier import MutationSupplier


def main() -> int:
    expected = json.loads(os.environ["DEMO_MODULE_HASHES"])
    if type(expected) is not dict or not {
        "worker_runtime",
        "worker_cli",
        "postgres_leases",
        "postgres_work",
    } <= set(expected):
        raise ValueError("Complete installed runtime proof is required")
    for name, digest in expected.items():
        if (
            type(name) is not str
            or re.fullmatch(r"[a-z][a-z0-9_]*", name) is None
            or type(digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError("Installed runtime proof is invalid")
        module = importlib.import_module("continuity_lab." + name)
        if module.__file__ is None:
            raise RuntimeError("Installed module path is missing")
        path = Path(module.__file__).resolve()
        if (
            "/site-packages/" not in str(path)
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise RuntimeError("Installed runtime differs from inspected source")
    supplier = MutationSupplier("/data/supplier.sqlite3")
    booking = supplier.booking(
        scope_id=os.environ["P1_WORKER_SCOPE"], booking_reference="DEMO-BK-001"
    )
    sink = CompletionSink("/data/completion.sqlite3")
    print(
        json.dumps(
            {
                "status": "passed",
                "installed_modules": len(expected),
                "module_hashes_verified": True,
                "supplier_id": supplier.provider_id,
                "booking_revision": booking.revision,
                "check_in": booking.check_in.isoformat(),
                "mutations": supplier.count_mutations(scope_id=os.environ["P1_WORKER_SCOPE"]),
                "apply_calls": supplier.count_calls(scope_id=os.environ["P1_WORKER_SCOPE"]),
                "inquiries": supplier.count_inquiries(scope_id=os.environ["P1_WORKER_SCOPE"]),
                "receiver_events": sink.count(),
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - secret-safe operator probe
        print('{"status":"failed","code":"worker_probe_failed"}')
        sys.exit(1)
