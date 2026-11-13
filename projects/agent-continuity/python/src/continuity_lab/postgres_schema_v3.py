"""Additive Phase E catalog for PostgreSQL v3; serving never executes this DDL.

CHECK definitions were probed against the pinned PostgreSQL 18 server. Original
inquiry and authority columns/JSON remain unchanged; only the continuation state
constraint extends to completed/cancelled. Legacy consent is never backfilled.
"""

CONTROL_STATE_CHECK = "CHECK(state IN ('ready','running','retry_wait','inquiry_complete','waiting','intent_committed','failed','uncertain','completed','cancelled'))"

DEFINITIONS: dict[str, str] = {
    "mutation_effects": '(intent_id TEXT COLLATE "C" CONSTRAINT mutation_effects_pk PRIMARY KEY, '
    'task_id TEXT COLLATE "C" NOT NULL, state TEXT COLLATE "C" NOT NULL, '
    "generation BIGINT NOT NULL, attempt_no BIGINT NOT NULL, dispatch_count "
    'BIGINT NOT NULL, active_attempt_id TEXT COLLATE "C", result_json TEXT '
    'COLLATE "C", error_code TEXT COLLATE "C", dispatched_at TEXT COLLATE '
    '"C", updated_at TEXT COLLATE "C" NOT NULL, CONSTRAINT effects_intent_fk '
    "FOREIGN KEY(intent_id) REFERENCES {schema}.action_intents(intent_id), "
    "CONSTRAINT effects_case_fk FOREIGN KEY(task_id) REFERENCES "
    "{schema}.cases(task_id), CONSTRAINT effects_task_key UNIQUE(task_id), "
    "CONSTRAINT effects_state CHECK(state IN "
    "('pending','claimed','dispatched','succeeded','failed','uncertain','cancelled')), "
    "CONSTRAINT effects_generation CHECK(generation>=0), CONSTRAINT "
    "effects_attempt CHECK(attempt_no BETWEEN 0 AND 100), CONSTRAINT "
    "effects_dispatch_count CHECK(dispatch_count BETWEEN 0 AND 100), "
    "CONSTRAINT effects_result CHECK((state='succeeded')=(result_json IS NOT "
    "NULL)), CONSTRAINT effects_error CHECK(error_code IS NULL OR error_code "
    "IN "
    "('supplier_rejected','dependency_unavailable','deadline_expired','ambiguous_outcome','attempts_exhausted')), "
    "CONSTRAINT effects_dispatch_time CHECK((dispatch_count=0)=(dispatched_at "
    "IS NULL)))",
    "mutation_attempts": '(attempt_id TEXT COLLATE "C" CONSTRAINT mutation_attempts_pk PRIMARY '
    'KEY, intent_id TEXT COLLATE "C" NOT NULL, attempt_no BIGINT NOT NULL, '
    'state TEXT COLLATE "C" NOT NULL, started_at TEXT COLLATE "C" NOT NULL, '
    'finished_at TEXT COLLATE "C", error_code TEXT COLLATE "C", CONSTRAINT '
    "mutation_attempt_effect_fk FOREIGN KEY(intent_id) REFERENCES "
    "{schema}.mutation_effects(intent_id), CONSTRAINT "
    "mutation_attempt_sequence_key UNIQUE(intent_id,attempt_no), CONSTRAINT "
    "mutation_attempt_number CHECK(attempt_no BETWEEN 1 AND 100), CONSTRAINT "
    "mutation_attempt_state CHECK(state IN "
    "('started','interrupted','succeeded','failed','uncertain','cancelled')), "
    "CONSTRAINT mutation_attempt_finished "
    "CHECK((state='started')=(finished_at IS NULL)), CONSTRAINT "
    "mutation_attempt_error CHECK((state IN "
    "('failed','uncertain'))=(error_code IS NOT NULL)), CONSTRAINT "
    "mutation_attempt_error_code CHECK(error_code IS NULL OR error_code IN "
    "('supplier_rejected','dependency_unavailable','deadline_expired','ambiguous_outcome','attempts_exhausted')))",
    "cancellation_commands": '(cancellation_id TEXT COLLATE "C" CONSTRAINT '
    'cancellation_commands_pk PRIMARY KEY, scope_id TEXT COLLATE "C" NOT '
    'NULL, task_id TEXT COLLATE "C" NOT NULL, actor_id TEXT COLLATE "C" '
    'NOT NULL, command_id TEXT COLLATE "C" NOT NULL, payload_json TEXT '
    'COLLATE "C" NOT NULL, disposition TEXT COLLATE "C" NOT NULL, '
    'created_at TEXT COLLATE "C" NOT NULL, CONSTRAINT '
    "cancellation_case_fk FOREIGN KEY(task_id,scope_id) REFERENCES "
    "{schema}.cases(task_id,scope_id), CONSTRAINT "
    "cancellation_scoped_command_key UNIQUE(scope_id,command_id), "
    "CONSTRAINT cancellation_disposition CHECK(disposition IN "
    "('cancelled_before_commit','cancelled_before_dispatch','requested_best_effort','already_terminal')), "
    "CONSTRAINT cancellation_payload CHECK(length(payload_json) BETWEEN "
    "1 AND 2048))",
    "business_outcomes": '(task_id TEXT COLLATE "C" CONSTRAINT business_outcomes_pk PRIMARY KEY, '
    'payload_json TEXT COLLATE "C" NOT NULL, created_at TEXT COLLATE "C" NOT '
    "NULL, CONSTRAINT outcome_case_fk FOREIGN KEY(task_id) REFERENCES "
    "{schema}.cases(task_id), CONSTRAINT outcome_payload "
    "CHECK(length(payload_json) BETWEEN 1 AND 65536))",
    "completion_events": '(event_id TEXT COLLATE "C" CONSTRAINT completion_events_pk PRIMARY KEY, '
    'task_id TEXT COLLATE "C" NOT NULL, payload_json TEXT COLLATE "C" NOT '
    'NULL, created_at TEXT COLLATE "C" NOT NULL, CONSTRAINT '
    "completion_task_key UNIQUE(task_id), CONSTRAINT completion_outcome_fk "
    "FOREIGN KEY(task_id) REFERENCES {schema}.business_outcomes(task_id), "
    "CONSTRAINT completion_payload CHECK(length(payload_json) BETWEEN 1 AND "
    "65536))",
    "completion_deliveries": '(event_id TEXT COLLATE "C" CONSTRAINT completion_deliveries_pk '
    'PRIMARY KEY, target_id TEXT COLLATE "C", state TEXT COLLATE "C" NOT '
    "NULL, generation BIGINT NOT NULL, attempts BIGINT NOT NULL, "
    'policy_json TEXT COLLATE "C" NOT NULL, next_attempt_at TEXT COLLATE '
    '"C", error_code TEXT COLLATE "C", updated_at TEXT COLLATE "C" NOT '
    "NULL, CONSTRAINT delivery_target_bound CHECK(target_id IS NOT NULL "
    "OR attempts=0), CONSTRAINT delivery_event_fk FOREIGN KEY(event_id) "
    "REFERENCES {schema}.completion_events(event_id), CONSTRAINT "
    "delivery_state CHECK(state IN "
    "('pending','delivering','delivered','exhausted')), CONSTRAINT "
    "delivery_generation CHECK(generation>=0), CONSTRAINT "
    "delivery_attempts CHECK(attempts BETWEEN 0 AND 100), CONSTRAINT "
    "delivery_due CHECK((state='pending')=(next_attempt_at IS NOT "
    "NULL)), CONSTRAINT delivery_error CHECK(error_code IS NULL OR "
    "error_code IN ('dependency_unavailable','delivery_exhausted')), "
    "CONSTRAINT delivery_policy CHECK(length(policy_json) BETWEEN 1 AND "
    "256))",
}

