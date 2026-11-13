"""Release assertions for completion committed before any delivery attempt."""

import json
import os
import sys
import unittest
from contextlib import closing
from pathlib import Path

import pg_effect_cases as prior

from continuity_lab.effect_models import DeliveryState, EffectState
from harness.process_control import OwnedProcess

ACTOR = prior.ACTOR

CHILD = r"""
import json,os,sys
from datetime import datetime
from continuity_lab.completion_sink import CompletionSink
from continuity_lab.effect_models import parse_mutation_result
from continuity_lab.outbox_delivery import CompletionDeliveryWorker
from continuity_lab.postgres_effects import PostgresEffects
from continuity_lab.postgres_settings import PostgresSettings
from continuity_lab.postgres_store import PostgresExecutionStore
mode,task_id,sink_path,now,raw=sys.argv[1:]
clock=lambda:datetime.fromisoformat(now)
def fail(name):
 if name=='effects.after_finish_commit':os._exit(76)
effects=PostgresEffects(PostgresExecutionStore(PostgresSettings.from_env(),clock=clock),clock=clock,failpoint=fail if mode=='commit' else None)
if mode=='commit':
 claim=effects.claim(scope_id='account-a',task_id=task_id)
 if claim is None:raise AssertionError('An eligible effect is required')
 effects.prepare_dispatch(claim,absence_confirmed=True)
 effects.finish_success(claim,parse_mutation_result(json.loads(raw)))
 raise AssertionError('The postcommit process failpoint was not reached')
if mode!='deliver':raise AssertionError('Unsupported test mode')
value=CompletionDeliveryWorker(effects,CompletionSink(sink_path,clock=clock)).run_one(scope_id='account-a',task_id=task_id)
print(json.dumps({'state':value.state,'event_id':value.event.event_id,'attempts':value.attempts}),flush=True)
"""


class PostgresCompletionCommitCases(unittest.TestCase):
    setUpClass = classmethod(prior.PostgresEffectCases.setUpClass.__func__)
    setUp = prior.PostgresEffectCases.setUp
    drop_schema = prior.PostgresEffectCases.drop_schema
    authority = prior.PostgresEffectCases.authority
    prepare = prior.PostgresEffectCases.prepare
    result = prior.PostgresEffectCases.result

    def child(self, mode, record, payload, suffix):
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("P1_MIGRATION_")
        }
        environment["P1_POSTGRES_SCHEMA"] = self.schema
        with OwnedProcess(
            [
                sys.executable,
                "-c",
                CHILD,
                mode,
                record.task_id,
                str(self.sink_path),
                self.clock[0].isoformat(),
                json.dumps(payload),
            ],
            cwd=Path.cwd(),
            env=environment,
            output_directory=(Path(self.directory.name) / suffix).resolve(),
            max_output_bytes=8192,
        ) as child:
            result = child.wait(timeout=15)
        return result.returncode, child.output_tail("stdout", maximum_bytes=8192)

    def test_completion_commit_process_loss_before_first_delivery_retains_one_event(
        self,
    ):
        record, _quote, intent = self.prepare()
        payload = self.result(intent).payload()
        code, _ = self.child("commit", record, payload, "commit-child")
        self.assertEqual(code, 76)
        # The killed process has committed completion but has never invoked the sink.
        self.assertEqual(self.sink.count(), 0)
        event = self.effects.completion(actor=ACTOR, task_id=record.task_id)
        delivery = self.effects.delivery(actor=ACTOR, task_id=record.task_id)
        self.assertEqual(event.outcome.state, EffectState.SUCCEEDED)
        self.assertEqual((delivery.state, delivery.attempts), (DeliveryState.PENDING, 0))
        original_id = event.event_id
        code, raw = self.child("deliver", record, payload, "delivery-child")
        self.assertEqual(code, 0)
        first = json.loads(raw)
        self.assertEqual(first, {"state": "delivered", "event_id": original_id, "attempts": 1})
        code, raw = self.child("deliver", record, payload, "replay-child")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(raw), first)
        self.assertEqual(self.sink.count(), 1)
        self.assertEqual(self.effects.completion(actor=ACTOR, task_id=record.task_id), event)
        self.assertEqual(
            self.effects.delivery(actor=ACTOR, task_id=record.task_id).state,
            DeliveryState.DELIVERED,
        )
        with closing(self.runtime.connect()) as connection:
            # Inspect via the authority's configured schema, never unqualified tables.
            from psycopg import sql

            observed = connection.execute(
                sql.SQL("SELECT COUNT(*) AS n FROM {} WHERE task_id=%s").format(
                    sql.Identifier(self.schema, "completion_events")
                ),
                (record.task_id,),
            ).fetchone()
        self.assertEqual(observed["n"], 1)
