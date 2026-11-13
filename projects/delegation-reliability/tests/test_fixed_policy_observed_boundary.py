"""Independent public observed-client evidence and historical-truth regressions."""

from __future__ import annotations

import copy
import json
import time
import unittest
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch

from delegation_reliability.contracts import ContractError, Scope, canonical
from delegation_reliability.fixed_policy import FixedPolicySpecialistClient
from delegation_reliability.fixed_policy_contracts import (
    FixedPolicyRequest,
    produce_fixed_policy_request,
)
from delegation_reliability.http_client import (
    SpecialistClient,
    SpecialistEndpoint,
    SpecialistHttpError,
)
from delegation_reliability.security import EvidenceRecord

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((ROOT / "contracts/delegation/fixed-policy-v2.json").read_bytes())


def inputs() -> tuple[FixedPolicyRequest, tuple[EvidenceRecord, ...], bytes]:
    value = copy.deepcopy(FIXTURE["producer_input"])
    value["deadline_at_ms"] = time.time_ns() // 1_000_000 + 60_000
    request = produce_fixed_policy_request(value)
    records = tuple(
        EvidenceRecord(request.scope, ref, FIXTURE[key].encode())
        for ref, key in zip(request.evidence, ("policy_body_utf8", "facts_body_utf8"), strict=True)
    )
    result = copy.deepcopy(FIXTURE["result"])
    result["input_fingerprint"] = request.input_fingerprint
    result["completed_at_ms"] = time.time_ns() // 1_000_000
    return request, records, canonical(result)


class ObservedEvidenceBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_evidence_inventory_denied_before_transport(self) -> None:
        request, records, body = inputs()
        bad_inventories: tuple[object, ...] = (
            None,
            (),
            list(records),
            records[:1],
            (*records, records[0]),
            (
                *records,
                replace(
                    records[0],
                    reference=replace(records[0].reference, source_id="unreferenced_source"),
                ),
            ),
            (replace(records[0], scope=Scope("foreign_tenant", "foreign_account")), records[1]),
            (replace(records[0], body=b"{}"), records[1]),
        )
        for index, invalid in enumerate(bad_inventories):
            with self.subTest(kind=type(invalid).__name__, inventory=index):
                transport = AsyncMock(return_value=body)
                client = FixedPolicySpecialistClient(SpecialistEndpoint(1), "Bearer " + "A" * 43)
                try:
                    with (
                        patch.object(SpecialistClient, "_call", transport),
                        self.assertRaises((ContractError, SpecialistHttpError)),
                    ):
                        await client.invoke_observed(
                            request, evidence=cast(tuple[EvidenceRecord, ...], invalid)
                        )
                    transport.assert_not_awaited()
                    self.assertEqual(client.active, 0)
                finally:
                    await client.close()

    async def test_valid_source_observation_is_distinct_from_unsupported_result(self) -> None:
        request, records, body = inputs()
        client = FixedPolicySpecialistClient(SpecialistEndpoint(1), "Bearer " + "A" * 43)
        try:
            with patch.object(SpecialistClient, "_call", AsyncMock(return_value=body)):
                observed = await client.invoke_observed(request, evidence=records)
            self.assertEqual(observed.applicability, "candidate")
            self.assertIs(observed.result.eligible, True)
            unsupported = json.loads(body)
            unsupported["eligible"] = False
            with (
                patch.object(
                    SpecialistClient, "_call", AsyncMock(return_value=canonical(unsupported))
                ),
                self.assertRaises(SpecialistHttpError) as error,
            ):
                await client.invoke_observed(request, evidence=records)
            self.assertEqual(error.exception.code, "invalid_response")
        finally:
            await client.close()

    async def test_expiry_never_bypasses_factual_validation(self) -> None:
        request, records, body = inputs()
        wrong = json.loads(body)
        wrong["eligible"] = False
        client = FixedPolicySpecialistClient(SpecialistEndpoint(1), "Bearer " + "A" * 43)
        try:
            for invalid, payload in ((True, canonical(wrong)), (False, body)):
                with (
                    self.subTest(unsupported=invalid),
                    patch("delegation_reliability.http_client.time.time_ns") as clock,
                ):
                    clock.return_value = request.deadline_at_ms * 1_000_000 - 1_000_000_000

                    async def delayed_result(
                        *args: object, response: bytes = payload, **kwargs: object
                    ) -> bytes:
                        # Advance only after invocation starts, modelling late I/O.
                        clock.return_value = (request.deadline_at_ms + 1) * 1_000_000
                        return response

                    transport = AsyncMock(side_effect=delayed_result)
                    with patch.object(SpecialistClient, "_call", transport):
                        if invalid:
                            with self.assertRaises(SpecialistHttpError) as error:
                                await client.invoke_observed(request, evidence=records)
                            self.assertEqual(error.exception.code, "invalid_response")
                        else:
                            historical = await client.invoke_observed(request, evidence=records)
                            self.assertEqual(historical.applicability, "expired")
                            self.assertIs(historical.result.eligible, True)
                    transport.assert_awaited_once()
        finally:
            await client.close()


if __name__ == "__main__":
    unittest.main()
