"""Additive Phase D catalog for PostgreSQL v2; no serving DDL or mutable policy.

The original inquiry tables and historical import receipt remain unchanged.
Canonical CHECK output was probed against the pinned PostgreSQL 18 server.
"""

DEFINITIONS: dict[str, str] = {
    "cases": '(task_id TEXT COLLATE "C" CONSTRAINT cases_pk PRIMARY KEY, case_id TEXT COLLATE "C" NOT '
    'NULL, scope_id TEXT COLLATE "C" NOT NULL, actor_id TEXT COLLATE "C" NOT NULL, revision '
    'BIGINT NOT NULL, request_json TEXT COLLATE "C" NOT NULL, current_quote_id TEXT COLLATE '
    '"C", cancelled BOOLEAN NOT NULL, created_at TEXT COLLATE "C" NOT NULL, updated_at TEXT '
    'COLLATE "C" NOT NULL, CONSTRAINT cases_distinct_identity CHECK(case_id <> task_id), '
    "CONSTRAINT cases_identity_key UNIQUE (case_id), CONSTRAINT cases_task_scope_key UNIQUE "
    "(task_id, scope_id), CONSTRAINT cases_execution_fk FOREIGN KEY (task_id) REFERENCES "
    "{schema}.executions(task_id), CONSTRAINT cases_revision CHECK (revision >= 0), "
    "CONSTRAINT cases_scope CHECK (length(scope_id) BETWEEN 1 AND 128), CONSTRAINT "
    "cases_actor CHECK (length(actor_id) BETWEEN 1 AND 128), CONSTRAINT cases_payload CHECK "
    "(length(request_json) BETWEEN 1 AND 2048))",
    "quotes": '(quote_id TEXT COLLATE "C" CONSTRAINT quotes_pk PRIMARY KEY, task_id TEXT COLLATE "C" '
    'NOT NULL, revision BIGINT NOT NULL, payload_json TEXT COLLATE "C" NOT NULL, created_at '
    'TEXT COLLATE "C" NOT NULL, CONSTRAINT quotes_identity_revision_key UNIQUE (quote_id, '
    "task_id, revision), CONSTRAINT quotes_case_fk FOREIGN KEY (task_id) REFERENCES "
    "{schema}.cases(task_id), CONSTRAINT quotes_revision CHECK (revision >= 0), CONSTRAINT "
    "quotes_payload CHECK (length(payload_json) BETWEEN 1 AND 4096))",
    "confirmations": '(confirmation_id TEXT COLLATE "C" CONSTRAINT confirmations_pk PRIMARY KEY, '
    'task_id TEXT COLLATE "C" NOT NULL, scope_id TEXT COLLATE "C" NOT NULL, actor_id '
    'TEXT COLLATE "C" NOT NULL, command_id TEXT COLLATE "C" NOT NULL, payload_json '
    'TEXT COLLATE "C" NOT NULL, created_at TEXT COLLATE "C" NOT NULL, CONSTRAINT '
    "confirmations_identity_task_key UNIQUE (confirmation_id, task_id), CONSTRAINT "
    "confirmations_case_fk FOREIGN KEY (task_id, scope_id) REFERENCES "
    "{schema}.cases(task_id, scope_id), CONSTRAINT confirmations_scoped_command "
    "UNIQUE (scope_id, command_id), CONSTRAINT confirmations_command CHECK "
    "(length(command_id) BETWEEN 1 AND 128), CONSTRAINT confirmations_payload CHECK "
    "(length(payload_json) BETWEEN 1 AND 8192))",
    "action_intents": '(intent_id TEXT COLLATE "C" CONSTRAINT intents_pk PRIMARY KEY, task_id TEXT '
    'COLLATE "C" NOT NULL, scope_id TEXT COLLATE "C" NOT NULL, actor_id TEXT '
    'COLLATE "C" NOT NULL, revision BIGINT NOT NULL, quote_id TEXT COLLATE "C" NOT '
    'NULL, confirmation_id TEXT COLLATE "C" NOT NULL, effect_id TEXT COLLATE "C" '
    'NOT NULL, payload_json TEXT COLLATE "C" NOT NULL, created_at TEXT COLLATE "C" '
    "NOT NULL, CONSTRAINT intents_case_fk FOREIGN KEY (task_id, scope_id) "
    "REFERENCES {schema}.cases(task_id, scope_id), CONSTRAINT intents_quote_fk "
    "FOREIGN KEY (quote_id, task_id, revision) REFERENCES {schema}.quotes(quote_id, "
    "task_id, revision), CONSTRAINT intents_confirmation_fk FOREIGN KEY "
    "(confirmation_id, task_id) REFERENCES {schema}.confirmations(confirmation_id, "
    "task_id), CONSTRAINT intents_effect_key UNIQUE (effect_id), CONSTRAINT "
    "intents_case_revision UNIQUE (task_id, revision), CONSTRAINT intents_revision "
    "CHECK (revision >= 0), CONSTRAINT intents_payload CHECK (length(payload_json) "
    "BETWEEN 1 AND 16384))",
    "intent_dispatch": '(event_id TEXT COLLATE "C" CONSTRAINT intent_dispatch_pk PRIMARY KEY, '
    'intent_id TEXT COLLATE "C" NOT NULL, payload_json TEXT COLLATE "C" NOT NULL, '
    'created_at TEXT COLLATE "C" NOT NULL, CONSTRAINT intent_dispatch_intent_key '
    "UNIQUE (intent_id), CONSTRAINT intent_dispatch_intent_fk FOREIGN KEY "
    "(intent_id) REFERENCES {schema}.action_intents(intent_id), CONSTRAINT "
    "intent_dispatch_payload CHECK (length(payload_json) BETWEEN 1 AND 16384))",
    "execution_controls": "(\n"
    ' task_id TEXT COLLATE "C" CONSTRAINT execution_controls_pk PRIMARY KEY,\n'
    ' state TEXT COLLATE "C" NOT NULL,\n'
    ' policy_json TEXT COLLATE "C" NOT NULL,\n'
    ' deadline TEXT COLLATE "C" NOT NULL,\n'
    ' next_attempt_at TEXT COLLATE "C",\n'
    " version BIGINT NOT NULL,\n"
    ' last_failure TEXT COLLATE "C",\n'
    ' error_code TEXT COLLATE "C",\n'
    ' updated_at TEXT COLLATE "C" NOT NULL,\n'
    " CONSTRAINT controls_execution_fk FOREIGN KEY(task_id) REFERENCES "
    "{schema}.executions(task_id),\n"
    " CONSTRAINT controls_state CHECK (state IN "
    "('ready','running','retry_wait','inquiry_complete','waiting','intent_committed','failed','uncertain')),\n"
    " CONSTRAINT controls_version CHECK (version >= 0),\n"
    " CONSTRAINT controls_due CHECK ((state='retry_wait') = (next_attempt_at IS "
    "NOT NULL)),\n"
    " CONSTRAINT controls_failure CHECK (last_failure IS NULL OR last_failure "
    "IN ('transient','permanent','ambiguous')),\n"
    " CONSTRAINT controls_error CHECK (error_code IS NULL OR error_code IN "
    "('dependency_unavailable','permanent_failure','retry_exhausted','deadline_expired','ambiguous_outcome'))\n"
    ")",
    "execution_waits": "(\n"
    ' wait_id TEXT COLLATE "C" CONSTRAINT execution_waits_pk PRIMARY KEY,\n'
    ' task_id TEXT COLLATE "C" NOT NULL,\n'
    ' quote_json TEXT COLLATE "C" NOT NULL,\n'
    ' deadline TEXT COLLATE "C" NOT NULL,\n'
    ' state TEXT COLLATE "C" NOT NULL,\n'
    ' created_at TEXT COLLATE "C" NOT NULL,\n'
    ' finished_at TEXT COLLATE "C",\n'
    " CONSTRAINT waits_execution_fk FOREIGN KEY(task_id) REFERENCES "
    "{schema}.executions(task_id),\n"
    " CONSTRAINT waits_identity_task_key UNIQUE(wait_id,task_id),\n"
    " CONSTRAINT waits_state CHECK(state IN ('pending','consumed','expired')),\n"
    " CONSTRAINT waits_finished CHECK ((state='pending') = (finished_at IS NULL))\n"
    ")",
    "execution_signals": "(\n"
    ' signal_id TEXT COLLATE "C" CONSTRAINT execution_signals_pk PRIMARY KEY,\n'
    ' scope_id TEXT COLLATE "C" NOT NULL,\n'
    ' task_id TEXT COLLATE "C" NOT NULL,\n'
    ' actor_id TEXT COLLATE "C" NOT NULL,\n'
    ' event_id TEXT COLLATE "C" NOT NULL,\n'
    ' payload_json TEXT COLLATE "C" NOT NULL,\n'
    ' created_at TEXT COLLATE "C" NOT NULL,\n'
    " CONSTRAINT signals_execution_fk FOREIGN KEY(task_id) REFERENCES "
    "{schema}.executions(task_id),\n"
    " CONSTRAINT signals_scoped_event_key UNIQUE(scope_id,event_id),\n"
    " CONSTRAINT signals_identity_task_key UNIQUE(signal_id,task_id)\n"
    ")",
    "execution_signal_consumptions": "(\n"
    ' signal_id TEXT COLLATE "C" CONSTRAINT '
    "execution_signal_consumptions_pk PRIMARY KEY,\n"
    ' wait_id TEXT COLLATE "C" NOT NULL,\n'
    ' task_id TEXT COLLATE "C" NOT NULL,\n'
    ' created_at TEXT COLLATE "C" NOT NULL,\n'
    " CONSTRAINT consumptions_wait_key UNIQUE(wait_id),\n"
    " CONSTRAINT consumptions_signal_fk FOREIGN "
    "KEY(signal_id,task_id) REFERENCES "
    "{schema}.execution_signals(signal_id,task_id),\n"
    " CONSTRAINT consumptions_wait_fk FOREIGN KEY(wait_id,task_id) "
    "REFERENCES {schema}.execution_waits(wait_id,task_id)\n"
    ")",
}

