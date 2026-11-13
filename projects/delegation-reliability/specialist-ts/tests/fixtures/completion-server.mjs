/** Trusted finite integration fixture; no body-selected hook or durable work owner. */
import { createHash } from 'node:crypto';
import { existsSync, writeFileSync } from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';
import {
  CAPABILITY,
  EvidenceRegistry,
  LocalTrust,
  SpecialistServer,
  canonical,
  tokenDigest,
} from '@livekit-ecosystem/delegation-specialist';

async function main() {
  const token = process.env.P3_COMPLETE_TOKEN;
  const ready = process.env.P3_COMPLETE_READY;
  const endpointFile = process.env.P3_COMPLETE_ENDPOINT_FILE;
  const barriers = process.env.P3_COMPLETE_BARRIERS;
  const stop = process.env.P3_COMPLETE_STOP;
  if (
    !/^[A-Za-z0-9_-]{43}$/.test(token ?? '') ||
    [ready, endpointFile, barriers, stop].some((value) => !value || value.length > 4096)
  ) {
    throw new Error('fixture_configuration');
  }
  const scope = Object.freeze({ tenant_id: 'tenant_p3', account_id: 'account_p3' });
  const body = canonical({ minimum_notice_days: 7, policy_version: 'policy_v1' });
  const reference = Object.freeze({
    source_id: 'policy_demo',
    version: 'source_v1',
    sha256: createHash('sha256').update(body).digest('hex'),
    media_type: 'application/json',
    byte_length: body.byteLength,
    width: null,
    height: null,
  });
  const trust = new LocalTrust([
    {
      principal_id: 'p3_check_service',
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
  let invocation = 0;
  const server = new SpecialistServer({
    trust,
    evidence: new EvidenceRegistry([{ scope, reference, body }]),
    observer: () => {},
    hooks: {
      beforeEvaluate: async () => {
        invocation++;
        const name = invocation === 1 ? 'delayed_a' : undefined;
        if (name === undefined) return;
        writeFileSync(`${barriers}/${name}.held`, 'reached\n', { flag: 'wx', mode: 0o600 });
        const deadline = performance.now() + 4500;
        while (!existsSync(`${barriers}/${name}.release`)) {
          if (performance.now() >= deadline) throw new Error('fixture_release_timeout');
          await delay(10);
        }
      },
    },
  });
  let clean = false;
  try {
    const endpoint = await server.listen();
    writeFileSync(
      endpointFile,
      JSON.stringify({ port: endpoint.port, node_version: process.versions.node }),
      { flag: 'wx', mode: 0o600 },
    );
    writeFileSync(ready, String(process.pid) + '\n', { flag: 'wx', mode: 0o600 });
    const deadline = performance.now() + 120000;
    while (!existsSync(stop)) {
      if (performance.now() >= deadline) throw new Error('fixture_stop_timeout');
      await delay(20);
    }
  } finally {
    await server.close();
    const metrics = server.metrics();
    clean = metrics.active === 0 && metrics.requests === 0 && metrics.sockets === 0;
  }
  if (!clean) throw new Error('fixture_cleanup');
  console.info(
    JSON.stringify({
      status: 'passed',
      cleanup_complete: true,
      invocation_count: invocation,
      active: 0,
      requests: 0,
      sockets: 0,
      node_version: process.versions.node,
    }),
  );
}
main().catch(() => {
  console.error(JSON.stringify({ status: 'failed', code: 'fixture_failed' }));
  process.exitCode = 1;
});
