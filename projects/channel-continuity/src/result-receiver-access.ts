/** Package-private sharing of the existing outbox owner; not a package export. */
import type { ChannelOutbox } from './outbox.js';
import type { OutboxStore } from './outbox-store.js';
const stores = new WeakMap<object, OutboxStore>();
export function registerResultOutbox(outbox: ChannelOutbox, store: OutboxStore): void {
  stores.set(outbox, store);
}
export function resultOutbox(outbox: object): OutboxStore | undefined {
  return stores.get(outbox);
}
