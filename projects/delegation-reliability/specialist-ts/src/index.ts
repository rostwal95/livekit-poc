/** First-capability public contract/trust surface; no HTTP server or scheduler. */
export {
  CAPABILITY,
  ERROR_CODES,
  MAX_REQUEST_BYTES,
  MAX_RESULT_BYTES,
  MAX_TIMESTAMP_MS,
  MAX_DEADLINE_WINDOW_MS,
  ContractError,
  canonical,
  checkReplay,
  encodeError,
  encodeRequest,
  encodeResult,
  logicalFingerprint,
  matchResult,
  parseError,
  parseRequest,
  parseResult,
  produceRequest,
} from './contracts.js';
export type {
  ContextSnapshot,
  DelegationRequest,
  DelegationResult,
  ErrorCode,
  ErrorEnvelope,
  EvidenceRef,
  Producer,
  ResultEvidence,
  Scope,
} from './contracts.js';
export {
  AttemptBoundary,
  EvidenceRegistry,
  LocalTrust,
  tokenDigest,
  verifyPolicyFacts,
} from './security.js';
export type {
  AttemptPermit,
  EvidenceRecord,
  Operation,
  PrincipalGrant,
  ScopeGrant,
} from './security.js';

export {
  SpecialistServer,
  DEFAULT_SPECIALIST_LIMITS,
  SpecialistClient,
  SpecialistHttpError,
} from './http.js';
export type {
  SpecialistLimits,
  SpecialistServerOptions,
  SpecialistHarnessHooks,
  SpecialistEvent,
  SpecialistObserver,
  ClientOptions,
  CallOptions,
  Endpoint,
  AttemptObservation,
  HttpCode,
} from './http.js';

export * from './document.js';
