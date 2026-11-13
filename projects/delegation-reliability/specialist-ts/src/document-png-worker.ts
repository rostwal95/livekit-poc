/** Fixed dependency-free worker for the declared static RGB(A) PNG subset only. */
import { createHash } from 'node:crypto';
import { parentPort, workerData } from 'node:worker_threads';
import { inflateSync } from 'node:zlib';

type SafeCode = 'invalid_contract' | 'evidence_mismatch' | 'unsupported_facts';
class PngError extends Error {
  constructor(readonly code: SafeCode) {
    super(code);
  }
}
const fail = (code: SafeCode = 'evidence_mismatch'): never => {
  throw new PngError(code);
};
const sha = (body: Uint8Array): string => createHash('sha256').update(body).digest('hex');
const table = new Uint32Array(256);
for (let n = 0; n < 256; n++) {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  table[n] = c >>> 0;
}
function crc(bytes: Uint8Array, start: number, end: number): number {
  let c = 0xffffffff;
  for (let i = start; i < end; i++) c = table[(c ^ bytes[i]!) & 255]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function paeth(a: number, b: number, c: number): number {
  const p = a + b - c,
    pa = Math.abs(p - a),
    pb = Math.abs(p - b),
    pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}
function run(): Record<string, unknown> {
  const input: unknown = workerData;
  if (input === null || typeof input !== 'object' || Array.isArray(input)) fail('invalid_contract');
  const data = input as { bytes?: unknown; width?: unknown; height?: unknown; sha256?: unknown };
  if (
    !(data.bytes instanceof Uint8Array) ||
    data.bytes.byteLength < 45 ||
    data.bytes.byteLength > 2097152
  )
    fail('invalid_contract');
  const bytes = Buffer.from(data.bytes as Uint8Array);
  if (typeof data.sha256 !== 'string' || sha(bytes) !== data.sha256) fail();
  if (!bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) fail();
  let offset = 8,
    count = 0,
    width = 0,
    height = 0,
    channels = 0,
    ended = false;
  const compressed: Buffer[] = [];
  while (offset < bytes.length) {
    if (++count > 128) fail('invalid_contract');
    if (bytes.length - offset < 12) fail();
    const length = bytes.readUInt32BE(offset);
    if (length > 0x7fffffff || length > bytes.length - offset - 12) fail();
    const type = bytes.subarray(offset + 4, offset + 8).toString('latin1');
    const end = offset + 8 + length;
    if (crc(bytes, offset + 4, end) !== bytes.readUInt32BE(end)) fail();
    if (count === 1) {
      if (type !== 'IHDR' || length !== 13) fail();
      width = bytes.readUInt32BE(offset + 8);
      height = bytes.readUInt32BE(offset + 12);
      if (width < 1 || height < 1 || width > 2048 || height > 2048 || width * height > 4194304)
        fail('invalid_contract');
      if (width !== data.width || height !== data.height) fail();
      if (
        bytes[offset + 16] !== 8 ||
        ![2, 6].includes(bytes[offset + 17]!) ||
        bytes[offset + 18] !== 0 ||
        bytes[offset + 19] !== 0 ||
        bytes[offset + 20] !== 0
      )
        fail('unsupported_facts');
      channels = bytes[offset + 17] === 2 ? 3 : 4;
    } else if (type === 'IDAT' && !ended) {
      compressed.push(bytes.subarray(offset + 8, end));
    } else if (type === 'IEND') {
      if (length !== 0 || compressed.length === 0 || end + 4 !== bytes.length) fail();
      ended = true;
    } else fail('unsupported_facts');
    offset = end + 4;
  }
  if (!ended || offset !== bytes.length || compressed.length === 0) fail();
  const stride = width * channels,
    expected = (stride + 1) * height;
  if (expected > 16779264) fail('invalid_contract');
  const source = Buffer.concat(compressed);
  let inflated: { buffer: Buffer; engine: { bytesWritten: number } };
  try {
    inflated = inflateSync(source, {
      maxOutputLength: expected,
      info: true,
    }) as unknown as typeof inflated;
  } catch {
    throw new PngError('evidence_mismatch');
  }
  if (
    !Buffer.isBuffer(inflated.buffer) ||
    inflated.buffer.length !== expected ||
    inflated.engine.bytesWritten !== source.length
  )
    fail();
  const filtered = inflated.buffer,
    pixels = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y++) {
    const rawRow = y * (stride + 1),
      filter = filtered[rawRow]!;
    if (filter > 4) fail();
    for (let x = 0; x < stride; x++) {
      const position = y * stride + x;
      const a = x >= channels ? pixels[position - channels]! : 0;
      const b = y > 0 ? pixels[position - stride]! : 0;
      const c = y > 0 && x >= channels ? pixels[position - stride - channels]! : 0;
      const predictor =
        filter === 0
          ? 0
          : filter === 1
            ? a
            : filter === 2
              ? b
              : filter === 3
                ? Math.floor((a + b) / 2)
                : paeth(a, b, c);
      pixels[position] = (filtered[rawRow + 1 + x]! + predictor) & 255;
    }
  }
  return {
    status: 'known',
    width,
    height,
    channels,
    pixel_sha256: sha(pixels),
    png_sha256: data.sha256,
  };
}
if (parentPort === null) throw new Error('worker_only');
try {
  parentPort.postMessage(run());
} catch (error) {
  parentPort.postMessage({
    status: 'failed',
    code: error instanceof PngError ? error.code : 'evidence_mismatch',
  });
} finally {
  parentPort.close();
}
