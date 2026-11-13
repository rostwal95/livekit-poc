/** Actual independently killed scripted model fixture; diagnostics are not an execution ledger. */
import { existsSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { runAgentWorker } from '@livekit-ecosystem/channel-continuity/agent-process';
if (
  [
    'P2_MIGRATION_PASSWORD',
    'P2_RUNTIME_PASSWORD',
    'PGHOSTADDR',
    'NODE_OPTIONS',
    'OPENAI_API_KEY',
  ].some((key) => process.env[key] !== undefined)
)
  throw new Error('unsafe_worker_environment');
runAgentWorker({
  allowedScopes: [{ tenantId: 'tenant-a', accountId: 'account-a' }],
  async prepare(context) {
    const diagnostic = {
      pid: process.pid,
      scope: context.scope,
      caseId: context.caseId,
      caseRevision: context.caseRevision,
      operationKey: context.operationKey,
      receiptId: context.message.receiptId,
      inputDigest: createHash('sha256').update(JSON.stringify(context)).digest('hex'),
    };
    if (process.env.P2_AGENT_DIAGNOSTICS)
      writeFileSync(
        join(process.env.P2_AGENT_DIAGNOSTICS, `model-${process.pid}.json`),
        JSON.stringify(diagnostic),
        { flag: 'wx', mode: 0o600 },
      );
    if (process.env.P2_AGENT_HOLD_FILE && existsSync(process.env.P2_AGENT_HOLD_FILE)) {
      writeFileSync(process.env.P2_AGENT_HELD_MARKER, String(process.pid) + '\n', {
        flag: 'wx',
        mode: 0o600,
      });
      await new Promise(() => {
        setInterval(() => {}, 1000);
      });
    }
    return { kind: 'investigation', source: 'scripted', caseRevision: context.caseRevision };
  },
}).catch(() => {
  process.exitCode = 1;
});
