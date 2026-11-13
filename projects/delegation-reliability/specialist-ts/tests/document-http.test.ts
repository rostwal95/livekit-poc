import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CAPABILITY, produceRequest } from '../src/contracts.js';
import type { EvidenceRef } from '../src/contracts.js';
import {
  DOCUMENT_CAPABILITY,
  DOCUMENT_FIELDS,
  produceDocumentRequest,
} from '../src/document-contracts.js';
import type {
  DocumentField,
  DocumentFieldName,
  DocumentRequest,
} from '../src/document-contracts.js';
import { DocumentHandler, DocumentSpecialistClient } from '../src/document.js';
import type { DocumentExtraction, DocumentExtractionProvider } from '../src/document.js';
import { SpecialistClient } from '../src/client.js';
import { SpecialistServer } from '../src/server.js';
import { EvidenceRegistry, LocalTrust, tokenDigest } from '../src/security.js';
import type { EvidenceRecord } from '../src/security.js';
const directory = new URL('../../../../contracts/delegation/', import.meta.url);
const positive = JSON.parse(readFileSync(new URL('document-v1.json', directory), 'utf8')) as {
  producer_input: Record<string, unknown>;
  result: { producer: DocumentExtractionProvider['producer'] };
};
const policy = JSON.parse(readFileSync(new URL('v1.json', directory), 'utf8')) as {
  producer_input: Record<string, unknown>;
  policy_body: string;
  request: { evidence: EvidenceRef[] };
};
const manifest = JSON.parse(
  readFileSync(new URL('documents/manifest.json', directory), 'utf8'),
) as {
  fixtures: Record<
    string,
    {
      file: string;
      source: EvidenceRef;
      regions: Record<DocumentFieldName, { x: number; y: number; width: number; height: number }[]>;
    }
  >;
};
const primary = { tenant_id: 'tenant_document', account_id: 'account_document' };
const other = { tenant_id: 'tenant_document', account_id: 'account_document_other' };
let sequence = 0;
function request(label = 'complete', account = primary): DocumentRequest {
  const fixture = manifest.fixtures[label]!;
  const n = ++sequence;
  return produceDocumentRequest({
    ...positive.producer_input,
    scope: account,
    delegation_id: 'document_' + n,
    context_snapshot: {
      document_kind: 'booking_confirmation_v1',
      document_source_id: fixture.source.source_id,
      requested_fields: DOCUMENT_FIELDS,
      note: '',
    },
    evidence: [fixture.source],
    deadline_at_ms: Date.now() + 60000,
    attempt: { attempt_id: 'attempt_document_' + n, number: 1 },
  });
}
function extraction(label = 'complete'): DocumentExtraction {
  const fixture = manifest.fixtures[label]!;
  const values: Record<string, readonly (string | null)[]> = {
    complete: ['DEMO-BK-001', 'Harbour Lodge', '2030-12-10', '2030-12-12'],
    missing: ['DEMO-BK-001', 'Harbour Lodge', '2030-12-10', null],
    ambiguous: ['DEMO-BK-001', 'Harbour Lodge', null, '2030-12-12'],
  };
  const result = {} as Record<DocumentFieldName, DocumentField>;
  for (const [i, name] of DOCUMENT_FIELDS.entries()) {
    const value = values[label]![i]!;
    result[name] = {
      state: value !== null ? 'known' : label === 'ambiguous' ? 'ambiguous' : 'missing',
      value,
      evidence_refs: fixture.regions[name].map((region) => ({
        source_id: fixture.source.source_id,
        version: fixture.source.version,
        sha256: fixture.source.sha256,
        region,
      })),
    };
  }
  return { outcome: label === 'complete' ? 'extracted' : 'clarification_required', fields: result };
}
function trust(): LocalTrust {
  return new LocalTrust([
    {
      principal_id: 'primary',
      token_sha256: tokenDigest('A'.repeat(43)),
      scopes: [
        {
          scope: primary,
          invoke_capabilities: [CAPABILITY, DOCUMENT_CAPABILITY],
          result_capabilities: [CAPABILITY, DOCUMENT_CAPABILITY],
          cancel_capabilities: [CAPABILITY, DOCUMENT_CAPABILITY],
          evidence_sources: [
            ...Object.values(manifest.fixtures).map((x) => x.source.source_id),
            policy.request.evidence[0]!.source_id,
          ],
        },
      ],
    },
    {
      principal_id: 'other',
      token_sha256: tokenDigest('B'.repeat(43)),
      scopes: [
        {
          scope: other,
          invoke_capabilities: [DOCUMENT_CAPABILITY],
          result_capabilities: [DOCUMENT_CAPABILITY],
          cancel_capabilities: [DOCUMENT_CAPABILITY],
          evidence_sources: [manifest.fixtures.complete!.source.source_id],
        },
      ],
    },
  ]);
}
function records(): EvidenceRecord[] {
  return [
    ...Object.values(manifest.fixtures).map((f) => ({
      scope: primary,
      reference: f.source,
      body: readFileSync(new URL('documents/' + f.file, directory)),
    })),
    {
      scope: other,
      reference: manifest.fixtures.complete!.source,
      body: readFileSync(new URL('documents/complete.png', directory)),
    },
    {
      scope: primary,
      reference: policy.request.evidence[0]!,
      body: Buffer.from(policy.policy_body),
    },
  ];
}
const provider = (
  extract: DocumentExtractionProvider['extract'] = () => extraction(),
): DocumentExtractionProvider => ({ producer: positive.result.producer, extract });
function deferred() {
  let release!: () => void;
  const promise = new Promise<void>((r) => {
    release = r;
  });
  return { promise, release };
}
async function settled(server: SpecialistServer, handler?: DocumentHandler): Promise<void> {
  await server.close();
  expect(server.metrics().active).toBe(0);
  expect(server.metrics().requests).toBe(0);
  expect(server.metrics().sockets).toBe(0);
  if (handler) expect(handler.metrics().active).toBe(0);
}
describe('actual shared authenticated document HTTP', () => {
  it('returns useful image fields through the public typed client after actual decode', async () => {
    const handler = new DocumentHandler(provider());
    const server = new SpecialistServer({
      trust: trust(),
      evidence: new EvidenceRegistry(records()),
      document: handler,
      observer: () => undefined,
    });
    const client = new DocumentSpecialistClient(await server.listen(), 'Bearer ' + 'A'.repeat(43));
    try {
      const input = request();
      const result = await client.invoke(input);
      expect(result.capability).toBe(DOCUMENT_CAPABILITY);
      expect(result.fields.booking_reference.value).toBe('DEMO-BK-001');
      expect(result.input_fingerprint).toBe(input.input_fingerprint);
      expect('eligible' in result).toBe(false);
      expect(handler.metrics().providerStarted).toBe(1);
      expect(handler.metrics().workersSettled).toBe(1);
    } finally {
      await client.close();
      await settled(server, handler);
    }
  });
  it('preserves default policy HTTP behavior without enabling document work', async () => {
    const server = new SpecialistServer({
      trust: trust(),
      evidence: new EvidenceRegistry(records()),
      observer: () => undefined,
    });
    const endpoint = await server.listen(),
      image = new DocumentSpecialistClient(endpoint, 'Bearer ' + 'A'.repeat(43)),
      client = new SpecialistClient(endpoint, 'Bearer ' + 'A'.repeat(43));
    try {
      await expect(image.invoke(request())).rejects.toMatchObject({ code: 'unknown_capability' });
      const accepted = produceRequest({
        ...policy.producer_input,
        scope: primary,
        deadline_at_ms: Date.now() + 60000,
      });
      expect((await client.invoke(accepted)).capability).toBe(CAPABILITY);
    } finally {
      await image.close();
      await client.close();
      await settled(server);
    }
  });
  it.each(['missing', 'ambiguous'])(
    'returns explicit %s clarification rather than filling values',
    async (label) => {
      const handler = new DocumentHandler(provider(() => extraction(label)));
      const server = new SpecialistServer({
        trust: trust(),
        evidence: new EvidenceRegistry(records()),
        document: handler,
        observer: () => undefined,
      });
      const client = new DocumentSpecialistClient(
        await server.listen(),
        'Bearer ' + 'A'.repeat(43),
      );
      try {
        const result = await client.invoke(request(label));
        expect(result.outcome).toBe('clarification_required');
        expect(
          label === 'missing' ? result.fields.check_out.state : result.fields.check_in.state,
        ).toBe(label);
      } finally {
        await client.close();
        await settled(server, handler);
      }
    },
  );
  it('rejects foreign scope before decode/provider', async () => {
    const handler = new DocumentHandler(provider());
    const server = new SpecialistServer({
      trust: trust(),
      evidence: new EvidenceRegistry(records()),
      document: handler,
      observer: () => undefined,
    });
    const client = new DocumentSpecialistClient(await server.listen(), 'Bearer ' + 'A'.repeat(43));
    try {
      await expect(client.invoke(request('complete', other))).rejects.toMatchObject({
        code: 'unauthorized',
      });
      expect(handler.metrics().providerStarted).toBe(0);
      expect(handler.metrics().workersStarted).toBe(0);
    } finally {
      await client.close();
      await settled(server, handler);
    }
  });
  it('rejects malformed provider result without exposing it as valid', async () => {
    const handler = new DocumentHandler(provider(() => ({ ...extraction(), eligible: true })));
    const server = new SpecialistServer({
      trust: trust(),
      evidence: new EvidenceRegistry(records()),
      document: handler,
      observer: () => undefined,
    });
    const client = new DocumentSpecialistClient(await server.listen(), 'Bearer ' + 'A'.repeat(43));
    try {
      await expect(client.invoke(request())).rejects.toMatchObject({ code: 'invalid_contract' });
      expect(handler.metrics().providerStarted).toBe(1);
    } finally {
      await client.close();
      await settled(server, handler);
    }
  });
  it('uses actual PNG dimensions rather than trusting registry metadata', async () => {
    const input = request();
    const ref = { ...input.evidence[0]!, width: 1 };
    const { input_fingerprint: _ignored, ...wire } = input;
    const forged = produceDocumentRequest({ ...wire, evidence: [ref] });
    const sources = records().map((r) =>
      r.scope.account_id === primary.account_id && r.reference.source_id === ref.source_id
        ? { ...r, reference: ref }
        : r,
    );
    const handler = new DocumentHandler(provider());
    const server = new SpecialistServer({
      trust: trust(),
      evidence: new EvidenceRegistry(sources),
      document: handler,
      observer: () => undefined,
    });
    const client = new DocumentSpecialistClient(await server.listen(), 'Bearer ' + 'A'.repeat(43));
    try {
      await expect(client.invoke(forged)).rejects.toMatchObject({ code: 'evidence_mismatch' });
      expect(handler.metrics().workersStarted).toBe(0);
      expect(handler.metrics().providerStarted).toBe(0);
    } finally {
      await client.close();
      await settled(server, handler);
    }
  });
  it('freshly rejects actual deadline expiry after worker exit before provider', async () => {
    const arrived = deferred(),
      release = deferred();
    const handler = new DocumentHandler(provider());
    const server = new SpecialistServer({
      trust: trust(),
      evidence: new EvidenceRegistry(records()),
      document: handler,
      observer: () => undefined,
      hooks: {
        afterDocumentDecode: async () => {
          arrived.release();
          await release.promise;
        },
      },
    });
    const client = new DocumentSpecialistClient(await server.listen(), 'Bearer ' + 'A'.repeat(43));
    const initial = request();
    const { input_fingerprint: _ignored, ...wire } = initial;
    const input = produceDocumentRequest({ ...wire, deadline_at_ms: Date.now() + 1000 });
    try {
      const pending = client.invoke(input);
      void pending.catch(() => undefined);
      await arrived.promise;
      expect(handler.metrics().workersSettled).toBe(1);
      while (Date.now() < input.deadline_at_ms)
        await new Promise((r) => setTimeout(r, Math.min(20, input.deadline_at_ms - Date.now())));
      release.release();
      await expect(pending).rejects.toMatchObject({ code: 'deadline_exceeded' });
      expect(handler.metrics().providerStarted).toBe(0);
    } finally {
      release.release();
      await client.close();
      await settled(server, handler);
    }
  }, 5000);
  it('retains ignoring provider after cancel and supports explicit close retry', async () => {
    const arrived = deferred(),
      release = deferred();
    const handler = new DocumentHandler(
      provider(async () => {
        arrived.release();
        await release.promise;
        return extraction();
      }),
    );
    const server = new SpecialistServer({
      trust: trust(),
      evidence: new EvidenceRegistry(records()),
      document: handler,
      observer: () => undefined,
      limits: { closeMs: 50 },
    });
    const client = new DocumentSpecialistClient(await server.listen(), 'Bearer ' + 'A'.repeat(43));
    try {
      const input = request(),
        pending = client.invoke(input);
      void pending.catch(() => undefined);
      await arrived.promise;
      expect((await client.status(input)).durable).toBe(false);
      expect((await client.cancel(input)).cancel_requested).toBe(true);
      await expect(pending).rejects.toMatchObject({ code: 'request_aborted' });
      expect(handler.metrics().providerActive).toBe(1);
      expect(server.metrics().active).toBe(1);
      await expect(server.close()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
      expect(handler.metrics().providerActive).toBe(1);
      release.release();
      await server.close();
      expect(handler.metrics().providerActive).toBe(0);
    } finally {
      release.release();
      await client.close();
      await settled(server, handler);
    }
  }, 5000);
  it('holds same-principal capacity while another verified account progresses', async () => {
    const arrived = deferred(),
      release = deferred();
    const handler = new DocumentHandler(
      provider(async (input) => {
        if (input.scope.account_id === primary.account_id) {
          arrived.release();
          await release.promise;
        }
        return extraction();
      }),
    );
    const server = new SpecialistServer({
      trust: trust(),
      evidence: new EvidenceRegistry(records()),
      document: handler,
      observer: () => undefined,
      limits: { maxActive: 2, maxPerPrincipal: 1 },
    });
    const endpoint = await server.listen(),
      a = new DocumentSpecialistClient(endpoint, 'Bearer ' + 'A'.repeat(43)),
      b = new DocumentSpecialistClient(endpoint, 'Bearer ' + 'B'.repeat(43));
    try {
      const pending = a.invoke(request());
      void pending.catch(() => undefined);
      await arrived.promise;
      await expect(a.invoke(request())).rejects.toMatchObject({ code: 'capacity' });
      expect((await b.invoke(request('complete', other))).scope.account_id).toBe(other.account_id);
      expect(handler.metrics().providerActive).toBe(1);
      release.release();
      await pending;
    } finally {
      release.release();
      await a.close();
      await b.close();
      await settled(server, handler);
    }
  }, 5000);
});
