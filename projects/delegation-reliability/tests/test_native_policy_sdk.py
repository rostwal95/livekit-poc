"""Real pinned AgentSession/tool ownership with scripted model and no RTC/provider.

Durable storage and browser transport are separate actual gates. No native SDK
execution method is replaced; only outbound socket connect is denied explicitly.
"""

import asyncio
import unittest
from unittest.mock import patch

from livekit.agents import AgentSession, llm
from livekit.agents.voice.events import (
    ConversationItemAddedEvent,
    ToolCallEnded,
    ToolCallStarted,
    ToolCallUpdated,
    ToolExecutionUpdatedEvent,
)
from test_native_policy import Context, close_until_settled, owners, until

from delegation_reliability import NativePolicyAgent, NativePolicyError
from delegation_reliability.scripted import (
    COMPLETED_REPLY,
    EVALUATE_COMMAND,
    QUESTION_COMMAND,
    USEFUL_REPLY,
    FixtureLLM,
)


class NativePolicySDKTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.resources = []

    async def asyncTearDown(self):
        for session, model, app, authority, specialist in self.resources:
            if authority.observe_release is not None:
                authority.observe_release.set()
            if specialist.release is not None:
                specialist.release.set()
            await session.aclose()
            await model.aclose()
            await until(lambda app=app: app.metrics()["runner_pending"] == 0)
            await close_until_settled(app)

    async def start(self, values=(10,)):
        app, authority, cases, specialist, _coordinator, runner = owners(values)
        specialist.release = asyncio.Event()
        model = FixtureLLM()
        session = AgentSession(llm=model, max_tool_steps=3, user_away_timeout=None)
        self.resources.append((session, model, app, authority, specialist))
        updates = []
        completed = asyncio.Event()

        def tools(event: ToolExecutionUpdatedEvent):
            updates.append(event.update)

        def conversation(event: ConversationItemAddedEvent):
            if (
                isinstance(event.item, llm.ChatMessage)
                and event.item.role == "assistant"
                and event.item.text_content == COMPLETED_REPLY
            ):
                completed.set()

        session.on("tool_execution_updated", tools)
        session.on("conversation_item_added", conversation)
        await session.start(NativePolicyAgent(app), record=False)
        return session, app, authority, cases, specialist, runner, updates, completed

    async def test_one_real_session_answers_usefully_while_actual_policy_is_held(self):
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            session, app, authority, _, specialist, runner, updates, completed = await self.start()
            async with asyncio.timeout(5):
                await session.run(user_input=EVALUATE_COMMAND)
                await specialist.entered.wait()
                self.assertEqual(authority.submit_calls, 1)
                self.assertEqual(authority.complete_count, 0)
                self.assertFalse(completed.is_set())
                progress = [x for x in updates if isinstance(x, ToolCallUpdated)]
                self.assertEqual(len(progress), 1)
                self.assertTrue(progress[0].silent)
                self.assertIn(authority.record.work_id, progress[0].message)
                follow_up = await session.run(user_input=QUESTION_COMMAND)
                self.assertTrue(
                    any(
                        event.type == "message"
                        and event.item.role == "assistant"
                        and event.item.text_content == USEFUL_REPLY
                        for event in follow_up.events
                    )
                )
                self.assertFalse(specialist.release.is_set())
                self.assertEqual(authority.complete_count, 0)
                self.assertEqual((await app.inspect_observed()).state, "work")
                self.assertEqual(runner.pending_count, 1)
                specialist.release.set()
                await completed.wait()
                await until(lambda: runner.pending_count == 0)
            seen = (await app.inspect_observed()).to_wire()
            self.assertEqual(seen["state"], "result")
            self.assertEqual(seen["result"]["eligible"], True)
            self.assertEqual(seen["applicability"], "candidate")
            self.assertEqual(len([x for x in updates if isinstance(x, ToolCallStarted)]), 1)
            self.assertEqual([x.status for x in updates if isinstance(x, ToolCallEnded)], ["done"])
            self.assertEqual(authority.issue_count, 1)
            self.assertEqual(authority.complete_count, 1)
            self.assertEqual(len(specialist.requests), 1)

    async def test_actual_sdk_cancellable_close_stops_waiting_not_durable_work(self):
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            session, app, authority, _, specialist, runner, updates, _ = await self.start()
            async with asyncio.timeout(5):
                await session.run(user_input=EVALUATE_COMMAND)
                await specialist.entered.wait()
                await session.aclose()
            self.assertIn("cancelled", [x.status for x in updates if isinstance(x, ToolCallEnded)])
            self.assertEqual(app.metrics()["owned_run"], 1)
            self.assertEqual(runner.pending_count, 1)
            self.assertFalse(authority.record.cancel_requested)
            with self.assertRaisesRegex(NativePolicyError, "^capacity$"):
                await app.evaluate(Context(authority))
            held = (await app.inspect_observed()).to_wire()
            self.assertEqual(held["tool_waiter"], "stopped_waiting")
            self.assertEqual(held["state"], "work")
            self.assertEqual(authority.issue_count, 1)
            specialist.release.set()
            await until(lambda: runner.pending_count == 0)
            self.assertEqual((await app.inspect_observed()).state, "result")
            self.assertEqual(authority.complete_count, 1)
            self.assertFalse(authority.record.cancel_requested)

    async def test_actual_sdk_missing_fact_is_clarification_not_false_eligibility(self):
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            session, app, authority, _, specialist, runner, _, completed = await self.start(())
            async with asyncio.timeout(5):
                await session.run(user_input=EVALUATE_COMMAND)
                await specialist.entered.wait()
                follow_up = await session.run(user_input=QUESTION_COMMAND)
                self.assertTrue(
                    any(
                        event.type == "message" and event.item.text_content == USEFUL_REPLY
                        for event in follow_up.events
                    )
                )
                specialist.release.set()
                await completed.wait()
                await until(lambda: runner.pending_count == 0)
            seen = (await app.inspect_observed()).to_wire()
            self.assertEqual(seen["applicability"], "clarification")
            self.assertIsNone(seen["result"]["eligible"])
            self.assertEqual(seen["result"]["uncertainty"], "missing")
            self.assertEqual(seen["result"]["fact_refs"], [])
            self.assertEqual(authority.complete_count, 1)
