import { rehydrationContext, type RehydrationContext } from '../src/rehydration-types.js';
/** A failed dependent close withholds its shared owners. Every independent close in a tier is attempted. */
export async function cleanupOperationsOwners(
  tiers: readonly (readonly (() => unknown)[])[],
  original?: unknown,
) {
  let failure = original;
  for (const tier of tiers) {
    const outcomes = await Promise.allSettled(tier.map((action) => Promise.resolve().then(action)));
    const rejected = outcomes.filter((v): v is PromiseRejectedResult => v.status === 'rejected');
    if (rejected.length) {
      failure ??= rejected[0]!.reason;
      break;
    }
  }
  if (failure !== undefined) throw failure;
}

/** Fixed evidence collection is sequential; it is not a business work queue. */
export async function inspectOperationsOriginals<T, R>(
  values: readonly T[],
  inspect: (value: T) => Promise<R>,
): Promise<readonly R[]> {
  if (values.length !== 10) throw Error('invalid_fixture_inventory');
  const originals: R[] = [];
  for (const value of values) originals.push(await inspect(value));
  return originals;
}

/** Normalize every original retained field through the same public DTO, not object insertion order. */
export function normalizeOperationsOriginal(context: RehydrationContext, original: unknown) {
  return rehydrationContext(
    {
      ...context,
      history: { messages: [original], nextCursor: null, hasMore: false },
    },
    context.case,
  ).history.messages[0]!;
}
