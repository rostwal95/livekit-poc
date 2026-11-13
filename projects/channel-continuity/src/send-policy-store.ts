/** Same-transaction policy SQL helper. Owns no pool, tasks, authority queue or provider I/O. */
import { randomUUID } from 'node:crypto';
import type { PoolClient } from 'pg';
import { table } from './database.js';
import type { ProviderScope } from './index.js';
import {
  OutboxError,
  recipient,
  sendRequest,
  carrierResult,
  sha,
  uuid,
  timestamp,
  type SendRequest,
  type OutboxPublisher,
} from './outbox-types.js';
import {
  admission,
  type OperationAdmission,
  operation,
  operationFrom,
  operationDigest,
  sendPolicyLimits,
  recoveryReceipt,
  recoveryObservation,
  type ProviderOperation,
  type ProviderLookup,
  type SendCapability,
  type SendPolicyLimits,
  type RecoveryKind,
  type RecoveryReceipt,
  type RecoveryObservation,
  type RecoveryCommandView,
  type RecoveryCode,
} from './send-policy-types.js';
type Ref = Omit<OutboxPublisher, 'token'>;
export type OperationState = {
  state: 'accepted_by_provider' | 'definitive_not_accepted' | 'unknown' | 'conflicted';
  ids: readonly string[];
  callbackVeto: boolean;
  commandCount: number;
  latestCommandId: string | null;
};
export class SendPolicyStore {
  readonly #schema: string;
  readonly #provider: ProviderScope;
  constructor(schema: string, provider: ProviderScope) {
    this.#schema = schema;
    this.#provider = Object.freeze({ ...provider });
  }
  #q(name: string) {
    return table(this.#schema, name);
  }
  #sameRef(op: ProviderOperation, ref: Ref) {
    if (
      JSON.stringify(
        recipient({ scope: op.scope, caseId: op.caseId, conversationId: op.conversationId }),
      ) !== JSON.stringify(ref) ||
      JSON.stringify(op.providerScope) !== JSON.stringify(this.#provider)
    )
      throw new OutboxError('AccessDenied');
  }
  async policy(c: PoolClient, guard = false): Promise<SendPolicyLimits> {
    const rows = (
      await c.query(
        `SELECT * FROM ${this.#q('send_policy_settings')} WHERE singleton${guard ? ' FOR UPDATE' : ''}`,
      )
    ).rows;
    if (
      rows.length !== 1 ||
      rows[0].ordinary_unknown !== 'hold_no_resend' ||
      rows[0].idempotent_unknown !== 'explicit_same_key_only'
    )
      throw new OutboxError('Unavailable');
    const p = rows[0],
      bounds = sendPolicyLimits({
        maxRecoveryCommands: p.max_recovery_commands,
        maxPerOperation: p.max_per_operation,
      });
    if (
      !Number.isSafeInteger(p.recovery_count) ||
      p.recovery_count < 0 ||
      p.recovery_count > bounds.maxRecoveryCommands
    )
      throw new OutboxError('Unavailable');
    if (guard) {
      const counts = (
        await c.query(`SELECT count(*)::integer AS count FROM ${this.#q('send_recovery_commands')}`)
      ).rows;
      if (counts[0]?.count !== p.recovery_count) throw new OutboxError('Unavailable');
    }
    return bounds;
  }
  async admissionFor(
    c: PoolClient,
    previous: SendRequest | undefined,
    ref: Ref,
  ): Promise<OperationAdmission> {
    if (previous === undefined) return admission({ schemaVersion: 1, kind: 'first_operation' });
    const { operation: op } = await this.loadOperation(c, previous.providerOperationKey, ref);
    const rows = (
      await c.query(
        `SELECT a.attempt_id,a.canonical_request,a.request_digest,r.canonical_result FROM ${this.#q('send_attempts')} a JOIN ${this.#q('send_results')} r USING(attempt_id) WHERE a.provider_operation_key=$1 AND r.canonical_result::jsonb->>'status'='definitive_not_accepted' ORDER BY a.ordinal DESC LIMIT 1`,
        [op.providerOperationKey],
      )
    ).rows;
    if (rows.length === 1) {
      const row = rows[0],
        request = sendRequest(JSON.parse(row.canonical_request)),
        result = carrierResult(JSON.parse(row.canonical_result), request);
      if (
        JSON.stringify(request) !== row.canonical_request ||
        request.attemptId !== row.attempt_id ||
        sha(row.canonical_request) !== row.request_digest ||
        JSON.stringify(operationFrom(request, op.capability)) !== JSON.stringify(op) ||
        JSON.stringify(result) !== row.canonical_result ||
        result.status !== 'definitive_not_accepted'
      )
        throw new OutboxError('Unavailable');
      return admission({
        schemaVersion: 1,
        kind: 'prior_send_nonacceptance',
        predecessorAttemptId: previous.attemptId,
        predecessorOperationKey: op.providerOperationKey,
        evidenceAttemptId: request.attemptId,
        evidenceDigest: sha(row.canonical_result),
      });
    }
    const observations = (
      await c.query(
        `${this.#commandSelect()} WHERE r.provider_operation_key=$1 AND o.canonical_observation::jsonb->>'source'='lookup' AND o.canonical_observation::jsonb->>'state'='definitive_not_accepted' AND o.canonical_observation::jsonb->>'assessment'='reported' ORDER BY r.accepted_at,r.command_id LIMIT 1`,
        [op.providerOperationKey],
      )
    ).rows;
    if (observations.length !== 1) throw new OutboxError('Unavailable');
    const view = this.#decode(observations[0], op);
    if (
      view.observation?.source !== 'lookup' ||
      view.observation.state !== 'definitive_not_accepted' ||
      view.observation.assessment !== 'reported'
    )
      throw new OutboxError('Unavailable');
    return admission({
      schemaVersion: 1,
      kind: 'prior_lookup_nonacceptance',
      predecessorAttemptId: previous.attemptId,
      predecessorOperationKey: op.providerOperationKey,
      commandId: view.receipt.commandId,
      evidenceDigest: sha(observations[0].canonical_observation),
    });
  }
  async createOperation(
    c: PoolClient,
    request: SendRequest,
    mode: SendCapability,
    witness: OperationAdmission,
  ): Promise<ProviderOperation> {
    const op = operationFrom(request, mode),
      proof = JSON.stringify(admission(witness));
    await c.query(
      `INSERT INTO ${this.#q('send_operations')} VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,clock_timestamp())`,
      [
        op.providerOperationKey,
        op.scope.tenantId,
        op.scope.accountId,
        op.outboundId,
        op.providerScope.provider,
        op.providerScope.providerAccountId,
        request.attemptId,
        mode,
        JSON.stringify(op),
        operationDigest(op),
        sha(JSON.stringify(request)),
        proof,
        sha(proof),
      ],
    );
    return op;
  }
  async loadOperation(
    c: PoolClient,
    key: string,
    ref: Ref,
    depth = 0,
  ): Promise<{ operation: ProviderOperation; firstAttemptId: string }> {
    if (depth > 5) throw new OutboxError('Unavailable');
    const rows = (
      await c.query(
        `SELECT o.*,a.canonical_request,a.request_digest,a.provider_operation_key AS anchor_key,a.tenant_id AS anchor_tenant,a.account_id AS anchor_account,a.outbound_id AS anchor_outbound,a.ordinal AS anchor_ordinal FROM ${this.#q('send_operations')} o JOIN ${this.#q('send_attempts')} a ON a.attempt_id=o.first_attempt_id WHERE o.provider_operation_key=$1`,
        [key],
      )
    ).rows;
    if (rows.length !== 1) throw new OutboxError('Unavailable');
    try {
      const r = rows[0],
        op = operation(JSON.parse(r.canonical_operation)),
        anchor = sendRequest(JSON.parse(r.canonical_request));
      if (
        JSON.stringify(op) !== r.canonical_operation ||
        operationDigest(op) !== r.operation_digest ||
        op.providerOperationKey !== r.provider_operation_key ||
        op.scope.tenantId !== r.tenant_id ||
        op.scope.accountId !== r.account_id ||
        op.outboundId !== r.outbound_id ||
        op.providerScope.provider !== r.provider ||
        op.providerScope.providerAccountId !== r.provider_account_id ||
        op.capability !== r.capability ||
        anchor.attemptId !== r.first_attempt_id ||
        r.anchor_key !== op.providerOperationKey ||
        r.anchor_tenant !== op.scope.tenantId ||
        r.anchor_account !== op.scope.accountId ||
        r.anchor_outbound !== op.outboundId ||
        JSON.stringify(anchor) !== r.canonical_request ||
        sha(r.canonical_request) !== r.request_digest ||
        r.request_digest !== r.first_request_digest ||
        JSON.stringify(operationFrom(anchor, op.capability)) !== r.canonical_operation
      )
        throw Error();
      if (
        typeof r.admission_proof !== 'string' ||
        sha(r.admission_proof) !== r.admission_digest ||
        !Number.isSafeInteger(r.anchor_ordinal) ||
        r.anchor_ordinal < 1 ||
        r.anchor_ordinal > 5
      )
        throw Error();
      const witness = admission(JSON.parse(r.admission_proof));
      if (JSON.stringify(witness) !== r.admission_proof) throw Error();
      if (witness.kind === 'first_operation') {
        if (r.anchor_ordinal !== 1) throw Error();
      } else {
        if (r.anchor_ordinal === 1 || witness.predecessorOperationKey === op.providerOperationKey)
          throw Error();
        const previousRows = (
          await c.query(`SELECT * FROM ${this.#q('send_attempts')} WHERE attempt_id=$1`, [
            witness.predecessorAttemptId,
          ])
        ).rows;
        if (previousRows.length !== 1) throw Error();
        const previousRow = previousRows[0],
          previous = sendRequest(JSON.parse(previousRow.canonical_request));
        if (
          previous.attemptId !== witness.predecessorAttemptId ||
          previousRow.ordinal !== r.anchor_ordinal - 1 ||
          previous.providerOperationKey !== witness.predecessorOperationKey ||
          previousRow.provider_operation_key !== witness.predecessorOperationKey ||
          JSON.stringify(previous) !== previousRow.canonical_request ||
          sha(previousRow.canonical_request) !== previousRow.request_digest ||
          previous.scope.tenantId !== previousRow.tenant_id ||
          previous.scope.accountId !== previousRow.account_id ||
          previous.outboundId !== previousRow.outbound_id ||
          previous.scope.tenantId !== op.scope.tenantId ||
          previous.scope.accountId !== op.scope.accountId ||
          previous.outboundId !== op.outboundId
        )
          throw Error();
        const predecessor = (
          await this.loadOperation(c, previous.providerOperationKey, ref, depth + 1)
        ).operation;
        if (predecessor.capability !== op.capability) throw Error();
        if (witness.kind === 'prior_send_nonacceptance') {
          const evidence = (
            await c.query(
              `SELECT a.canonical_request,a.request_digest,a.attempt_id,r.canonical_result FROM ${this.#q('send_attempts')} a JOIN ${this.#q('send_results')} r USING(attempt_id) WHERE a.attempt_id=$1 AND a.provider_operation_key=$2`,
              [witness.evidenceAttemptId, witness.predecessorOperationKey],
            )
          ).rows;
          if (evidence.length !== 1) throw Error();
          const e = evidence[0],
            request = sendRequest(JSON.parse(e.canonical_request)),
            result = carrierResult(JSON.parse(e.canonical_result), request);
          if (
            request.attemptId !== witness.evidenceAttemptId ||
            request.attemptId !== e.attempt_id ||
            JSON.stringify(request) !== e.canonical_request ||
            sha(e.canonical_request) !== e.request_digest ||
            JSON.stringify(operationFrom(request, predecessor.capability)) !==
              JSON.stringify(predecessor) ||
            JSON.stringify(result) !== e.canonical_result ||
            sha(e.canonical_result) !== witness.evidenceDigest ||
            result.status !== 'definitive_not_accepted'
          )
            throw Error();
        } else {
          const evidence = (
            await c.query(`${this.#commandSelect()} WHERE r.command_id=$1`, [witness.commandId])
          ).rows;
          if (
            evidence.length !== 1 ||
            sha(evidence[0].canonical_observation) !== witness.evidenceDigest
          )
            throw Error();
          const view = this.#decode(evidence[0], predecessor);
          if (
            view.observation?.source !== 'lookup' ||
            view.observation.state !== 'definitive_not_accepted' ||
            view.observation.assessment !== 'reported'
          )
            throw Error();
        }
      }
      this.#sameRef(op, ref);
      return { operation: op, firstAttemptId: uuid(r.first_attempt_id) };
    } catch (error) {
      if (error instanceof OutboxError && error.code === 'AccessDenied') throw error;
      throw new OutboxError('Unavailable');
    }
  }
  #semantic(
    kind: RecoveryKind,
    commandId: string,
    outboundId: string,
    attemptId: string,
    op: ProviderOperation,
  ): string {
    return JSON.stringify({
      schemaVersion: 1,
      kind,
      commandId,
      outboundId,
      attemptId,
      scope: op.scope,
      caseId: op.caseId,
      conversationId: op.conversationId,
      providerOperationKey: op.providerOperationKey,
      operationDigest: operationDigest(op),
    });
  }
  #commandSelect(): string {
    return `SELECT r.*,src.canonical_request AS source_request,src.request_digest AS source_request_digest,src.tenant_id AS source_tenant,src.account_id AS source_account,src.outbound_id AS source_outbound,src.provider_operation_key AS source_key,o.canonical_observation,o.observation_digest,o.observed_at FROM ${this.#q('send_recovery_commands')} r JOIN ${this.#q('send_attempts')} src ON src.attempt_id=r.source_attempt_id LEFT JOIN ${this.#q('send_recovery_observations')} o USING(command_id)`;
  }
  #decode(row: Record<string, unknown>, op: ProviderOperation): RecoveryCommandView {
    try {
      if (
        typeof row.canonical_command !== 'string' ||
        sha(row.canonical_command) !== row.command_digest ||
        typeof row.receipt_json !== 'string' ||
        sha(row.receipt_json) !== row.receipt_digest
      )
        throw Error();
      if (
        typeof row.source_request !== 'string' ||
        sha(row.source_request) !== row.source_request_digest
      )
        throw Error();
      const source = sendRequest(JSON.parse(row.source_request));
      if (
        JSON.stringify(source) !== row.source_request ||
        source.attemptId !== row.source_attempt_id ||
        source.providerOperationKey !== op.providerOperationKey ||
        row.source_key !== op.providerOperationKey ||
        source.scope.tenantId !== row.source_tenant ||
        source.scope.accountId !== row.source_account ||
        source.outboundId !== row.source_outbound ||
        JSON.stringify(operationFrom(source, op.capability)) !== JSON.stringify(op)
      )
        throw Error();
      const receipt = recoveryReceipt(JSON.parse(row.receipt_json));
      if (
        JSON.stringify(receipt) !== row.receipt_json ||
        receipt.commandId !== row.command_id ||
        receipt.sourceAttemptId !== row.source_attempt_id ||
        receipt.kind !== row.kind ||
        receipt.newAttemptId !== row.new_attempt_id ||
        receipt.outboundId !== op.outboundId ||
        receipt.providerOperationKey !== op.providerOperationKey ||
        receipt.operationDigest !== operationDigest(op) ||
        row.canonical_command !==
          this.#semantic(
            receipt.kind,
            receipt.commandId,
            receipt.outboundId,
            receipt.sourceAttemptId,
            op,
          ) ||
        row.tenant_id !== op.scope.tenantId ||
        row.account_id !== op.scope.accountId ||
        row.outbound_id !== op.outboundId ||
        receipt.acceptedAt !== timestamp(row.accepted_at)
      )
        throw Error();
      let observed: RecoveryObservation | null = null;
      if (row.canonical_observation !== null) {
        if (
          typeof row.canonical_observation !== 'string' ||
          sha(row.canonical_observation) !== row.observation_digest
        )
          throw Error();
        observed = recoveryObservation(JSON.parse(row.canonical_observation), receipt);
        if (
          JSON.stringify(observed) !== row.canonical_observation ||
          observed.observedAt !== timestamp(row.observed_at)
        )
          throw Error();
      } else if (row.observation_digest !== null || row.observed_at !== null) throw Error();
      return Object.freeze({ receipt, observation: observed });
    } catch {
      throw new OutboxError('Unavailable');
    }
  }
  async command(c: PoolClient, commandId: string, ref: Ref): Promise<RecoveryCommandView | null> {
    const rows = (await c.query(`${this.#commandSelect()} WHERE r.command_id=$1`, [commandId]))
      .rows;
    if (!rows.length) return null;
    if (rows.length !== 1) throw new OutboxError('Unavailable');
    const { operation: op } = await this.loadOperation(c, rows[0].provider_operation_key, ref);
    return this.#decode(rows[0], op);
  }
  match(view: RecoveryCommandView, kind: RecoveryKind, outboundId: string, attemptId: string) {
    if (
      view.receipt.kind !== kind ||
      view.receipt.outboundId !== outboundId ||
      view.receipt.sourceAttemptId !== attemptId
    )
      throw new OutboxError('IdentityConflict');
  }
  async state(c: PoolClient, op: ProviderOperation): Promise<OperationState> {
    const bounds = await this.policy(c),
      rows = (
        await c.query(
          `${this.#commandSelect()} WHERE r.provider_operation_key=$1 ORDER BY r.accepted_at,r.command_id LIMIT 33`,
          [op.providerOperationKey],
        )
      ).rows;
    if (rows.length > bounds.maxPerOperation) throw new OutboxError('Unavailable');
    const ids = new Set<string>();
    let failed = false,
      conflicted = false;
    for (const r of rows) {
      const view = this.#decode(r, op),
        observed = view.observation;
      if (!observed) continue;
      if (observed.assessment === 'conflicted') conflicted = true;
      if (observed.state === 'accepted_by_provider') ids.add(observed.providerMessageId!);
      if (observed.state === 'definitive_not_accepted') failed = true;
    }
    const attempts = (
      await c.query(
        `SELECT a.*,r.canonical_result FROM ${this.#q('send_attempts')} a LEFT JOIN ${this.#q('send_results')} r USING(attempt_id) WHERE a.provider_operation_key=$1 ORDER BY a.ordinal LIMIT 6`,
        [op.providerOperationKey],
      )
    ).rows;
    if (!attempts.length || attempts.length > 5) throw new OutboxError('Unavailable');
    for (const row of attempts) {
      try {
        const request = sendRequest(JSON.parse(row.canonical_request));
        if (
          JSON.stringify(request) !== row.canonical_request ||
          request.attemptId !== row.attempt_id ||
          sha(row.canonical_request) !== row.request_digest ||
          request.scope.tenantId !== row.tenant_id ||
          request.scope.accountId !== row.account_id ||
          request.outboundId !== row.outbound_id ||
          JSON.stringify(operationFrom(request, op.capability)) !== JSON.stringify(op)
        )
          throw Error();
        if (row.canonical_result !== null) {
          const result = carrierResult(JSON.parse(row.canonical_result), request);
          if (JSON.stringify(result) !== row.canonical_result) throw Error();
          if (result.status === 'accepted_by_provider') ids.add(result.providerMessageId);
          else failed = true;
        }
      } catch {
        throw new OutboxError('Unavailable');
      }
    }
    const callback =
      (
        await c.query(
          `SELECT 1 FROM ${this.#q('send_attempts')} a JOIN ${this.#q('callback_observations')} b USING(attempt_id) WHERE a.tenant_id=$1 AND a.account_id=$2 AND a.outbound_id=$3 LIMIT 1`,
          [op.scope.tenantId, op.scope.accountId, op.outboundId],
        )
      ).rowCount !== 0;
    const sorted = Object.freeze([...ids].sort());
    return {
      state:
        conflicted || ids.size > 1 || (ids.size > 0 && failed)
          ? 'conflicted'
          : ids.size
            ? 'accepted_by_provider'
            : failed
              ? 'definitive_not_accepted'
              : 'unknown',
      ids: sorted,
      callbackVeto: callback,
      commandCount: rows.length,
      latestCommandId: rows.length ? uuid(rows.at(-1)!.command_id) : null,
    };
  }
  async insertCommand(
    c: PoolClient,
    ref: Ref,
    kind: RecoveryKind,
    commandId: string,
    source: SendRequest,
    op: ProviderOperation,
    decision: RecoveryReceipt['decision'],
    code: RecoveryCode,
    newAttemptId: string | null,
  ): Promise<RecoveryCommandView> {
    this.#sameRef(op, ref);
    const bounds = await this.policy(c, true),
      counts = (
        await c.query(
          `SELECT recovery_count,(SELECT count(*)::integer FROM ${this.#q('send_recovery_commands')} WHERE provider_operation_key=$1) AS local FROM ${this.#q('send_policy_settings')} WHERE singleton`,
          [op.providerOperationKey],
        )
      ).rows[0];
    if (
      !counts ||
      !Number.isSafeInteger(counts.local) ||
      counts.local < 0 ||
      counts.local > bounds.maxPerOperation
    )
      throw new OutboxError('Unavailable');
    if (
      counts.recovery_count >= bounds.maxRecoveryCommands ||
      counts.local >= bounds.maxPerOperation
    )
      throw new OutboxError('Overloaded');
    const at = (await c.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS at")).rows[0]
        ?.at,
      receipt = recoveryReceipt({
        schemaVersion: 1,
        receiptId: randomUUID(),
        commandId,
        kind,
        outboundId: source.outboundId,
        sourceAttemptId: source.attemptId,
        providerOperationKey: op.providerOperationKey,
        operationDigest: operationDigest(op),
        decision,
        code,
        newAttemptId,
        acceptedAt: timestamp(at),
      }),
      semantic = this.#semantic(kind, commandId, source.outboundId, source.attemptId, op),
      raw = JSON.stringify(receipt);
    await c.query(
      `INSERT INTO ${this.#q('send_recovery_commands')} VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)`,
      [
        commandId,
        op.providerOperationKey,
        ref.scope.tenantId,
        ref.scope.accountId,
        op.outboundId,
        source.attemptId,
        kind,
        semantic,
        sha(semantic),
        raw,
        sha(raw),
        newAttemptId,
        at,
      ],
    );
    await c.query(
      `UPDATE ${this.#q('send_policy_settings')} SET recovery_count=recovery_count+1 WHERE singleton`,
    );
    return Object.freeze({ receipt, observation: null });
  }
  async observe(
    c: PoolClient,
    receipt: RecoveryReceipt,
    op: ProviderOperation,
    input: ProviderLookup,
    source: RecoveryObservation['source'],
  ): Promise<RecoveryCommandView> {
    const prior = await this.state(c, op);
    const conflicts =
      prior.state === 'conflicted' ||
      (input.state === 'accepted_by_provider' &&
        (prior.state === 'definitive_not_accepted' ||
          prior.ids.some((id) => id !== input.providerMessageId))) ||
      (input.state === 'definitive_not_accepted' && prior.ids.length > 0);
    const at = (await c.query("SELECT date_trunc('milliseconds',clock_timestamp()) AS at")).rows[0]
        ?.at,
      observation = recoveryObservation(
        {
          schemaVersion: 1,
          commandId: receipt.commandId,
          providerOperationKey: receipt.providerOperationKey,
          operationDigest: receipt.operationDigest,
          source,
          state: input.state,
          assessment: conflicts ? 'conflicted' : 'reported',
          providerMessageId: input.providerMessageId,
          observedAt: timestamp(at),
        },
        receipt,
      ),
      raw = JSON.stringify(observation),
      old = (
        await c.query(
          `SELECT canonical_observation FROM ${this.#q('send_recovery_observations')} WHERE command_id=$1`,
          [receipt.commandId],
        )
      ).rows;
    if (old.length) throw new OutboxError('IdentityConflict');
    await c.query(`INSERT INTO ${this.#q('send_recovery_observations')} VALUES($1,$2,$3,$4)`, [
      receipt.commandId,
      raw,
      sha(raw),
      at,
    ]);
    return Object.freeze({ receipt, observation });
  }
  async validateRetry(
    c: PoolClient,
    request: SendRequest,
    previous: SendRequest,
    op: ProviderOperation,
  ): Promise<void> {
    if (
      op.capability !== 'idempotent_fake_sms_v1' ||
      previous.providerOperationKey !== request.providerOperationKey
    )
      throw new OutboxError('Unavailable');
    const rows = (
      await c.query(`${this.#commandSelect()} WHERE r.new_attempt_id=$1`, [request.attemptId])
    ).rows;
    if (rows.length !== 1) throw new OutboxError('Unavailable');
    const { receipt } = this.#decode(rows[0], op);
    if (receipt.decision !== 'retry_reserved' || receipt.sourceAttemptId !== previous.attemptId)
      throw new OutboxError('Unavailable');
  }
}