COLUMNS: dict[str, tuple[str, ...]] = {
    "cases": (
        "task_id",
        "case_id",
        "scope_id",
        "actor_id",
        "revision",
        "request_json",
        "current_quote_id",
        "cancelled",
        "created_at",
        "updated_at",
    ),
    "quotes": ("quote_id", "task_id", "revision", "payload_json", "created_at"),
    "confirmations": (
        "confirmation_id",
        "task_id",
        "scope_id",
        "actor_id",
        "command_id",
        "payload_json",
        "created_at",
    ),
    "action_intents": (
        "intent_id",
        "task_id",
        "scope_id",
        "actor_id",
        "revision",
        "quote_id",
        "confirmation_id",
        "effect_id",
        "payload_json",
        "created_at",
    ),
    "intent_dispatch": ("event_id", "intent_id", "payload_json", "created_at"),
    "execution_controls": (
        "task_id",
        "state",
        "policy_json",
        "deadline",
        "next_attempt_at",
        "version",
        "last_failure",
        "error_code",
        "updated_at",
    ),
    "execution_waits": (
        "wait_id",
        "task_id",
        "quote_json",
        "deadline",
        "state",
        "created_at",
        "finished_at",
    ),
    "execution_signals": (
        "signal_id",
        "scope_id",
        "task_id",
        "actor_id",
        "event_id",
        "payload_json",
        "created_at",
    ),
    "execution_signal_consumptions": ("signal_id", "wait_id", "task_id", "created_at"),
}

