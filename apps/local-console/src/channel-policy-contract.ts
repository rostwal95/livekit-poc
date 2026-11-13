/** Normalized application observations, NOT the unfrozen Parent HTTP wire. */
import type { NativeMode, NativeSession, FrozenNativeInput, TurnMethod } from './p2-native-policy';
export type UiCode =
  'invalid' | 'denied' | 'conflict' | 'capacity' | 'unavailable' | 'unknown' | 'cleanup_incomplete';
export class JoinedUiError extends Error {
  constructor(readonly code: UiCode) {
    super(code);
  }
}
export interface ParentCursor {
  readonly ownerEpoch: string;
  readonly generation: string;
}
export interface StartIntent {
  readonly ownerEpoch: string;
  readonly expectedGeneration: string;
  readonly commandId: string;
}
export interface ParentObservation {
  readonly cursor: ParentCursor;
  readonly stage: 'dormant' | 'starting' | 'active' | 'ending' | 'cleanup_incomplete';
  readonly originalStartCommandId: string | null;
  readonly workerReady: boolean;
}
export interface BrowserGrant {
  readonly session: NativeSession;
  readonly expiresAt: string;
  readonly mode: NativeMode;
}
export interface StartObservation {
  readonly cursor: ParentCursor;
  readonly originalStartCommandId: string;
  readonly workerReady: boolean;
  readonly grant: BrowserGrant;
}
/** Adapter must resolve the original Start; this is not a guessed raw End DTO. */
export interface RetireIntent {
  readonly originalStart: StartIntent;
  readonly observedCursor: ParentCursor | null;
}
export interface EndObservation {
  readonly cursor: ParentCursor;
  readonly originalStartCommandId: string;
  readonly settled: boolean;
}
export interface SmsIntent {
  readonly commandId: string;
  readonly body: string;
  readonly occurredAt: string;
}
export interface SmsObservation {
  readonly commandId: string;
  readonly status: 'accepted' | 'replayed';
  readonly observedAt: string;
}
export interface CaseSummary {
  readonly revision: string;
  readonly observedAt: string;
}
export type PolicySummary =
  | Readonly<{
      state: 'current';
      eligible: boolean | null;
      uncertainty: 'none' | 'missing' | 'conflicting';
      revision: string;
      asOf: string;
    }>
  | Readonly<{
      state: 'no_delivery' | 'not_applicable';
      eligible: null;
      uncertainty: null;
      revision: null;
      asOf: string;
    }>
  | Readonly<{
      state: 'unavailable';
      eligible: null;
      uncertainty: null;
      revision: null;
      asOf: null;
    }>;
export interface CaseResultObservation {
  readonly case: CaseSummary | null;
  readonly policy: PolicySummary;
}
export interface JoinedTransport {
  observe(authorization: string, signal: AbortSignal): Promise<ParentObservation>;
  start(intent: StartIntent, authorization: string, signal: AbortSignal): Promise<StartObservation>;
  retire(intent: RetireIntent, authorization: string, signal: AbortSignal): Promise<EndObservation>;
  read(authorization: string, signal: AbortSignal): Promise<CaseResultObservation>;
  sms(intent: SmsIntent, authorization: string, signal: AbortSignal): Promise<SmsObservation>;
  close(): Promise<void>;
}
/** Construction must be inert; close includes late connect/publish/reader owners. */
export interface JoinedRoomPort {
  connect(signal: AbortSignal): Promise<void>;
  sendText(input: FrozenNativeInput): Promise<void>;
  turn(method: TurnMethod, inputId: string | null): Promise<string>;
  enableAudio(): Promise<void>;
  close(): Promise<void>;
}
