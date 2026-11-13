/** Actual read-only browser over the public PG-backed HTTP service; no RTC or command endpoint. */
import { test, expect, type Page } from '@playwright/test';
import { mkdir, writeFile, readFile, link, unlink, stat } from 'node:fs/promises';
import { resolve } from 'node:path';
const output = process.env.P2_OPERATIONS_BROWSER_OUTPUT,
  access = process.env.P2_OPERATIONS_BROWSER_ACCESS,
  directory = process.env.P2_OPERATIONS_DIRECTORY,
  owner = process.env.P2_OPERATIONS_OWNER,
  receiptId = process.env.P2_OPERATIONS_RECEIPT_ID,
  operationKey = process.env.P2_OPERATIONS_OPERATION_KEY,
  outboundId = process.env.P2_OPERATIONS_OUTBOUND_ID;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])/;
if (
  !output ||
  !directory ||
  !access ||
  !/^[A-Za-z0-9_-]{43}(?![\s\S])/.test(access) ||
  !owner ||
  !/^[0-9a-f]{32}(?![\s\S])/.test(owner) ||
  [receiptId, operationKey, outboundId].some((x) => !x || !uuid.test(x))
)
  throw Error('Explicit fixed operations fixture required');
interface Evidence {
  schemaVersion: 1;
  phase: string;
  code: string | null;
  telemetryCode: string | null;
  contextObserved: boolean;
  current: boolean;
  asOf: string | null;
  historical: boolean;
  diagnosticsHistorical: boolean;
  ownedClient: number;
  actualRequests: number;
  cleanupComplete: boolean;
  contextPending: boolean;
  telemetryPending: boolean;
  polling: boolean;
  ticks: number;
  readCounts: { context: number; telemetry: number; settled: number; abandoned: number };
  receipts: { receiptId: string; processingState: string; operationKey: string }[];
  operations: { operationKey: string; state: string }[];
  outbound: { outboundId: string; result: string; callbacks: string[] }[];
  pages: { history: number; work: number; responses: number; replies: number };
  sources: { source: string; state: string; metricCount: number }[];
  observationCount: number;
}
const groups = [
  'durable_joined_timeline_and_scoped_paging',
  'unknown_carrier_and_callback_source_separation',
  'actual_read_failure_retry_export_outage_and_forget_fencing',
];
let latest: Evidence | undefined;
async function evidence(page: Page) {
  const raw = await page.locator('#operations-evidence').textContent();
  if (!raw || Buffer.byteLength(raw) > 32768) throw Error('Bounded operations evidence required');
  latest = JSON.parse(raw) as Evidence;
  return latest;
}
async function mark(stage: string) {
  const name = 'operations-' + stage + '.json',
    path = resolve(directory!, name),
    temp = path + '.' + process.pid + '.pending';
  await writeFile(temp, JSON.stringify({ schemaVersion: 1, owner, stage }) + '\n', {
    flag: 'wx',
    mode: 0o600,
  });
  try {
    await link(temp, path);
  } finally {
    await unlink(temp);
  }
}
async function privateProof(name: string) {
  const path = resolve(directory!, name),
    s = await stat(path);
  expect(s.size).toBeLessThanOrEqual(1048576);
  return JSON.parse(await readFile(path, 'utf8')) as Record<string, unknown>;
}
async function waitFile(name: string) {
  await expect
    .poll(
      async () => {
        try {
          await stat(resolve(directory!, name));
          return true;
        } catch {
          return false;
        }
      },
      { timeout: 15000 },
    )
    .toBe(true);
  return privateProof(name);
}
async function settled(page: Page) {
  await expect
    .poll(async () => {
      const e = await evidence(page);
      return !e.contextPending && !e.telemetryPending;
    })
    .toBe(true);
}
async function refresh(page: Page) {
  await page.locator('[data-ops-refresh]').click();
  await settled(page);
}
async function untilState(page: Page, state: string) {
  for (let n = 0; n < 20; n++) {
    await refresh(page);
    const e = await evidence(page);
    if (e.receipts.find((r) => r.receiptId === receiptId)?.processingState === state) return e;
    await page.waitForTimeout(50);
  }
  throw Error('Actual processing observation did not reach expected state');
}
async function save(file: string, value: unknown) {
  await writeFile(resolve(output!, file), JSON.stringify(value) + '\n', {
    flag: 'wx',
    mode: 0o600,
  });
}
test('joined durable operations, source evidence and honest read recovery', async ({ page }) => {
  await mkdir(output!, { recursive: true, mode: 0o700 });
  const errors: string[] = [],
    unexpected: string[] = [];
  let stage = 'opening';
  let primary: unknown;
  let initial: Evidence | undefined,
    running: Evidence | undefined,
    uncertain: Evidence | undefined,
    known: Evidence | undefined,
    callback: Evidence | undefined,
    failed: Evidence | undefined,
    recovered: Evidence | undefined,
    forgotten: Evidence | undefined;
  let afterForget: unknown, afterRelease: unknown;
  page.on('pageerror', () => errors.push('page_error'));
  page.on('request', (request) => {
    try {
      const url = new URL(request.url()),
        base = new URL(process.env.P2_OPERATIONS_BROWSER_ORIGIN!);
      if (url.origin !== base.origin && !['data:', 'blob:'].includes(url.protocol))
        unexpected.push('foreign_origin');
    } catch {
      unexpected.push('invalid_origin');
    }
  });
  try {
    await page.goto('/p2-operations.html');
    await expect(
      page.getByRole('heading', { name: 'Channel operations', exact: true }),
    ).toBeVisible();
    expect((await evidence(page)).contextObserved).toBe(false);
    await page.locator('[data-ops-token]').fill(access!);
    await page.locator('[data-ops-connect]').click();
    await expect.poll(async () => (await evidence(page)).phase).toBe('ready');
    await settled(page);
    if ((await evidence(page)).polling) await page.locator('[data-ops-pause]').click();
    await expect(page.locator('[data-ops-token]')).toHaveValue('');
    initial = await evidence(page);
    expect(initial.current).toBe(true);
    expect(initial.asOf).not.toBeNull();
    expect(initial.receipts.find((r) => r.receiptId === receiptId)).toMatchObject({
      operationKey,
      processingState: 'pending',
    });
    expect(initial.outbound.find((r) => r.outboundId === outboundId)).toMatchObject({
      result: 'unknown',
      callbacks: [],
    });
    expect(initial.sources.map((s) => s.source)).toEqual([
      'inbox',
      'inbox_telemetry',
      'operations',
    ]);
    expect(initial.sources.every((s) => s.state === 'observed')).toBe(true);
    expect(initial.observationCount).toBeGreaterThan(0);
    await page.locator('[data-ops-more="history"]').click();
    await settled(page);
    expect((await evidence(page)).pages.history).toBe(11);
    expect(
      await page.evaluate(() => {
        const active = document.activeElement as HTMLElement | null;
        return (
          active?.dataset.opsMore === 'history' || active?.dataset.opsFocusSection === 'history'
        );
      }),
    ).toBe(true);
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => document.activeElement !== document.body)).toBe(true);
    await page.locator('[data-ops-more="work"]').click();
    await settled(page);
    expect((await evidence(page)).pages.work).toBe(11);
    expect(new Set((await evidence(page)).receipts.map((r) => r.receiptId)).size).toBe(11);
    stage = 'pending_known';
    await page.screenshot({ path: resolve(output!, 'operations-ready.png'), fullPage: true });
    await mark('request-dispatch');
    running = await untilState(page, 'running');
    expect(running.operations.find((r) => r.operationKey === operationKey)?.state).toBe('running');
    stage = 'running_observed';
    await mark('dispatch-running');
    uncertain = await untilState(page, 'uncertain');
    expect(uncertain.operations.find((r) => r.operationKey === operationKey)?.state).toBe(
      'uncertain',
    );
    await mark('request-reconcile');
    known = await untilState(page, 'dispatched');
    expect(known.receipts.find((r) => r.receiptId === receiptId)?.operationKey).toBe(operationKey);
    expect(known.operations.some((r) => r.operationKey === operationKey)).toBe(false);
    await expect
      .poll(async () => {
        await refresh(page);
        return (await evidence(page)).pages.responses;
      })
      .toBe(1);
    stage = 'known_original_operation';
    expect((await evidence(page)).outbound.find((r) => r.outboundId === outboundId)?.result).toBe(
      'unknown',
    );
    await mark('request-callback');
    await expect
      .poll(async () => {
        await refresh(page);
        return (await evidence(page)).outbound
          .find((r) => r.outboundId === outboundId)
          ?.callbacks.includes('delivered');
      })
      .toBe(true);
    callback = await evidence(page);
    expect(callback.outbound.find((r) => r.outboundId === outboundId)?.result).toBe('unknown');
    await expect(
      page.locator(`[data-ops-outbound="${outboundId}"] [data-ops-source="send_result"]`),
    ).toContainText('unknown');
    await expect(
      page.locator(`[data-ops-outbound="${outboundId}"] [data-ops-source="callback"]`),
    ).toContainText('delivered');
    stage = 'source_separation';
    await mark('read-failure');
    await refresh(page);
    await expect.poll(async () => (await evidence(page)).code).toBe('unavailable');
    failed = await evidence(page);
    expect(failed.historical).toBe(true);
    expect(failed.current).toBe(false);
    expect(failed.polling).toBe(false);
    expect(failed.receipts.find((r) => r.receiptId === receiptId)?.operationKey).toBe(operationKey);
    await page.locator('[data-ops-retry]').click();
    await settled(page);
    await expect.poll(async () => (await evidence(page)).phase).toBe('ready');
    recovered = await evidence(page);
    expect(recovered.code).toBeNull();
    expect(recovered.current).toBe(true);
    expect(recovered.historical).toBe(false);
    expect(recovered.receipts.find((r) => r.receiptId === receiptId)?.operationKey).toBe(
      operationKey,
    );
    await mark('release-exporter');
    await refresh(page);
    await expect(page.locator('[data-ops-token]')).toHaveValue('');
    stage = 'actual_read_recovered';
    await page.screenshot({ path: resolve(output!, 'operations-recovered.png'), fullPage: true });
    await mark('hold-read');
    await page.locator('[data-ops-refresh]').click();
    const held = await waitFile('operations-read-held.json');
    expect(held.readerActive).toBe(1);
    await page.locator('[data-ops-forget]').click();
    await expect.poll(async () => (await evidence(page)).ownedClient).toBe(0);
    forgotten = await evidence(page);
    expect(forgotten.receipts).toEqual([]);
    expect(forgotten.outbound).toEqual([]);
    expect(forgotten.sources).toEqual([]);
    expect(forgotten.asOf).toBeNull();
    expect(forgotten.actualRequests).toBe(0);
    expect(forgotten.cleanupComplete).toBe(true);
    await mark('release-read');
    const late = await waitFile('operations-late-read-proof.json');
    afterForget = late.afterForget;
    afterRelease = late.afterRelease;
    expect(afterForget).toEqual({ readerActive: 1 });
    expect(afterRelease).toEqual({ readerActive: 0 });
    const final = await evidence(page);
    expect(final.receipts).toEqual([]);
    expect(final.contextObserved).toBe(false);
    expect(final.ownedClient).toBe(0);
    expect(final.actualRequests).toBe(0);
    expect(
      await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length })),
    ).toEqual({ local: 0, session: 0 });
    expect(errors).toEqual([]);
    expect(unexpected).toEqual([]);
    stage = 'complete';
    await mark('browser-finished');
    await save('operations-browser-observations.json', {
      schemaVersion: 1,
      status: 'passed',
      mode: 'local_scripted_p2_operations_browser',
      groups,
      initial,
      running,
      uncertain,
      known,
      callback,
      failed,
      recovered,
      forgotten,
      backendAfterForget: afterForget,
      backendAfterRelease: afterRelease,
      originalReceiptId: receiptId,
      originalOperationKey: operationKey,
      originalOutboundId: outboundId,
      readOnlyControls: true,
      actualReadFailure: true,
      latePositiveJsDeliveryClaimed: false,
      cleanupComplete: true,
      pageErrors: errors.length,
      unexpectedNetworkRequests: unexpected.length,
    });
  } catch (error) {
    primary = error;
    throw error;
  } finally {
    if (primary) {
      try {
        await mark('release-exporter');
      } catch {
        /* already requested */
      }
      try {
        await mark('release-read');
      } catch {
        /* already requested */
      }
      try {
        await page.locator('[data-ops-forget]').click({ timeout: 1000 });
      } catch {
        /* failure snapshot remains diagnostic */
      }
    }
    await save('operations-browser-context.json', {
      schemaVersion: 1,
      status: stage === 'complete' ? 'passed' : 'failed',
      stage,
      phase: latest?.phase ?? null,
      code: latest?.code ?? null,
      ownedClient: latest?.ownedClient ?? null,
      actualRequests: latest?.actualRequests ?? null,
      contextPending: latest?.contextPending ?? null,
      telemetryPending: latest?.telemetryPending ?? null,
      pageErrors: errors.length,
      unexpectedNetworkRequests: unexpected.length,
    }).catch(() => {});
  }
});