COLUMN_SPECS: dict[str, dict[str, tuple[str, bool]]] = {
    "cases": {
        "task_id": ("text", True),
        "case_id": ("text", True),
        "scope_id": ("text", True),
        "actor_id": ("text", True),
        "revision": ("bigint", True),
        "request_json": ("text", True),
        "current_quote_id": ("text", False),
        "cancelled": ("boolean", True),
        "created_at": ("text", True),
        "updated_at": ("text", True),
    },
    "quotes": {
        "quote_id": ("text", True),
        "task_id": ("text", True),
        "revision": ("bigint", True),
        "payload_json": ("text", True),
        "created_at": ("text", True),
    },
    "confirmations": {
        "confirmation_id": ("text", True),
        "task_id": ("text", True),
        "scope_id": ("text", True),
        "actor_id": ("text", True),
        "command_id": ("text", True),
        "payload_json": ("text", True),
        "created_at": ("text", True),
    },
    "action_intents": {
        "intent_id": ("text", True),
        "task_id": ("text", True),
        "scope_id": ("text", True),
        "actor_id": ("text", True),
        "revision": ("bigint", True),
        "quote_id": ("text", True),
        "confirmation_id": ("text", True),
        "effect_id": ("text", True),
        "payload_json": ("text", True),
        "created_at": ("text", True),
    },
    "intent_dispatch": {
        "event_id": ("text", True),
        "intent_id": ("text", True),
        "payload_json": ("text", True),
        "created_at": ("text", True),
    },
    "execution_controls": {
        "task_id": ("text", True),
        "state": ("text", True),
        "policy_json": ("text", True),
        "deadline": ("text", True),
        "next_attempt_at": ("text", False),
        "version": ("bigint", True),
        "last_failure": ("text", False),
        "error_code": ("text", False),
        "updated_at": ("text", True),
    },
    "execution_waits": {
        "wait_id": ("text", True),
        "task_id": ("text", True),
        "quote_json": ("text", True),
        "deadline": ("text", True),
        "state": ("text", True),
        "created_at": ("text", True),
        "finished_at": ("text", False),
    },
    "execution_signals": {
        "signal_id": ("text", True),
        "scope_id": ("text", True),
        "task_id": ("text", True),
        "actor_id": ("text", True),
        "event_id": ("text", True),
        "payload_json": ("text", True),
        "created_at": ("text", True),
    },
    "execution_signal_consumptions": {
        "signal_id": ("text", True),
        "wait_id": ("text", True),
        "task_id": ("text", True),
        "created_at": ("text", True),
    },
}

