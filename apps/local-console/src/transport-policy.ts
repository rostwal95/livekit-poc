/** Validation for the existing local diagnostic protocol, without UI or room state. */
import { ParticipantKind } from 'livekit-client';
import { MAX_REPLY_BYTES, MAX_TEXT_BYTES } from './lab';
import type { LabState } from './lab';

const encoder = new TextEncoder();
const TRACK_SID = /^TR_[A-Za-z0-9_-]{1,128}$/;

export interface AgentSender {
  readonly identity: string;
  readonly kind: ParticipantKind;
}

/** A peer-provided display name or topic never establishes agent authority. */
export function isAgentSender(sender: AgentSender | undefined): boolean {
  return sender !== undefined && sender.kind === ParticipantKind.AGENT
    && typeof sender.identity === 'string' && sender.identity.length > 0
    && sender.identity.length <= 256;
}

function boundedText(text: string, maximum = MAX_TEXT_BYTES): boolean {
  return text.length > 0 && encoder.encode(text).byteLength <= maximum;
}

export function acceptAgentText(text: string, sender: AgentSender | undefined): string | null {
  return isAgentSender(sender) && boundedText(text, MAX_REPLY_BYTES) ? text : null;
}

/** Return only an allowlisted human-readable observation, never arbitrary metadata. */
export function parseAudioDiagnostic(
  text: string,
  sender: AgentSender | undefined,
  expectedTrackSid?: string,
): string | null {
  if (!isAgentSender(sender) || !boundedText(text)) return null;
  let value: unknown;
  try { value = JSON.parse(text); } catch { return null; }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const keys = Object.keys(value);
  if (keys.length !== 3 || !keys.every((key) => ['type', 'frames', 'track_sid'].includes(key))) return null;
  if (!('type' in value) || value.type !== 'audio.frames'
      || !('frames' in value) || typeof value.frames !== 'number'
      || !Number.isSafeInteger(value.frames) || value.frames < 0
      || !('track_sid' in value) || typeof value.track_sid !== 'string'
      || !TRACK_SID.test(value.track_sid)) return null;
  if (expectedTrackSid !== undefined && value.track_sid !== expectedTrackSid) return null;
  return `Agent received ${value.frames} audio frames.`;
}

/** Room connectivity alone does not establish that the diagnostic agent has joined. */
export function canUseAgentMedia(state: LabState, agentPresent: boolean): boolean {
  return state === 'connected' && agentPresent;
}

/** Stopping an already-published microphone remains available if the agent leaves. */
export function canControlMicrophone(state: LabState, agentPresent: boolean, publishing: boolean): boolean {
  return state === 'connected' && (agentPresent || publishing);
}
