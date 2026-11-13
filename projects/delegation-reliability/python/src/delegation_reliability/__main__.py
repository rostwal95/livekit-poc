"""Provider-free P3-A example; output contains safe observations, not prompt payloads."""

from __future__ import annotations

import asyncio
import json
import platform
import sys
from dataclasses import asdict
from importlib.metadata import version

from .baseline import run_baseline
from .models import BaselineError, PolicyInput


async def _run() -> dict[str, object]:
    value = PolicyInput()
    tool = await run_baseline("single_tool", value)
    native = await run_baseline("native_task_group", value)
    if tool.result != native.result:
        raise BaselineError()
    return {
        "schema_version": 1,
        "scope": "scripted_native_orchestration_only",
        "sdk_version": version("livekit-agents"),
        "python_version": platform.python_version(),
        "observations": [asdict(tool), asdict(native)],
        "equivalent_input_and_result": True,
        "paid_provider_calls": 0,
        "limitations": ["no_durable_recovery", "no_real_model", "no_browser_media"],
    }


def main() -> int:
    try:
        report = asyncio.run(_run())
    except BaselineError as error:
        print(json.dumps({"status": "failed", "code": error.code}), file=sys.stderr)
        return 1
    except Exception:  # noqa: BLE001 - Safe JSON process boundary, never BaseException.
        # Explicit process boundary: do not serialize SDK exception text/chains.
        print(json.dumps({"status": "failed", "code": "sdk_boundary_failed"}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "passed", **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