COLUMNS: dict[str, tuple[str, ...]] = {
    "mutation_effects": (
        "intent_id",
        "task_id",
        "state",
        "generation",
        "attempt_no",
        "dispatch_count",
        "active_attempt_id",
        "result_json",
        "error_code",
        "dispatched_at",
        "updated_at",
    ),
    "mutation_attempts": (
        "attempt_id",
        "intent_id",
        "attempt_no",
        "state",
        "started_at",
        "finished_at",
        "error_code",
    ),
    "cancellation_commands": (
        "cancellation_id",
        "scope_id",
        "task_id",
        "actor_id",
        "command_id",
        "payload_json",
        "disposition",
        "created_at",
    ),
    "business_outcomes": ("task_id", "payload_json", "created_at"),
    "completion_events": ("event_id", "task_id", "payload_json", "created_at"),
    "completion_deliveries": (
        "event_id",
        "target_id",
        "state",
        "generation",
        "attempts",
        "policy_json",
        "next_attempt_at",
        "error_code",
        "updated_at",
    ),
}

COLUMN_SPECS: dict[str, dict[str, tuple[str, bool]]] = {
    "mutation_effects": {
        "intent_id": ("text", True),
        "task_id": ("text", True),
        "state": ("text", True),
        "generation": ("bigint", True),
        "attempt_no": ("bigint", True),
        "dispatch_count": ("bigint", True),
        "active_attempt_id": ("text", False),
        "result_json": ("text", False),
        "error_code": ("text", False),
        "dispatched_at": ("text", False),
        "updated_at": ("text", True),
    },
    "mutation_attempts": {
        "attempt_id": ("text", True),
        "intent_id": ("text", True),
        "attempt_no": ("bigint", True),
        "state": ("text", True),
        "started_at": ("text", True),
        "finished_at": ("text", False),
        "error_code": ("text", False),
    },
    "cancellation_commands": {
        "cancellation_id": ("text", True),
        "scope_id": ("text", True),
        "task_id": ("text", True),
        "actor_id": ("text", True),
        "command_id": ("text", True),
        "payload_json": ("text", True),
        "disposition": ("text", True),
        "created_at": ("text", True),
    },
    "business_outcomes": {
        "task_id": ("text", True),
        "payload_json": ("text", True),
        "created_at": ("text", True),
    },
    "completion_events": {
        "event_id": ("text", True),
        "task_id": ("text", True),
        "payload_json": ("text", True),
        "created_at": ("text", True),
    },
    "completion_deliveries": {
        "event_id": ("text", True),
        "target_id": ("text", False),
        "state": ("text", True),
        "generation": ("bigint", True),
        "attempts": ("bigint", True),
        "policy_json": ("text", True),
        "next_attempt_at": ("text", False),
        "error_code": ("text", False),
        "updated_at": ("text", True),
    },
}

