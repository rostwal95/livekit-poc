/** Snapshot class/plain-object methods without invoking injected accessors. */
export function snapshotMethod<T extends (...args: never[]) => unknown>(
  owner: unknown,
  name: string,
): T {
  if (owner === null || (typeof owner !== 'object' && typeof owner !== 'function'))
    throw new TypeError('invalid_adapter');
  let current: object | null = owner;
  for (let depth = 0; current !== null && depth < 8; depth++) {
    const descriptor = Object.getOwnPropertyDescriptor(current, name);
    if (descriptor !== undefined) {
      if (!('value' in descriptor) || typeof descriptor.value !== 'function')
        throw new TypeError('invalid_adapter');
      return descriptor.value.bind(owner) as T;
    }
    current = Object.getPrototypeOf(current);
  }
  throw new TypeError('invalid_adapter');
}