CHECK_DEFINITIONS: dict[str, str] = {
    "cases_revision": "CHECK ((revision >= 0))",
    "cases_scope": "CHECK (((length(scope_id) >= 1) AND (length(scope_id) <= 128)))",
    "cases_actor": "CHECK (((length(actor_id) >= 1) AND (length(actor_id) <= 128)))",
    "cases_payload": "CHECK (((length(request_json) >= 1) AND (length(request_json) <= 2048)))",
    "quotes_revision": "CHECK ((revision >= 0))",
    "quotes_payload": "CHECK (((length(payload_json) >= 1) AND (length(payload_json) <= 4096)))",
    "confirmations_command": "CHECK (((length(command_id) >= 1) AND (length(command_id) <= 128)))",
    "confirmations_payload": "CHECK (((length(payload_json) >= 1) AND (length(payload_json) <= "
    "8192)))",
    "intents_revision": "CHECK ((revision >= 0))",
    "intents_payload": "CHECK (((length(payload_json) >= 1) AND (length(payload_json) <= 16384)))",
    "intent_dispatch_payload": "CHECK (((length(payload_json) >= 1) AND (length(payload_json) <= "
    "16384)))",
    "controls_state": "CHECK ((state = ANY (ARRAY['ready'::text, 'running'::text, 'retry_wait'::text, "
    "'inquiry_complete'::text, 'waiting'::text, 'intent_committed'::text, "
    "'failed'::text, 'uncertain'::text])))",
    "controls_version": "CHECK ((version >= 0))",
    "controls_due": "CHECK (((state = 'retry_wait'::text) = (next_attempt_at IS NOT NULL)))",
    "controls_failure": "CHECK (((last_failure IS NULL) OR (last_failure = ANY "
    "(ARRAY['transient'::text, 'permanent'::text, 'ambiguous'::text]))))",
    "controls_error": "CHECK (((error_code IS NULL) OR (error_code = ANY "
    "(ARRAY['dependency_unavailable'::text, 'permanent_failure'::text, "
    "'retry_exhausted'::text, 'deadline_expired'::text, "
    "'ambiguous_outcome'::text]))))",
    "waits_state": "CHECK ((state = ANY (ARRAY['pending'::text, 'consumed'::text, 'expired'::text])))",
    "waits_finished": "CHECK (((state = 'pending'::text) = (finished_at IS NULL)))",
    "metadata_version": "CHECK ((version = 2))",
    "metadata_state": "CHECK ((state = 'active'::text))",
    "cases_distinct_identity": "CHECK ((case_id <> task_id))",
}

CHECK_TABLES: dict[str, str] = {
    "cases_revision": "cases",
    "cases_scope": "cases",
    "cases_actor": "cases",
    "cases_payload": "cases",
    "quotes_revision": "quotes",
    "quotes_payload": "quotes",
    "confirmations_command": "confirmations",
    "confirmations_payload": "confirmations",
    "intents_revision": "action_intents",
    "intents_payload": "action_intents",
    "intent_dispatch_payload": "intent_dispatch",
    "controls_state": "execution_controls",
    "controls_version": "execution_controls",
    "controls_due": "execution_controls",
    "controls_failure": "execution_controls",
    "controls_error": "execution_controls",
    "waits_state": "execution_waits",
    "waits_finished": "execution_waits",
    "metadata_version": "schema_metadata",
    "metadata_state": "schema_metadata",
    "cases_distinct_identity": "cases",
}

