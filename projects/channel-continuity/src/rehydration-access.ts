/** Package-internal capability; never exported by the public package manifest. */
import type { PoolClient } from 'pg';
import type { ChannelInbox } from './postgres.js';
import type { NativeStore } from './native-store.js';
import type { CommunicationStore } from './communication-store.js';
import type { ChannelLimits } from './public-types.js';
export type RehydrationTx = Readonly<{
  client: PoolClient;
  now: Date;
  bounds: ChannelLimits;
  guard: Record<string, number>;
  onCommit: (action: () => void) => void;
}>;
export type RehydrationInboxAccess = Readonly<{
  schema: string;
  databaseIdentity: string;
  native: NativeStore;
  communication: CommunicationStore;
  transaction: <T>(
    protectedCheck: boolean,
    action: (tx: RehydrationTx) => Promise<T>,
  ) => Promise<T>;
}>;
const registry = new WeakMap<object, RehydrationInboxAccess>();
export function registerRehydrationInbox(
  inbox: ChannelInbox,
  access: RehydrationInboxAccess,
): void {
  registry.set(inbox, access);
}
export function rehydrationInbox(inbox: object): RehydrationInboxAccess | undefined {
  return registry.get(inbox);
}

export function registerRehydrationProxy(owner: object, inbox: ChannelInbox): void {
  const access = registry.get(inbox);
  if (access) registry.set(owner, access);
}
