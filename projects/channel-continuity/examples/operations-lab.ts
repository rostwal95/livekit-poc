/** Application composition only. Import starts no listener and owns no database pool. */
import type { ChannelInbox } from '@livekit-ecosystem/channel-continuity/postgres';
import type { FakeSmsIntegration } from '@livekit-ecosystem/channel-continuity/security';
import type { CurrentCasePort } from '@livekit-ecosystem/channel-continuity/rehydration';
import {
  OperationsError,
  OperationsReader,
  OperationsTelemetry,
  OperationsReadServer,
  operationsRecord,
  type OperationsProfile,
  type OperationsObserver,
} from '@livekit-ecosystem/channel-continuity/operations';
export type OperationsLabOptions = Readonly<{
  inbox: ChannelInbox;
  cases: CurrentCasePort;
  sms: FakeSmsIntegration;
  profile: OperationsProfile;
  authorization: string;
  observer?: OperationsObserver;
}>;
export async function startOperationsLab(options: OperationsLabOptions) {
  let o: Record<string, unknown>;
  try {
    const keys = [
      'inbox',
      'cases',
      'sms',
      'profile',
      'authorization',
      ...(options &&
      typeof options === 'object' &&
      Object.getOwnPropertyDescriptor(options, 'observer')
        ? ['observer']
        : []),
    ];
    o = operationsRecord(options, keys);
  } catch {
    throw new OperationsError('invalid_query');
  }
  const inbox = o.inbox as ChannelInbox;
  const reader = new OperationsReader(
    inbox,
    o.cases as CurrentCasePort,
    o.sms as FakeSmsIntegration,
    o.profile as OperationsProfile,
  );
  const telemetry: OperationsTelemetry = new OperationsTelemetry(
    [
      {
        source: 'inbox',
        read: () => {
          const m = inbox.metrics();
          return {
            accepted: m.accepted,
            replayed: m.replayed,
            rejected: m.rejected,
            dependencyErrors: m.dependencyErrors,
            overloaded: m.overloaded,
            telemetryFailures: m.telemetryFailures,
            active: m.active,
          };
        },
      },
      { source: 'inbox_telemetry', read: () => inbox.telemetryMetrics() },
      {
        source: 'operations',
        read: () => {
          const r = reader.metrics(),
            t = telemetry.metrics();
          return {
            ...t,
            readerActive: r.active,
            readerStarted: r.started,
            readerKnown: r.known,
            readerWaiterRejected: r.waiterRejected,
          };
        },
      },
    ],
    o.observer as OperationsObserver | undefined,
  );
  const server = new OperationsReadServer(reader, telemetry, o.authorization as string);
  // Supplied inbox/case port/export transport are separate application owners.
  let primary: unknown,
    started = false;
  try {
    const endpoint = await server.start();
    started = true;
    return Object.freeze({
      endpoint,
      reader,
      telemetry,
      server,
      async close() {
        let failure: unknown;
        for (const action of [() => server.close(), () => reader.close(), () => telemetry.close()])
          try {
            await action();
          } catch (error) {
            failure ??= error;
          }
        if (failure) throw failure;
      },
    });
  } catch (error) {
    primary = error;
    throw error;
  } finally {
    if (!started) {
      for (const action of [() => server.close(), () => reader.close(), () => telemetry.close()])
        try {
          await action();
        } catch (error) {
          primary ??= error;
        }
      if (primary) {
        /* Original startup failure remains authoritative; dependencies stay app-owned. */
      }
    }
  }
}
