/** Complete PostgreSQL layout for a fresh channel profile. */
export const CHANNEL_SCHEMA_VERSION = 1;
export const CHANNEL_SCHEMA_MARKER = 'continuity-channel-0001';

export const CHANNEL_SCHEMA_SQL = `
-- Inbox and associations
CREATE TABLE schema_metadata (
  singleton boolean PRIMARY KEY CHECK(singleton),
  version smallint NOT NULL CHECK(version=1),
  runtime_role text NOT NULL,
  definition_digest text NOT NULL,
  catalog_snapshot jsonb NOT NULL,
  max_inbox integer NOT NULL CHECK(max_inbox BETWEEN 1 AND 10000),
  max_challenges integer NOT NULL CHECK(max_challenges BETWEEN 1 AND 10000),
  max_associations integer NOT NULL CHECK(max_associations BETWEEN 1 AND 10000),
  max_senders integer NOT NULL CHECK(max_senders BETWEEN 1 AND 10000)
);

CREATE TABLE admission (
  singleton boolean PRIMARY KEY CHECK(singleton),
  inbox_count integer NOT NULL DEFAULT 0 CHECK(inbox_count>=0),
  challenge_count integer NOT NULL DEFAULT 0 CHECK(challenge_count>=0),
  association_count integer NOT NULL DEFAULT 0 CHECK(association_count>=0),
  sender_count integer NOT NULL DEFAULT 0 CHECK(sender_count>=0)
);

CREATE TABLE sender_heads (
  tenant_id text NOT NULL,
  provider text NOT NULL,
  provider_account_id text NOT NULL,
  sender_id text NOT NULL,
  epoch bigint NOT NULL DEFAULT 0 CHECK(epoch>=0),
  active_epoch bigint CHECK(active_epoch>0 AND active_epoch<=epoch),
  PRIMARY KEY(tenant_id,provider,provider_account_id,sender_id)
);

CREATE TABLE associations (
  tenant_id text NOT NULL,
  provider text NOT NULL,
  provider_account_id text NOT NULL,
  sender_id text NOT NULL,
  epoch bigint NOT NULL CHECK(epoch>0),
  account_id text NOT NULL,
  conversation_id text NOT NULL,
  case_id text,
  activated_at timestamptz NOT NULL,
  revoked_at timestamptz,
  PRIMARY KEY(tenant_id,provider,provider_account_id,sender_id,epoch),
  FOREIGN KEY(tenant_id,provider,provider_account_id,sender_id) REFERENCES sender_heads(tenant_id,provider,provider_account_id,sender_id)
);

CREATE UNIQUE INDEX associations_active ON associations(tenant_id,provider,provider_account_id,sender_id) WHERE revoked_at IS NULL;

CREATE TABLE challenges (
  challenge_id uuid PRIMARY KEY,
  secret_digest text NOT NULL,
  tenant_id text NOT NULL,
  provider text NOT NULL,
  provider_account_id text NOT NULL,
  sender_id text NOT NULL,
  account_id text NOT NULL,
  conversation_id text NOT NULL,
  case_id text,
  expected_epoch bigint NOT NULL CHECK(expected_epoch>=0),
  issued_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL CHECK(expires_at>issued_at),
  attempts integer NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
  consumed_at timestamptz,
  FOREIGN KEY(tenant_id,provider,provider_account_id,sender_id) REFERENCES sender_heads(tenant_id,provider,provider_account_id,sender_id)
);

CREATE TABLE conversations (
  tenant_id text NOT NULL,
  account_id text NOT NULL,
  conversation_id text NOT NULL,
  last_sequence bigint NOT NULL DEFAULT 0 CHECK(last_sequence>=0),
  PRIMARY KEY(tenant_id,account_id,conversation_id)
);

CREATE TABLE inbox (
  receipt_id uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  provider text NOT NULL,
  provider_account_id text NOT NULL,
  event_id text NOT NULL,
  message_id text NOT NULL,
  account_id text NOT NULL,
  conversation_id text NOT NULL,
  association_epoch bigint NOT NULL,
  canonical_payload text NOT NULL,
  wire_json text NOT NULL,
  acceptance_sequence bigint NOT NULL CHECK(acceptance_sequence>0),
  accepted_at timestamptz NOT NULL,
  UNIQUE(tenant_id,provider,provider_account_id,event_id),
  UNIQUE(tenant_id,account_id,conversation_id,acceptance_sequence),
  FOREIGN KEY(tenant_id,account_id,conversation_id) REFERENCES conversations(tenant_id,account_id,conversation_id)
);

CREATE TABLE processing_intents (
  receipt_id uuid PRIMARY KEY REFERENCES inbox(receipt_id),
  operation_key uuid NOT NULL UNIQUE,
  state text NOT NULL,
  claim_epoch bigint NOT NULL DEFAULT 0 CHECK(claim_epoch>=0),
  claim_owner uuid,
  claim_until timestamptz,
  claim_kind text CHECK(claim_kind IN('dispatch','reconcile')),
  attempt_count smallint NOT NULL DEFAULT 0 CHECK(attempt_count BETWEEN 0 AND 5),
  next_attempt_at timestamptz,
  possible_external boolean NOT NULL DEFAULT false,
  external_receipt_id uuid,
  last_code text NOT NULL DEFAULT 'none' CHECK(last_code IN('none','association_required','adapter_invalid','adapter_unavailable','operation_conflict','claim_lost','accepted','lookup_absent')),
  CONSTRAINT processing_intents_state_check CHECK(state IN('pending','running','dispatched','blocked','exhausted','uncertain')),
  CONSTRAINT processing_claim_shape CHECK((claim_owner IS NULL)=(claim_until IS NULL) AND (claim_owner IS NULL)=(claim_kind IS NULL)),
  CONSTRAINT processing_possible_state CHECK(NOT possible_external OR state IN('uncertain','dispatched')),
  CONSTRAINT processing_dispatched_receipt CHECK((state='dispatched')=(external_receipt_id IS NOT NULL)),
  CONSTRAINT processing_identity_pair UNIQUE(receipt_id,operation_key)
);

-- Dispatch claims and results
CREATE INDEX dispatch_active ON processing_intents(claim_until) WHERE claim_owner IS NOT NULL;

CREATE TABLE dispatch_settings (
  singleton boolean PRIMARY KEY CHECK(singleton),
  max_active smallint NOT NULL CHECK(max_active BETWEEN 1 AND 4),
  max_attempts smallint NOT NULL CHECK(max_attempts BETWEEN 1 AND 5),
  lease_ms integer NOT NULL CHECK(lease_ms BETWEEN 500 AND 30000),
  retry_delay_ms integer NOT NULL CHECK(retry_delay_ms BETWEEN 20 AND 5000)
);

CREATE TABLE dispatch_plans (
  receipt_id uuid PRIMARY KEY,
  operation_key uuid NOT NULL UNIQUE,
  payload_json text NOT NULL CHECK(octet_length(payload_json)<=32768),
  payload_digest text NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),
  prepared_at timestamptz NOT NULL,
  association_epoch bigint NOT NULL CHECK(association_epoch>0),
  FOREIGN KEY(receipt_id,operation_key) REFERENCES processing_intents(receipt_id,operation_key)
);

CREATE TABLE dispatch_attempts (
  receipt_id uuid NOT NULL REFERENCES processing_intents(receipt_id),
  epoch bigint NOT NULL CHECK(epoch>0),
  owner_id uuid NOT NULL,
  started_at timestamptz NOT NULL,
  finished_at timestamptz,
  disposition text NOT NULL CHECK(disposition IN('started','accepted','timeout','adapter_unavailable','adapter_invalid','association_required','operation_conflict','lease_expired')),
  PRIMARY KEY(receipt_id,epoch),
  CHECK((disposition='started')=(finished_at IS NULL))
);

-- Outbound routes and delivery
CREATE TABLE outbox_settings (
  singleton boolean PRIMARY KEY CHECK(singleton),
  receiver_id uuid NOT NULL UNIQUE,
  max_replies integer NOT NULL CHECK(max_replies BETWEEN 1 AND 10000),
  max_routes integer NOT NULL CHECK(max_routes BETWEEN 1 AND 10000),
  max_attempts smallint NOT NULL CHECK(max_attempts BETWEEN 1 AND 5)
);

CREATE TABLE outbox_admission (
  singleton boolean PRIMARY KEY CHECK(singleton),
  reply_count integer NOT NULL CHECK(reply_count>=0),
  route_count integer NOT NULL CHECK(route_count>=0)
);

CREATE TABLE reply_intents (
  tenant_id text NOT NULL,
  account_id text NOT NULL,
  outbound_id uuid NOT NULL,
  receipt_id uuid NOT NULL UNIQUE,
  conversation_id text NOT NULL,
  case_id text NOT NULL,
  response_id text NOT NULL,
  canonical_payload text NOT NULL CHECK(octet_length(canonical_payload)<=32768),
  intent_digest text NOT NULL CHECK(intent_digest ~ '^[0-9a-f]{64}$'),
  body_digest text NOT NULL CHECK(body_digest ~ '^[0-9a-f]{64}$'),
  accepted_at timestamptz NOT NULL,
  PRIMARY KEY(tenant_id,account_id,outbound_id)
);

CREATE INDEX reply_pending ON reply_intents(tenant_id,account_id,conversation_id,case_id,accepted_at,outbound_id);

CREATE TABLE outbound_routes (
  tenant_id text NOT NULL,
  account_id text NOT NULL,
  conversation_id text NOT NULL,
  case_id text NOT NULL,
  provider text NOT NULL,
  provider_account_id text NOT NULL,
  version bigint NOT NULL CHECK(version>0),
  sender_id text,
  association_epoch bigint CHECK(association_epoch>0),
  suppressed boolean NOT NULL,
  CHECK((sender_id IS NULL)=(association_epoch IS NULL)),
  PRIMARY KEY(tenant_id,account_id,conversation_id)
);

CREATE TABLE send_attempts (
  attempt_id uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  account_id text NOT NULL,
  outbound_id uuid NOT NULL,
  ordinal smallint NOT NULL CHECK(ordinal BETWEEN 1 AND 5),
  provider_operation_key uuid NOT NULL,
  canonical_request text NOT NULL CHECK(octet_length(canonical_request)<=32768),
  request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
  reserved_at timestamptz NOT NULL,
  UNIQUE(tenant_id,account_id,outbound_id,ordinal),
  FOREIGN KEY(tenant_id,account_id,outbound_id) REFERENCES reply_intents(tenant_id,account_id,outbound_id)
);

CREATE TABLE send_results (
  attempt_id uuid PRIMARY KEY REFERENCES send_attempts(attempt_id),
  canonical_result text NOT NULL CHECK(octet_length(canonical_result)<=8192),
  observed_at timestamptz NOT NULL
);

-- Provider callbacks
CREATE TABLE callback_settings (
  singleton boolean PRIMARY KEY CHECK(singleton),
  rule_version smallint NOT NULL CHECK(rule_version=1),
  max_global integer NOT NULL CHECK(max_global BETWEEN 1 AND 100000),
  max_per_attempt smallint NOT NULL CHECK(max_per_attempt BETWEEN 1 AND 32)
);

CREATE TABLE callback_admission (
  singleton boolean PRIMARY KEY CHECK(singleton),
  callback_count integer NOT NULL CHECK(callback_count>=0)
);

CREATE TABLE callback_observations (
  tenant_id text NOT NULL,
  provider text NOT NULL,
  provider_account_id text NOT NULL,
  event_id text NOT NULL,
  receipt_id uuid NOT NULL UNIQUE,
  attempt_id uuid NOT NULL REFERENCES send_attempts(attempt_id),
  ordinal smallint NOT NULL CHECK(ordinal BETWEEN 1 AND 32),
  canonical_payload text NOT NULL CHECK(octet_length(canonical_payload)<=4096),
  payload_digest text NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),
  first_wire text NOT NULL CHECK(octet_length(first_wire)<=4096),
  accepted_at timestamptz NOT NULL,
  PRIMARY KEY(tenant_id,provider,provider_account_id,event_id),
  UNIQUE(attempt_id,ordinal)
);

-- Provider operations and recovery
CREATE TABLE send_policy_settings (
  singleton boolean PRIMARY KEY CHECK(singleton),
  ordinary_unknown text NOT NULL CHECK(ordinary_unknown='hold_no_resend'),
  idempotent_unknown text NOT NULL CHECK(idempotent_unknown='explicit_same_key_only'),
  max_recovery_commands integer NOT NULL CHECK(max_recovery_commands BETWEEN 1 AND 100000),
  max_per_operation smallint NOT NULL CHECK(max_per_operation BETWEEN 1 AND 32),
  recovery_count integer NOT NULL CHECK(recovery_count>=0)
);

CREATE TABLE send_operations (
  provider_operation_key uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  account_id text NOT NULL,
  outbound_id uuid NOT NULL,
  provider text NOT NULL,
  provider_account_id text NOT NULL,
  first_attempt_id uuid NOT NULL UNIQUE REFERENCES send_attempts(attempt_id) DEFERRABLE INITIALLY DEFERRED,
  capability text NOT NULL CHECK(capability IN('ordinary_fake_sms_v1','idempotent_fake_sms_v1')),
  canonical_operation text NOT NULL CHECK(octet_length(canonical_operation)<=32768),
  operation_digest text NOT NULL CHECK(operation_digest ~ '^[0-9a-f]{64}$'),
  first_request_digest text NOT NULL CHECK(first_request_digest ~ '^[0-9a-f]{64}$'),
  admission_proof text NOT NULL CHECK(octet_length(admission_proof)<=4096),
  admission_digest text NOT NULL CHECK(admission_digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  UNIQUE(tenant_id,account_id,outbound_id,provider_operation_key),
  FOREIGN KEY(tenant_id,account_id,outbound_id) REFERENCES reply_intents(tenant_id,account_id,outbound_id)
);

CREATE TABLE send_recovery_commands (
  command_id uuid PRIMARY KEY,
  provider_operation_key uuid NOT NULL REFERENCES send_operations(provider_operation_key),
  tenant_id text NOT NULL,
  account_id text NOT NULL,
  outbound_id uuid NOT NULL,
  source_attempt_id uuid NOT NULL REFERENCES send_attempts(attempt_id),
  kind text NOT NULL CHECK(kind IN('reconcile','retry')),
  canonical_command text NOT NULL CHECK(octet_length(canonical_command)<=4096),
  command_digest text NOT NULL CHECK(command_digest ~ '^[0-9a-f]{64}$'),
  receipt_json text NOT NULL CHECK(octet_length(receipt_json)<=4096),
  receipt_digest text NOT NULL CHECK(receipt_digest ~ '^[0-9a-f]{64}$'),
  new_attempt_id uuid UNIQUE REFERENCES send_attempts(attempt_id) DEFERRABLE INITIALLY DEFERRED,
  accepted_at timestamptz NOT NULL,
  FOREIGN KEY(tenant_id,account_id,outbound_id,provider_operation_key) REFERENCES send_operations(tenant_id,account_id,outbound_id,provider_operation_key)
);

CREATE INDEX recovery_operation ON send_recovery_commands(provider_operation_key,accepted_at,command_id);

CREATE TABLE send_recovery_observations (
  command_id uuid PRIMARY KEY REFERENCES send_recovery_commands(command_id),
  canonical_observation text NOT NULL CHECK(octet_length(canonical_observation)<=2048),
  observation_digest text NOT NULL CHECK(observation_digest ~ '^[0-9a-f]{64}$'),
  observed_at timestamptz NOT NULL
);

ALTER TABLE send_attempts ADD CONSTRAINT send_attempts_operation_key FOREIGN KEY(tenant_id,account_id,outbound_id,provider_operation_key) REFERENCES send_operations(tenant_id,account_id,outbound_id,provider_operation_key);

-- Native session bindings
CREATE TABLE native_settings (
  singleton boolean PRIMARY KEY CHECK(singleton),
  max_bindings integer NOT NULL CHECK(max_bindings BETWEEN 1 AND 1024),
  binding_count integer NOT NULL CHECK(binding_count>=0)
);

CREATE TABLE native_bindings (
  binding_id uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  provider text NOT NULL CHECK(provider='livekit'),
  provider_account_id text NOT NULL,
  account_id text NOT NULL,
  conversation_id text NOT NULL,
  case_id text NOT NULL,
  room_id text NOT NULL,
  participant_id text NOT NULL,
  bearer_digest text NOT NULL UNIQUE CHECK(bearer_digest ~ '^[0-9a-f]{64}$'),
  canonical_binding text NOT NULL CHECK(octet_length(canonical_binding)<=4096),
  binding_digest text NOT NULL CHECK(binding_digest ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL CHECK(expires_at>published_at),
  revoked_at timestamptz,
  FOREIGN KEY(tenant_id,account_id,conversation_id) REFERENCES conversations(tenant_id,account_id,conversation_id)
);

-- Response observations
CREATE TABLE communication_settings (
  singleton boolean PRIMARY KEY CHECK(singleton),
  profile_id uuid NOT NULL UNIQUE,
  max_responses integer NOT NULL CHECK(max_responses BETWEEN 1 AND 10000),
  max_observations integer NOT NULL CHECK(max_observations BETWEEN 1 AND 100000),
  max_observations_per_response integer NOT NULL CHECK(max_observations_per_response BETWEEN 1 AND 64),
  response_count integer NOT NULL CHECK(response_count>=0),
  observation_count integer NOT NULL CHECK(observation_count>=0)
);

CREATE TABLE native_responses (
  response_id uuid PRIMARY KEY,
  generation_id uuid NOT NULL,
  sdk_speech_id text NOT NULL,
  binding_id uuid NOT NULL REFERENCES native_bindings(binding_id),
  input_receipt_id uuid NOT NULL,
  operation_key uuid NOT NULL,
  tenant_id text NOT NULL,
  account_id text NOT NULL,
  conversation_id text NOT NULL,
  case_id text NOT NULL,
  canonical_anchor text NOT NULL CHECK(octet_length(canonical_anchor)<=8192),
  anchor_digest text NOT NULL CHECK(anchor_digest ~ '^[0-9a-f]{64}$'),
  receipt_id uuid NOT NULL UNIQUE,
  response_sequence bigint NOT NULL CHECK(response_sequence>0),
  accepted_at timestamptz NOT NULL,
  UNIQUE(binding_id,generation_id),
  UNIQUE(binding_id,sdk_speech_id),
  UNIQUE(response_id,binding_id),
  UNIQUE(tenant_id,account_id,conversation_id,response_sequence),
  FOREIGN KEY(input_receipt_id,operation_key) REFERENCES processing_intents(receipt_id,operation_key)
);

CREATE TABLE native_observations (
  binding_id uuid NOT NULL,
  source text NOT NULL CHECK(source IN('agent_sdk','browser_client')),
  event_id uuid NOT NULL,
  response_id uuid NOT NULL,
  canonical_payload text NOT NULL CHECK(octet_length(canonical_payload)<=32768),
  payload_digest text NOT NULL CHECK(payload_digest ~ '^[0-9a-f]{64}$'),
  receipt_id uuid NOT NULL UNIQUE,
  observation_sequence bigint NOT NULL CHECK(observation_sequence>0),
  accepted_at timestamptz NOT NULL,
  PRIMARY KEY(binding_id,source,event_id),
  UNIQUE(response_id,observation_sequence),
  FOREIGN KEY(response_id,binding_id) REFERENCES native_responses(response_id,binding_id)
);

CREATE INDEX native_responses_scope ON native_responses(tenant_id,account_id,conversation_id,response_sequence);

CREATE INDEX native_observations_response ON native_observations(response_id,observation_sequence);

-- Result receipts and read indexes
CREATE TABLE result_receipts (
  delivery_id uuid PRIMARY KEY,
  tenant_id text NOT NULL,
  account_id text NOT NULL,
  work_id uuid NOT NULL,
  attempt_id uuid NOT NULL,
  result_sha256 text NOT NULL CHECK(result_sha256 ~ '^[0-9a-f]{64}$'),
  recipient_id text NOT NULL,
  case_id text NOT NULL,
  conversation_id text NOT NULL,
  outbound_id uuid NOT NULL,
  canonical_intent text NOT NULL CHECK(octet_length(canonical_intent) BETWEEN 1 AND 16384),
  UNIQUE(tenant_id,account_id,outbound_id),
  FOREIGN KEY(tenant_id,account_id,outbound_id) REFERENCES reply_intents(tenant_id,account_id,outbound_id)
);

CREATE INDEX dispatch_due
  ON processing_intents(receipt_id) WHERE state IN ('pending','running','uncertain');

CREATE INDEX attempts_operation ON send_attempts(provider_operation_key,ordinal);

CREATE INDEX recovery_outbound ON send_recovery_commands(tenant_id,account_id,outbound_id);
`;
