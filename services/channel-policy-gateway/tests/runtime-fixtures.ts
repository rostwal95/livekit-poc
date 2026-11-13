/** Synthetic public configuration/credentials for pure and loopback tests only. */
import type { RuntimeConfiguration, RuntimeCredentials } from '../src/runtime-config.js';
export function configuration(): RuntimeConfiguration {
  return {
    schemaVersion: 1,
    profileInboxLimit: 16,
    route: {
      profileId: '11111111-1111-4111-8111-111111111111',
      receiverId: '22222222-2222-4222-8222-222222222222',
      scope: { tenantId: 'tenant_demo', accountId: 'account_demo' },
      caseId: 'case_demo',
      conversationId: 'conversation_demo',
      recipientId: 'recipient_demo',
    },
    postgres: {
      host: '127.0.0.1',
      port: 15432,
      database: 'livekit_lab',
      user: 'livekit_lab',
      schema: 'p2_joined_unit',
    },
    providers: {
      native: { tenantId: 'tenant_demo', provider: 'livekit', providerAccountId: 'joined_rtc' },
      sms: { tenantId: 'tenant_demo', provider: 'fake_sms', providerAccountId: 'joined_sms' },
    },
    simulationHmac: 'public_synthetic_v1',
    caseEndpoint: { host: '127.0.0.1', port: 11021 },
    originEndpoints: {
      native: { host: '127.0.0.1', port: 11022 },
      sms: { host: '127.0.0.1', port: 11023 },
    },
    listen: { nativePort: 11024, smsPort: 11025, readPort: 11026, receiverPort: 11027 },
  };
}
export function credentials(): RuntimeCredentials {
  return {
    postgresPassword: 'synthetic_password_value_1234567890',
    accountToken: 'a'.repeat(43),
    nativePublisherToken: 'b'.repeat(43),
    resultPublisherToken: 'c'.repeat(43),
    workerBearer: 'd'.repeat(43),
    nativeOriginBearer: 'e'.repeat(43),
    smsOriginBearer: 'f'.repeat(43),
    caseAuthorization: 'Bearer ' + 'g'.repeat(43),
  };
}
export function environment(): Record<string, string> {
  const c = credentials();
  return {
    PATH: '/usr/bin:/bin',
    LANG: 'en_US.UTF-8',
    CI: '1',
    NO_COLOR: '1',
    P2_DEMO_POSTGRES_PASSWORD: c.postgresPassword,
    P2_DEMO_ACCOUNT_TOKEN: c.accountToken,
    P2_DEMO_NATIVE_PUBLISHER_TOKEN: c.nativePublisherToken,
    P2_DEMO_RESULT_PUBLISHER_TOKEN: c.resultPublisherToken,
    P2_DEMO_WORKER_BEARER: c.workerBearer,
    P2_DEMO_NATIVE_ORIGIN_BEARER: c.nativeOriginBearer,
    P2_DEMO_SMS_ORIGIN_BEARER: c.smsOriginBearer,
    P2_DEMO_CASE_AUTHORIZATION: c.caseAuthorization,
  };
}
export function deferred<T = void>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
