/** Public server values contain no driver-specific type dependency. */
export type DatabaseSettings = Readonly<{
  host: string;
  port: number;
  database: string;
  user: string;
  password: string;
  schema: string;
}>;
export type ChannelLimits = Readonly<{
  maxInbox: number;
  maxChallenges: number;
  maxAssociations: number;
  maxSenders: number;
}>;
export const DEFAULT_LIMITS: ChannelLimits = Object.freeze({
  maxInbox: 1000,
  maxChallenges: 512,
  maxAssociations: 256,
  maxSenders: 128,
});
export type ChannelErrorCode =
  | 'InvalidConfiguration'
  | 'InvalidEvent'
  | 'AccessDenied'
  | 'AssociationRequired'
  | 'AssociationRejected'
  | 'IdentityConflict'
  | 'Overloaded'
  | 'NotFound'
  | 'StorageUnavailable'
  | 'AcknowledgementUnknown'
  | 'SchemaMismatch'
  | 'CleanupIncomplete'
  | 'UpgradeRequired'
  | 'DispatchClaimLost'
  | 'DispatchUnavailable'
  | 'OperationConflict';
export class ChannelError extends Error {
  constructor(readonly code: ChannelErrorCode) {
    super(code);
    this.name = 'ChannelError';
  }
}

export const PROCESSING_STATES = [
  'pending',
  'running',
  'dispatched',
  'blocked',
  'exhausted',
  'uncertain',
] as const;
export type ProcessingState = (typeof PROCESSING_STATES)[number];
