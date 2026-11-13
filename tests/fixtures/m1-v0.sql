-- Synthetic pre-upgrade M1 data. No execution schema or version marker exists.
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'queued'),
    created_at TEXT NOT NULL,
    UNIQUE (scope_id, idempotency_key)
);
INSERT INTO tasks VALUES (
    '11111111-1111-4111-8111-111111111111',
    'traveller-a',
    'm1-existing-001',
    '{"booking_reference":"DEMO-BK-001","confirmed":true,"new_check_in":"2030-12-10"}',
    'queued',
    '2026-11-09T10:00:00+00:00'
);