CHECK_DEFINITIONS: dict[str, str] = {
    "effects_state": "CHECK ((state = ANY (ARRAY['pending'::text, 'claimed'::text, "
    "'dispatched'::text, 'succeeded'::text, 'failed'::text, 'uncertain'::text, "
    "'cancelled'::text])))",
    "effects_generation": "CHECK ((generation >= 0))",
    "effects_attempt": "CHECK (((attempt_no >= 0) AND (attempt_no <= 100)))",
    "effects_dispatch_count": "CHECK (((dispatch_count >= 0) AND (dispatch_count <= 100)))",
    "effects_result": "CHECK (((state = 'succeeded'::text) = (result_json IS NOT NULL)))",
    "effects_error": "CHECK (((error_code IS NULL) OR (error_code = ANY "
    "(ARRAY['supplier_rejected'::text, 'dependency_unavailable'::text, "
    "'deadline_expired'::text, 'ambiguous_outcome'::text, "
    "'attempts_exhausted'::text]))))",
    "effects_dispatch_time": "CHECK (((dispatch_count = 0) = (dispatched_at IS NULL)))",
    "mutation_attempt_number": "CHECK (((attempt_no >= 1) AND (attempt_no <= 100)))",
    "mutation_attempt_state": "CHECK ((state = ANY (ARRAY['started'::text, 'interrupted'::text, "
    "'succeeded'::text, 'failed'::text, 'uncertain'::text, "
    "'cancelled'::text])))",
    "mutation_attempt_finished": "CHECK (((state = 'started'::text) = (finished_at IS NULL)))",
    "mutation_attempt_error": "CHECK (((state = ANY (ARRAY['failed'::text, 'uncertain'::text])) = "
    "(error_code IS NOT NULL)))",
    "mutation_attempt_error_code": "CHECK (((error_code IS NULL) OR (error_code = ANY "
    "(ARRAY['supplier_rejected'::text, "
    "'dependency_unavailable'::text, 'deadline_expired'::text, "
    "'ambiguous_outcome'::text, 'attempts_exhausted'::text]))))",
    "cancellation_disposition": "CHECK ((disposition = ANY "
    "(ARRAY['cancelled_before_commit'::text, "
    "'cancelled_before_dispatch'::text, "
    "'requested_best_effort'::text, 'already_terminal'::text])))",
    "cancellation_payload": "CHECK (((length(payload_json) >= 1) AND (length(payload_json) <= "
    "2048)))",
    "outcome_payload": "CHECK (((length(payload_json) >= 1) AND (length(payload_json) <= 65536)))",
    "completion_payload": "CHECK (((length(payload_json) >= 1) AND (length(payload_json) <= "
    "65536)))",
    "delivery_target_bound": "CHECK (((target_id IS NOT NULL) OR (attempts = 0)))",
    "delivery_state": "CHECK ((state = ANY (ARRAY['pending'::text, 'delivering'::text, "
    "'delivered'::text, 'exhausted'::text])))",
    "delivery_generation": "CHECK ((generation >= 0))",
    "delivery_attempts": "CHECK (((attempts >= 0) AND (attempts <= 100)))",
    "delivery_due": "CHECK (((state = 'pending'::text) = (next_attempt_at IS NOT NULL)))",
    "delivery_error": "CHECK (((error_code IS NULL) OR (error_code = ANY "
    "(ARRAY['dependency_unavailable'::text, 'delivery_exhausted'::text]))))",
    "delivery_policy": "CHECK (((length(policy_json) >= 1) AND (length(policy_json) <= 256)))",
    "controls_state": "CHECK ((state = ANY (ARRAY['ready'::text, 'running'::text, "
    "'retry_wait'::text, 'inquiry_complete'::text, 'waiting'::text, "
    "'intent_committed'::text, 'failed'::text, 'uncertain'::text, "
    "'completed'::text, 'cancelled'::text])))",
    "metadata_version": "CHECK ((version = 3))",
}

