/** Explicit configured read-only consumer. Import opens no files/listeners/workers. */
import { pathToFileURL } from 'node:url';
import { ContractError } from '@livekit-ecosystem/delegation-specialist';
import {
  DOCUMENT_CAPABILITY,
  encodeDocumentRequest,
  encodeDocumentResult,
  parseDocumentRequest,
  parseDocumentResult,
  matchDocumentResult,
} from '@livekit-ecosystem/delegation-specialist/document';
/**
 * @param {{invoke(request: import('@livekit-ecosystem/delegation-specialist/document').DocumentRequest): Promise<import('@livekit-ecosystem/delegation-specialist/document').DocumentResult>}} client
 * @param {import('@livekit-ecosystem/delegation-specialist/document').DocumentRequest} request
 */
export async function extractDocument(client, request) {
  const snapshot = parseDocumentRequest(encodeDocumentRequest(request));
  const observed = await client.invoke(snapshot);
  const result = parseDocumentResult(encodeDocumentResult(observed));
  if (matchDocumentResult(snapshot, result, Date.now()) !== 'candidate')
    throw new ContractError('expired');
  return result;
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(
    JSON.stringify({ status: 'configuration_required', capability: DOCUMENT_CAPABILITY }),
  );
}
