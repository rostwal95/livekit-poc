import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { deflateSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { ContractError } from '../src/contracts.js';
import { DocumentPngDecoder } from '../src/document-png.js';
import type { DocumentWorkerObservation } from '../src/document-png.js';
import type { EvidenceRecord } from '../src/security.js';
const directory = new URL('../../../../contracts/delegation/documents/', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('manifest.json', directory), 'utf8')) as {
  fixtures: Record<
    string,
    { file: string; source: EvidenceRecord['reference']; pixel_sha256: string; channels: number }
  >;
};
const scope = { tenant_id: 'tenant_document', account_id: 'account_document' };
const sha = (b: Uint8Array) => createHash('sha256').update(b).digest('hex');
function source(label = 'complete'): EvidenceRecord {
  const f = manifest.fixtures[label]!;
  return { scope, reference: { ...f.source }, body: readFileSync(new URL(f.file, directory)) };
}
function changed(body: Uint8Array, width = 640, height = 360): EvidenceRecord {
  return {
    scope,
    reference: {
      source_id: 'test_image',
      version: 'document_v1',
      media_type: 'image/png',
      byte_length: body.byteLength,
      width,
      height,
      sha256: sha(body),
    },
    body,
  };
}
const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
function crc(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (const b of bytes) {
    c ^= b;
    for (let i = 0; i < 8; i++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1;
  }
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type: string, body: Uint8Array): Buffer {
  const out = Buffer.alloc(body.length + 12);
  out.writeUInt32BE(body.length, 0);
  out.write(type, 4, 'ascii');
  out.set(body, 8);
  out.writeUInt32BE(crc(out.subarray(4, -4)), out.length - 4);
  return out;
}
function png(
  raw: Uint8Array,
  options: {
    width?: number;
    height?: number;
    color?: number;
    extra?: Buffer;
    compressed?: Uint8Array;
  } = {},
): Buffer {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(options.width ?? 1, 0);
  header.writeUInt32BE(options.height ?? 1, 4);
  header[8] = 8;
  header[9] = options.color ?? 2;
  return Buffer.concat([
    signature,
    chunk('IHDR', header),
    ...(options.extra ? [options.extra] : []),
    chunk('IDAT', options.compressed ?? deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}
async function rejected(record: EvidenceRecord, code = 'evidence_mismatch'): Promise<void> {
  const decoder = new DocumentPngDecoder();
  try {
    await expect(
      decoder.decode(record, new AbortController().signal, performance.now() + 5000),
    ).rejects.toMatchObject({ code });
    expect(decoder.metrics().workersActive).toBe(0);
  } finally {
    await decoder.close();
  }
}
describe('actual bounded static PNG worker', () => {
  it('decodes all five actual fixtures and exposes normal results only after exit0', async () => {
    const seen: DocumentWorkerObservation[] = [];
    const decoder = new DocumentPngDecoder((v) => {
      seen.push(v);
    });
    try {
      for (const [label, f] of Object.entries(manifest.fixtures)) {
        const image = await decoder.decode(
          source(label),
          new AbortController().signal,
          performance.now() + 5000,
        );
        expect(image.pixel_sha256).toBe(f.pixel_sha256);
        expect(image.channels).toBe(f.channels);
        expect(decoder.metrics().workersActive).toBe(0);
      }
      expect(seen).toHaveLength(5);
      expect(seen.every((x) => x.exit_code === 0 && x.normal_result && x.thread_id > 0)).toBe(true);
    } finally {
      await decoder.close();
    }
  });
  it('rejects forged actual dimensions without starting a worker', async () => {
    const value = source();
    const decoder = new DocumentPngDecoder();
    try {
      await expect(
        decoder.decode(
          { ...value, reference: { ...value.reference, width: 1 } },
          new AbortController().signal,
          performance.now() + 5000,
        ),
      ).rejects.toMatchObject({ code: 'evidence_mismatch' });
      expect(decoder.metrics().workersStarted).toBe(0);
    } finally {
      await decoder.close();
    }
  });
  it('rejects excessive actual dimensions before worker/decompression', async () => {
    const body = png(Buffer.from([0, 1, 2, 3]), { width: 2049 });
    const decoder = new DocumentPngDecoder();
    try {
      await expect(
        decoder.decode(
          changed(body, 2049, 1),
          new AbortController().signal,
          performance.now() + 5000,
        ),
      ).rejects.toBeInstanceOf(ContractError);
      expect(decoder.metrics().workersStarted).toBe(0);
    } finally {
      await decoder.close();
    }
  });
  it('rejects CRC-correct high-bit chunk types instead of ASCII-masking them', async () => {
    const header = png(Buffer.from([0, 1, 2, 3]));
    header[12] = header[12]! | 0x80;
    header.writeUInt32BE(crc(header.subarray(12, 29)), 29);
    await rejected(changed(header, 1, 1));
    const idat = png(Buffer.from([0, 1, 2, 3]));
    const length = idat.readUInt32BE(33);
    idat[37] = idat[37]! | 0x80;
    idat.writeUInt32BE(crc(idat.subarray(37, 41 + length)), 41 + length);
    await rejected(changed(idat, 1, 1), 'unsupported_facts');
  });
  it('rejects corrupt CRC even with a newly matched source digest', async () => {
    const b = Buffer.from(source().body);
    b[b.length - 1] = b[b.length - 1]! ^ 1;
    await rejected(changed(b));
  });
  it('rejects truncated final chunk and trailing file bytes', async () => {
    const b = Buffer.from(source().body);
    await rejected(changed(b.subarray(0, -1)));
    await rejected(changed(Buffer.concat([b, Buffer.from([0])])));
  });
  it('rejects APNG and ancillary instruction chunks as unsupported forms', async () => {
    await rejected(
      changed(png(Buffer.from([0, 1, 2, 3]), { extra: chunk('acTL', Buffer.alloc(8)) }), 1, 1),
      'unsupported_facts',
    );
    await rejected(
      changed(
        png(Buffer.from([0, 1, 2, 3]), {
          extra: chunk('tEXt', Buffer.from('tool\0call_supplier')),
        }),
        1,
        1,
      ),
      'unsupported_facts',
    );
  });
  it('rejects unsupported grayscale instead of advertising full PNG support', async () => {
    await rejected(changed(png(Buffer.from([0, 1]), { color: 0 }), 1, 1), 'unsupported_facts');
  });
  it('caps expansion before allocating an unbounded decoded image', async () => {
    const body = png(Buffer.alloc(0), { compressed: deflateSync(Buffer.alloc(1048576)) });
    await rejected(changed(body, 1, 1));
  });
  it('rejects compressed trailing input even when the inflated rows are correct', async () => {
    const body = png(Buffer.alloc(0), {
      compressed: Buffer.concat([deflateSync(Buffer.from([0, 1, 2, 3])), Buffer.from([1, 2, 3])]),
    });
    await rejected(changed(body, 1, 1));
  });
  it('rejects illegal filter byte and extra decompressed rows', async () => {
    await rejected(changed(png(Buffer.from([5, 1, 2, 3])), 1, 1));
    await rejected(changed(png(Buffer.from([0, 1, 2, 3, 0])), 1, 1));
  });
  it('supports actual RGBA rows without RGB conversion or padding', async () => {
    const pixels = Buffer.from([10, 20, 30, 40, 50, 60, 70, 80]);
    const decoder = new DocumentPngDecoder();
    try {
      const result = await decoder.decode(
        changed(png(Buffer.concat([Buffer.from([0]), pixels]), { width: 2, color: 6 }), 2, 1),
        new AbortController().signal,
        performance.now() + 5000,
      );
      expect(result.channels).toBe(4);
      expect(result.pixel_sha256).toBe(sha(pixels));
    } finally {
      await decoder.close();
    }
  });
  it('retains a started worker after abort until actual exit is observed', async () => {
    const controller = new AbortController();
    const seen: DocumentWorkerObservation[] = [];
    const decoder = new DocumentPngDecoder((v) => {
      seen.push(v);
    });
    const result = decoder.decode(source(), controller.signal, performance.now() + 5000);
    controller.abort();
    expect(decoder.metrics().workersActive).toBe(1);
    await expect(result).rejects.toMatchObject({ code: 'request_aborted' });
    expect(decoder.metrics().workersActive).toBe(0);
    expect(seen).toHaveLength(1);
    expect(seen[0]!.normal_result).toBe(false);
    await decoder.close();
  });
  it('owns copied input bytes/reference across actual worker awaits', async () => {
    const value = source();
    const expected = value.reference.sha256;
    const decoder = new DocumentPngDecoder();
    const work = decoder.decode(value, new AbortController().signal, performance.now() + 5000);
    (value.body as Uint8Array).fill(0);
    Object.assign(value.reference, { width: 1, sha256: '0'.repeat(64) });
    try {
      const image = await work;
      expect(image.reference.width).toBe(640);
      expect(image.reference.sha256).toBe(expected);
    } finally {
      await decoder.close();
    }
  });
  it('rejects encoded oversize before copying or starting a worker', async () => {
    const body = new Uint8Array(2097153);
    const decoder = new DocumentPngDecoder();
    try {
      await expect(
        decoder.decode(changed(body), new AbortController().signal, performance.now() + 5000),
      ).rejects.toMatchObject({ code: 'evidence_mismatch' });
      expect(decoder.metrics().workersStarted).toBe(0);
    } finally {
      await decoder.close();
    }
  });
  it('reports incomplete held observer cleanup then observes the same late settlement', async () => {
    let release!: () => void;
    const held = new Promise<void>((r) => {
      release = r;
    });
    const decoder = new DocumentPngDecoder(() => held);
    await decoder.decode(source(), new AbortController().signal, performance.now() + 5000);
    expect(decoder.metrics().workerObserverPending).toBe(1);
    await expect(decoder.close()).rejects.toMatchObject({ code: 'cleanup_incomplete' });
    release();
    await decoder.close();
    expect(decoder.metrics().workerObserverPending).toBe(0);
  }, 5000);
  it('contains a throwing observer without reversing known pixel truth', async () => {
    const decoder = new DocumentPngDecoder(() => {
      throw Error('private sentinel');
    });
    try {
      const image = await decoder.decode(
        source(),
        new AbortController().signal,
        performance.now() + 5000,
      );
      expect(image.pixel_sha256).toBe(manifest.fixtures.complete!.pixel_sha256);
      expect(decoder.metrics().observerFailures).toBe(1);
    } finally {
      await decoder.close();
    }
  });
  it('fails closed when source bytes differ from the immutable reference', async () => {
    const value = source();
    const decoder = new DocumentPngDecoder();
    try {
      await expect(
        decoder.decode(
          { ...value, body: Uint8Array.from(value.body).fill(0) },
          new AbortController().signal,
          performance.now() + 5000,
        ),
      ).rejects.toMatchObject({ code: 'evidence_mismatch' });
      expect(decoder.metrics().workersStarted).toBe(0);
    } finally {
      await decoder.close();
    }
  });
});
