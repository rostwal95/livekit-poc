/** Configured policy-v2 consumer; importing performs no setup or I/O. */
import { pathToFileURL } from 'node:url';
import { ContractError } from '@livekit-ecosystem/delegation-specialist';
import {
  encodeFixedPolicyRequest,
  encodeFixedPolicyResult,
  parseFixedPolicyRequest,
  parseFixedPolicyResult,
  snapshotFixedPolicyRecords,
  verifyFixedPolicyFacts,
} from '@livekit-ecosystem/delegation-specialist/fixed-policy';
/**
 * @param {{invoke(request: import('@livekit-ecosystem/delegation-specialist/fixed-policy').FixedPolicyRequest): Promise<import('@livekit-ecosystem/delegation-specialist/fixed-policy').FixedPolicyResult>}} client
 * @param {import('@livekit-ecosystem/delegation-specialist/fixed-policy').FixedPolicyRequest} request
 * @param {readonly import('@livekit-ecosystem/delegation-specialist').EvidenceRecord[]} records
 */
export async function evaluateFixedPolicy(client, request, records) {
  const snapshot = parseFixedPolicyRequest(encodeFixedPolicyRequest(request));
  const sources = snapshotFixedPolicyRecords(records);
  const observed = await client.invoke(snapshot);
  const result = parseFixedPolicyResult(encodeFixedPolicyResult(observed));
  if (verifyFixedPolicyFacts(snapshot, result, sources, Date.now()) === 'expired')
    throw new ContractError('expired');
  return result;
}
/**
 * Explicit historical observation. The configured public client copies exactly
 * two bounded JSON sources and verifies all facts before exposing late history.
 * @param {import('@livekit-ecosystem/delegation-specialist/fixed-policy').FixedPolicySpecialistClient} client
 * @param {import('@livekit-ecosystem/delegation-specialist/fixed-policy').FixedPolicyRequest} request
 * @param {readonly import('@livekit-ecosystem/delegation-specialist').EvidenceRecord[]} records
 * @returns {Promise<import('@livekit-ecosystem/delegation-specialist/fixed-policy').FixedPolicyResultObservation>}
 */
export async function observeFixedPolicy(client, request, records) {
  return await client.invokeObserved(request, records);
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(
    JSON.stringify({
      status: 'configuration_required',
      capability: 'booking.evaluate_policy',
      input_schema_version: 2,
    }),
  );
}