KEYS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "cases_pk": ("cases", "p", ("task_id",)),
    "cases_task_scope_key": ("cases", "u", ("task_id", "scope_id")),
    "quotes_pk": ("quotes", "p", ("quote_id",)),
    "quotes_identity_revision_key": ("quotes", "u", ("quote_id", "task_id", "revision")),
    "confirmations_pk": ("confirmations", "p", ("confirmation_id",)),
    "confirmations_identity_task_key": ("confirmations", "u", ("confirmation_id", "task_id")),
    "confirmations_scoped_command": ("confirmations", "u", ("scope_id", "command_id")),
    "intents_pk": ("action_intents", "p", ("intent_id",)),
    "intents_effect_key": ("action_intents", "u", ("effect_id",)),
    "intents_case_revision": ("action_intents", "u", ("task_id", "revision")),
    "intent_dispatch_pk": ("intent_dispatch", "p", ("event_id",)),
    "intent_dispatch_intent_key": ("intent_dispatch", "u", ("intent_id",)),
    "waits_identity_task_key": ("execution_waits", "u", ("wait_id", "task_id")),
    "execution_controls_pk": ("execution_controls", "p", ("task_id",)),
    "execution_waits_pk": ("execution_waits", "p", ("wait_id",)),
    "execution_signals_pk": ("execution_signals", "p", ("signal_id",)),
    "signals_scoped_event_key": ("execution_signals", "u", ("scope_id", "event_id")),
    "signals_identity_task_key": ("execution_signals", "u", ("signal_id", "task_id")),
    "execution_signal_consumptions_pk": ("execution_signal_consumptions", "p", ("signal_id",)),
    "consumptions_wait_key": ("execution_signal_consumptions", "u", ("wait_id",)),
    "cases_identity_key": ("cases", "u", ("case_id",)),
}

FOREIGN_KEYS: dict[str, tuple[str, tuple[str, ...], str, tuple[str, ...]]] = {
    "cases_execution_fk": ("cases", ("task_id",), "executions", ("task_id",)),
    "quotes_case_fk": ("quotes", ("task_id",), "cases", ("task_id",)),
    "confirmations_case_fk": (
        "confirmations",
        ("task_id", "scope_id"),
        "cases",
        ("task_id", "scope_id"),
    ),
    "intents_case_fk": (
        "action_intents",
        ("task_id", "scope_id"),
        "cases",
        ("task_id", "scope_id"),
    ),
    "intents_quote_fk": (
        "action_intents",
        ("quote_id", "task_id", "revision"),
        "quotes",
        ("quote_id", "task_id", "revision"),
    ),
    "intents_confirmation_fk": (
        "action_intents",
        ("confirmation_id", "task_id"),
        "confirmations",
        ("confirmation_id", "task_id"),
    ),
    "intent_dispatch_intent_fk": (
        "intent_dispatch",
        ("intent_id",),
        "action_intents",
        ("intent_id",),
    ),
    "waits_execution_fk": ("execution_waits", ("task_id",), "executions", ("task_id",)),
    "controls_execution_fk": ("execution_controls", ("task_id",), "executions", ("task_id",)),
    "signals_execution_fk": ("execution_signals", ("task_id",), "executions", ("task_id",)),
    "consumptions_signal_fk": (
        "execution_signal_consumptions",
        ("signal_id", "task_id"),
        "execution_signals",
        ("signal_id", "task_id"),
    ),
    "consumptions_wait_fk": (
        "execution_signal_consumptions",
        ("wait_id", "task_id"),
        "execution_waits",
        ("wait_id", "task_id"),
    ),
}

GRANTS: dict[str, tuple[str, ...]] = {
    "cases": ("SELECT", "INSERT", "UPDATE"),
    "quotes": ("SELECT", "INSERT"),
    "confirmations": ("SELECT", "INSERT"),
    "action_intents": ("SELECT", "INSERT"),
    "intent_dispatch": ("SELECT", "INSERT"),
    "execution_controls": ("SELECT", "INSERT", "UPDATE"),
    "execution_waits": ("SELECT", "INSERT", "UPDATE"),
    "execution_signals": ("SELECT", "INSERT"),
    "execution_signal_consumptions": ("SELECT", "INSERT"),
}

# Ordinary non-unique btrees support bounded per-task history and cap lookups.
OPERATING_INDEXES: dict[str, tuple[str, tuple[str, ...]]] = {
    "quotes_task_idx": ("quotes", ("task_id",)),
    "confirmations_task_idx": ("confirmations", ("task_id",)),
    "signals_task_created_idx": ("execution_signals", ("task_id", "created_at", "signal_id")),
    "waits_task_state_idx": ("execution_waits", ("task_id", "state")),
}
