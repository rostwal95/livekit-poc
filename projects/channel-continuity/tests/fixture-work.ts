/** Test-only caller observation; no I/O starts on import. Reviewed 12 November 2026. */
export type FixtureOutcome<T> =
  Readonly<{ status: 'fulfilled'; value: T }> | Readonly<{ status: 'rejected'; reason: unknown }>;

// Both branches are installed in the same turn that creates the caller. The
// retained outcome never rejects; a later result assertion rethrows its original.
export function observeFixtureWork<T>(caller: Promise<T>): Promise<FixtureOutcome<T>> {
  return caller.then(
    (value) => ({ status: 'fulfilled', value }),
    (reason: unknown) => ({ status: 'rejected', reason }),
  );
}

export async function fixtureResult<T>(observed: Promise<FixtureOutcome<T>>): Promise<T> {
  const outcome = await observed;
  if (outcome.status === 'rejected') throw outcome.reason;
  return outcome.value;
}

export async function awaitFixtureEntry(
  entered: Promise<void>,
  observed: Promise<FixtureOutcome<unknown>>,
  timeoutMs: number,
  timeoutError: () => unknown = () => new Error('fixture_entry_timeout'),
): Promise<void> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const outcome = await Promise.race([
      entered.then(() => ({ status: 'entry' as const })),
      observed.then((caller) => ({ status: 'settled' as const, caller })),
      new Promise<Readonly<{ status: 'timeout' }>>((resolve) => {
        timer = setTimeout(() => resolve({ status: 'timeout' }), timeoutMs);
      }),
    ]);
    if (outcome.status === 'entry') return;
    if (outcome.status === 'timeout') throw timeoutError();
    if (outcome.caller.status === 'rejected') throw outcome.caller.reason;
    throw new Error('fixture_entry_not_reached');
  } finally {
    clearTimeout(timer);
  }
}