CHECK_TABLES: dict[str, str] = {
    "effects_state": "mutation_effects",
    "effects_generation": "mutation_effects",
    "effects_attempt": "mutation_effects",
    "effects_dispatch_count": "mutation_effects",
    "effects_result": "mutation_effects",
    "effects_error": "mutation_effects",
    "effects_dispatch_time": "mutation_effects",
    "mutation_attempt_number": "mutation_attempts",
    "mutation_attempt_state": "mutation_attempts",
    "mutation_attempt_finished": "mutation_attempts",
    "mutation_attempt_error": "mutation_attempts",
    "mutation_attempt_error_code": "mutation_attempts",
    "cancellation_disposition": "cancellation_commands",
    "cancellation_payload": "cancellation_commands",
    "outcome_payload": "business_outcomes",
    "completion_payload": "completion_events",
    "delivery_target_bound": "completion_deliveries",
    "delivery_state": "completion_deliveries",
    "delivery_generation": "completion_deliveries",
    "delivery_attempts": "completion_deliveries",
    "delivery_due": "completion_deliveries",
    "delivery_error": "completion_deliveries",
    "delivery_policy": "completion_deliveries",
    "controls_state": "execution_controls",
    "metadata_version": "schema_metadata",
}

KEYS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "mutation_effects_pk": ("mutation_effects", "p", ("intent_id",)),
    "effects_task_key": ("mutation_effects", "u", ("task_id",)),
    "mutation_attempts_pk": ("mutation_attempts", "p", ("attempt_id",)),
    "mutation_attempt_sequence_key": (
        "mutation_attempts",
        "u",
        ("intent_id", "attempt_no"),
    ),
    "cancellation_commands_pk": ("cancellation_commands", "p", ("cancellation_id",)),
    "cancellation_scoped_command_key": (
        "cancellation_commands",
        "u",
        ("scope_id", "command_id"),
    ),
    "business_outcomes_pk": ("business_outcomes", "p", ("task_id",)),
    "completion_events_pk": ("completion_events", "p", ("event_id",)),
    "completion_task_key": ("completion_events", "u", ("task_id",)),
    "completion_deliveries_pk": ("completion_deliveries", "p", ("event_id",)),
}

FOREIGN_KEYS: dict[str, tuple[str, tuple[str, ...], str, tuple[str, ...]]] = {
    "cancellation_case_fk": (
        "cancellation_commands",
        ("task_id", "scope_id"),
        "cases",
        ("task_id", "scope_id"),
    ),
    "effects_intent_fk": (
        "mutation_effects",
        ("intent_id",),
        "action_intents",
        ("intent_id",),
    ),
    "effects_case_fk": ("mutation_effects", ("task_id",), "cases", ("task_id",)),
    "mutation_attempt_effect_fk": (
        "mutation_attempts",
        ("intent_id",),
        "mutation_effects",
        ("intent_id",),
    ),
    "outcome_case_fk": ("business_outcomes", ("task_id",), "cases", ("task_id",)),
    "completion_outcome_fk": (
        "completion_events",
        ("task_id",),
        "business_outcomes",
        ("task_id",),
    ),
    "delivery_event_fk": (
        "completion_deliveries",
        ("event_id",),
        "completion_events",
        ("event_id",),
    ),
}

GRANTS: dict[str, tuple[str, ...]] = {
    "mutation_effects": ("SELECT", "INSERT", "UPDATE"),
    "mutation_attempts": ("SELECT", "INSERT", "UPDATE"),
    "cancellation_commands": ("SELECT", "INSERT"),
    "business_outcomes": ("SELECT", "INSERT"),
    "completion_events": ("SELECT", "INSERT"),
    "completion_deliveries": ("SELECT", "INSERT", "UPDATE"),
}

OPERATING_INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "cancellation_task_created_idx": (
        "cancellation_commands",
        ("task_id", "created_at", "cancellation_id"),
    ),
    "completion_delivery_due_idx": (
        "completion_deliveries",
        ("state", "next_attempt_at", "event_id"),
    ),
    "mutation_effect_state_idx": (
        "mutation_effects",
        ("state", "updated_at", "task_id"),
    ),
}
