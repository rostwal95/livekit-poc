/** Trusted negative fixture. It owns no DB/provider credential or business authority. */
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';
const mode = process.env.P2_AGENT_MODE ?? 'normal';
const chunks = [];
process.stdin.on('data', (chunk) => chunks.push(chunk));
process.stdin.once('end', () => {
  const raw = Buffer.concat(chunks).toString();
  const input = JSON.parse(raw);
  if (process.env.P2_AGENT_MARKER)
    writeFileSync(process.env.P2_AGENT_MARKER, String(process.pid) + '\n', {
      flag: 'wx',
      mode: 0o600,
    });
  if (mode === 'hold') {
    setInterval(() => {}, 1000);
    return;
  }
  if (mode === 'ignore') {
    process.on('SIGTERM', () => {});
    setInterval(() => {}, 1000);
    return;
  }
  if (mode === 'descendant') {
    const child = spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { stdio: 'ignore' });
    if (process.env.P2_AGENT_DESCENDANT)
      writeFileSync(process.env.P2_AGENT_DESCENDANT, String(child.pid) + '\n', {
        flag: 'wx',
        mode: 0o600,
      });
    setInterval(() => {}, 1000);
    return;
  }
  if (mode === 'oversize') {
    process.stdout.write('x'.repeat(4096));
    return;
  }
  if (mode === 'stderr') {
    process.stderr.write('PRIVATE_SENTINEL'.repeat(1000));
    return;
  }
  if (mode === 'malformed') {
    process.stdout.write('{broken\n');
    return;
  }
  if (mode === 'exit') {
    process.exitCode = 7;
    return;
  }
  const digest = createHash('sha256').update(raw.slice(0, -1)).digest('hex');
  const output = {
    schemaVersion: 1,
    kind: 'agent.prepared',
    inputDigest: mode === 'wrong-digest' ? '0'.repeat(64) : digest,
    decision: {
      kind: 'investigation',
      source: 'scripted',
      caseRevision: mode === 'wrong-revision' ? '999' : input.context.caseRevision,
    },
  };
  if (mode === 'env') {
    if (
      ['PGHOSTADDR', 'P2_RUNTIME_PASSWORD', 'OPENAI_API_KEY', 'NODE_OPTIONS'].some(
        (key) => process.env[key] !== undefined,
      )
    ) {
      process.exitCode = 8;
      return;
    }
  }
  process.stdout.write(JSON.stringify(output) + '\n');
});
