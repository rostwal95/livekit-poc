/** Explicit bounded local HTTP example surface; importing starts no service. */
export { SpecialistServer, DEFAULT_SPECIALIST_LIMITS } from './server.js';
export type {
  SpecialistLimits,
  SpecialistServerOptions,
  SpecialistHarnessHooks,
  SpecialistEvent,
  SpecialistObserver,
} from './server.js';
export { SpecialistClient } from './client.js';
export type { ClientOptions, CallOptions, SpecialistClientMetrics } from './client.js';
export { SpecialistHttpError } from './http-protocol.js';
export type { Endpoint, AttemptObservation, HttpCode } from './http-protocol.js';
