/** One local scripted HTTP invocation through public exports. No provider credentials. */
import { createHash, randomBytes } from 'node:crypto';
import {
  CAPABILITY,
  EvidenceRegistry,
  LocalTrust,
  SpecialistClient,
  SpecialistServer,
  canonical,
  matchResult,
  produceRequest,
  tokenDigest,
} from '@livekit-ecosystem/delegation-specialist';

async function main() {
  const token = randomBytes(32).toString('base64url');
  const scope = Object.freeze({ tenant_id: 'tenant_demo', account_id: 'account_demo' });
  const policy = canonical({ minimum_notice_days: 7, policy_version: 'policy_v1' });
  const reference = Object.freeze({
    source_id: 'policy_demo',
    version: 'source_v1',
    sha256: createHash('sha256').update(policy).digest('hex'),
    media_type: 'application/json',
    byte_length: policy.byteLength,
    width: null,
    height: null,
  });
  const trust = new LocalTrust([
    {
      principal_id: 'demo_service',
      token_sha256: tokenDigest(token),
      scopes: [
        {
          scope,
          invoke_capabilities: [CAPABILITY],
          result_capabilities: [CAPABILITY],
          cancel_capabilities: [CAPABILITY],
          evidence_sources: [reference.source_id],
        },
      ],
    },
  ]);
  const evidence = new EvidenceRegistry([{ scope, reference, body: policy }]);
  const server = new SpecialistServer({ trust, evidence });
  let client;
  let failure;
  let observation;
  try {
    const endpoint = await server.listen();
    client = new SpecialistClient(endpoint, 'Bearer ' + token);
    const request = produceRequest({
      schema_version: 1,
      kind: 'delegation.request',
      capability: CAPABILITY,
      input_schema_version: 1,
      scope,
      delegation_id: 'delegation_demo',
      case_id: 'case_demo',
      request_revision: 1,
      context_snapshot: {
        policy_version: 'policy_v1',
        policy_source_id: reference.source_id,
        days_before_arrival: 14,
        note: 'Local scripted read-only policy example.',
      },
      evidence: [reference],
      deadline_at_ms: Date.now() + 10000,
      result_route: { conversation_id: 'conversation_demo' },
      attempt: { attempt_id: 'attempt_demo', number: 1 },
    });
    const result = await client.invoke(request);
    const classification = matchResult(request, result, Date.now());
    if (classification !== 'candidate' || result.eligible !== true || result.uncertainty !== 'none')
      throw new Error('example_failed');
    observation = {
      status: 'passed',
      mode: 'local_scripted_http',
      capability: CAPABILITY,
      result: classification,
      eligible: result.eligible,
      business_action: 'not_authorized',
      durable_acceptance: false,
    };
  } catch (error) {
    failure = error;
  } finally {
    try {
      if (client) await client.close();
    } catch (error) {
      failure ??= error;
    }
    try {
      await server.close();
    } catch (error) {
      failure ??= error;
    }
  }
  if (failure) throw failure;
  console.info(JSON.stringify({ ...observation, cleanup_complete: true }));
}

main().catch(() => {
  console.error(JSON.stringify({ status: 'failed', code: 'example_failed' }));
  process.exitCode = 1;
});
