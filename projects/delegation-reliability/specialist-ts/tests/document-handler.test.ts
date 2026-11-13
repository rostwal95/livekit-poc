import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { DocumentHandler, produceDocumentRequest } from '../src/document.js';
import type { DocumentRequest } from '../src/document.js';
import type { Producer } from '../src/contracts.js';
import type { DocumentExtraction } from '../src/document.js';
import type { EvidenceRecord } from '../src/security.js';

const fixture = JSON.parse(
  readFileSync(
    new URL('../../../../contracts/delegation/document-v1.json', import.meta.url),
    'utf8',
  ),
);
const image = readFileSync(
  new URL('../../../../contracts/delegation/documents/complete.png', import.meta.url),
);
function latch(): { promise: Promise<void>; release: () => void } {
  let release!: () => void;
  const promise = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

describe('direct document handler resource ownership', () => {
  it('caps four decoded held provider calls before a fifth worker, then progresses', async () => {
    const gate = latch();
    const arrivals = Array.from({ length: 4 }, () => latch());
    let calls = 0;
    const handler = new DocumentHandler({
      producer: fixture.result.producer as Producer,
      extract: async (): Promise<DocumentExtraction> => {
        const index = calls++;
        arrivals[index]?.release();
        await gate.promise;
        return { outcome: fixture.result.outcome, fields: fixture.result.fields };
      },
    });
    const request = (number: number): DocumentRequest => {
      const value = structuredClone(fixture.producer_input);
      value.deadline_at_ms = Date.now() + 60000;
      value.delegation_id = 'direct_document_' + number;
      value.attempt.attempt_id = 'direct_attempt_' + number;
      return produceDocumentRequest(value);
    };
    const record: EvidenceRecord = {
      scope: fixture.request.scope,
      reference: fixture.request.evidence[0],
      body: image,
    };
    const pending = [];
    try {
      for (let index = 0; index < 4; index++) {
        pending.push(
          handler.evaluate(
            request(index),
            record,
            new AbortController().signal,
            performance.now() + 10000,
          ),
        );
        await arrivals[index]!.promise;
        expect(handler.metrics().workersActive).toBe(0);
      }
      expect(handler.metrics()).toMatchObject({ active: 4, providerActive: 4, workersStarted: 4 });
      await expect(
        handler.evaluate(
          request(4),
          record,
          new AbortController().signal,
          performance.now() + 10000,
        ),
      ).rejects.toMatchObject({ code: 'capacity' });
      expect(calls).toBe(4);
      expect(handler.metrics()).toMatchObject({ active: 4, providerActive: 4, workersStarted: 4 });
      gate.release();
      expect((await Promise.all(pending)).every((result) => result.outcome === 'extracted')).toBe(
        true,
      );
      expect(handler.metrics()).toMatchObject({ active: 0, providerActive: 0 });
      const useful = await handler.evaluate(
        request(5),
        record,
        new AbortController().signal,
        performance.now() + 10000,
      );
      expect(useful.fields.booking_reference.value).toBe('DEMO-BK-001');
      expect(calls).toBe(5);
      expect(handler.metrics().workersStarted).toBe(5);
    } finally {
      gate.release();
      await Promise.allSettled(pending);
      await handler.close();
    }
    expect(handler.metrics()).toMatchObject({ active: 0, providerActive: 0, workersActive: 0 });
  });
});
