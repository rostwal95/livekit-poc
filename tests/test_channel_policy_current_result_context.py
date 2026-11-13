"""Actual public SDK streams with synthetic selected model/usage; no paid calls."""

from __future__ import annotations

import asyncio
import json
import unittest
from dataclasses import replace
from typing import Never
from unittest.mock import patch

from livekit import rtc
from livekit.agents import llm
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
)
from test_channel_policy_worker_current_result import fixture

from services.channel_policy_demo import current_result_context as m

PRIVATE = "PRIVATE_CONTEXT_SENTINEL"


class Reader:
    def __init__(self, value):
        self.value = value
        self.calls = 0
        self.release = None
        self.error = None
        self.entered = asyncio.Event()
        self.closed = 0

    async def read(self):
        self.calls += 1
        self.entered.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.value

    async def close(self):
        self.closed += 1


class SelectedModel(llm.LLM[Never]):
    def __init__(self):
        super().__init__()
        self.calls = []
        self.streams = []
        self.closed = 0
        self.prewarmed = 0
        self.hold_run = None
        self.hold_close = None
        self.error = None
        self.chunks = [
            llm.ChatChunk(
                id="genuine_sdk_request",
                delta=llm.ChoiceDelta(role="assistant", content="Genuine selected reply"),
            ),
            llm.ChatChunk(
                id="genuine_sdk_request",
                usage=llm.CompletionUsage(
                    completion_tokens=7,
                    prompt_tokens=19,
                    prompt_cached_tokens=3,
                    total_tokens=26,
                    service_tier="fixture",
                ),
            ),
        ]

    @property
    def model(self):
        return "selected-sdk-model"

    @property
    def provider(self):
        return "selected-sdk-fixture"

    def prewarm(self, *, loop=None):
        self.prewarmed += 1

    def chat(
        self,
        *,
        chat_ctx,
        tools=None,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls=NOT_GIVEN,
        tool_choice=NOT_GIVEN,
        extra_kwargs=NOT_GIVEN,
    ):
        self.calls.append(
            {
                "chat_ctx": chat_ctx,
                "tools": tools,
                "conn_options": conn_options,
                "parallel": parallel_tool_calls,
                "choice": tool_choice,
                "extra": extra_kwargs,
            }
        )
        stream = SelectedStream(self, chat_ctx, tools or [], conn_options)
        self.streams.append(stream)
        return stream

    async def aclose(self):
        self.closed += 1
        await super().aclose()


class SelectedStream(llm.LLMStream):
    def __init__(self, model, context, tools, options):
        self.model = model
        self.close_calls = 0
        self.close_entered = asyncio.Event()
        super().__init__(model, chat_ctx=context, tools=tools, conn_options=options)

    async def _run(self):
        if self.model.error is not None:
            raise self.model.error
        for chunk in self.model.chunks:
            self._event_ch.send_nowait(chunk)
        if self.model.hold_run is not None:
            await self.model.hold_run.wait()

    async def aclose(self):
        self.close_calls += 1
        self.close_entered.set()
        if self.model.hold_close is not None:
            await self.model.hold_close.wait()
        await super().aclose()


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.binding, self.value = fixture()
        self.reader = Reader(self.value)
        self.model = SelectedModel()
        self.wrapped = m.with_current_result(self.model, self.reader, cleanup_timeout_s=0.05)
        self.wrappers = [self.wrapped]
        self.tasks = []
        self.releases = []

    async def asyncTearDown(self):
        if self.reader.release is not None:
            self.reader.release.set()
        for event in self.releases:
            event.set()
        if self.model.hold_run is not None:
            self.model.hold_run.set()
        if self.model.hold_close is not None:
            self.model.hold_close.set()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        for wrapped in self.wrappers:
            await wrapped.aclose()
        await self.model.aclose()

    def context(self):
        ctx = llm.ChatContext()
        ctx.add_message(role="user", content="Please review this booking.")
        return ctx

    async def generate(self, wrapped=None, ctx=None, **kwargs):
        async with (wrapped or self.wrapped).chat(
            chat_ctx=ctx or self.context(), **kwargs
        ) as stream:
            return [chunk async for chunk in stream]

    def fact(self):
        item = self.model.calls[-1]["chat_ctx"].items[-1]
        self.assertIsInstance(item, llm.ChatMessage)
        text = item.text_content
        self.assertLessEqual(len(text.encode()), 1024)
        return text, json.loads(text.split("\n", 1)[1])

    async def test_public_sdk_chunks_usage_and_genuine_provider_labels_are_forwarded(self):
        metrics = []
        self.wrapped.on("metrics_collected", metrics.append)
        original = self.context()
        chunks = await self.generate(ctx=original)
        self.assertEqual(chunks, self.model.chunks)
        self.assertTrue(all(a is b for a, b in zip(chunks, self.model.chunks, strict=True)))
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(self.reader.calls, 1)
        self.assertEqual(
            (self.wrapped.label, self.wrapped.model, self.wrapped.provider),
            (self.model.label, self.model.model, self.model.provider),
        )
        self.assertEqual(len(metrics), 1)
        metric = metrics[0]
        self.assertEqual(
            (
                metric.completion_tokens,
                metric.prompt_tokens,
                metric.prompt_cached_tokens,
                metric.total_tokens,
            ),
            (7, 19, 3, 26),
        )
        self.assertEqual(
            (metric.label, metric.metadata.model_name, metric.metadata.model_provider),
            (self.model.label, self.model.model, self.model.provider),
        )
        self.assertEqual(len(original.items), 1)

    async def test_fetch_is_inside_stream_and_chatcontext_is_copied_before_await(self):
        self.reader.release = asyncio.Event()
        original = self.context()
        stream = self.wrapped.chat(chat_ctx=original)
        self.assertEqual(self.reader.calls, 0)
        await self.reader.entered.wait()
        self.assertEqual(self.model.calls, [])
        original.add_message(role="user", content="Late caller mutation")
        self.reader.release.set()
        async with stream:
            chunks = [chunk async for chunk in stream]
        copied = self.model.calls[0]["chat_ctx"]
        self.assertIsNot(copied, original)
        self.assertEqual(len(copied.items), 2)
        self.assertNotIn("Late caller mutation", str(copied.items))
        self.assertEqual(len(original.items), 2)
        self.assertTrue(chunks)

    async def test_existing_sdk_records_and_nested_metadata_are_snapshotted_before_fetch(self):
        self.reader.release = asyncio.Event()
        original = self.context()
        message = original.items[0]
        message.extra = {"google": {"signatures": ["initial"]}}
        message.metrics = {
            "provider_request_ids": ["initial"],
            "llm_metadata": {"model_name": "initial"},
        }
        call = llm.FunctionCall(
            call_id="call_1",
            name="inspect_booking",
            arguments='{"request":"initial"}',
            extra={"nested": ["initial"]},
        )
        output = llm.FunctionCallOutput(call_id="call_1", output="initial", is_error=False)
        handoff = llm.AgentHandoff(new_agent_id="initial")
        config = llm.AgentConfigUpdate(
            instructions="initial", tools_added=["initial"], tools_removed=["initial"]
        )
        original.items.extend([call, output, handoff, config])
        metrics = []
        self.wrapped.on("metrics_collected", metrics.append)
        stream = self.wrapped.chat(chat_ctx=original)
        await self.reader.entered.wait()
        message.content[0] = "Changed after admission"
        message.interrupted = True
        message.extra["google"]["signatures"].append("changed")
        message.metrics["provider_request_ids"].append("changed")
        message.metrics["llm_metadata"]["model_name"] = "changed"
        call.arguments = '{"request":"changed"}'
        call.extra["nested"].append("changed")
        output.output = "changed"
        handoff.new_agent_id = "changed"
        config.instructions = "changed"
        config.tools_added.append("changed")
        config.tools_removed.append("changed")
        self.reader.release.set()
        async with stream:
            chunks = [chunk async for chunk in stream]
        copied = self.model.calls[0]["chat_ctx"]
        self.assertIsInstance(copied, llm.ChatContext)
        for before, after in zip(original.items, copied.items[:5], strict=True):
            self.assertIs(type(after), type(before))
            self.assertIsNot(after, before)
            self.assertEqual(after.id, before.id)
        first, saved_call, saved_output, saved_handoff, saved_config = copied.items[:5]
        self.assertEqual(first.text_content, "Please review this booking.")
        self.assertFalse(first.interrupted)
        self.assertEqual(first.extra, {"google": {"signatures": ["initial"]}})
        self.assertEqual(
            first.metrics,
            {"provider_request_ids": ["initial"], "llm_metadata": {"model_name": "initial"}},
        )
        self.assertEqual(saved_call.arguments, '{"request":"initial"}')
        self.assertEqual(saved_call.extra, {"nested": ["initial"]})
        self.assertEqual((saved_output.output, saved_handoff.new_agent_id), ("initial", "initial"))
        self.assertEqual(saved_config.instructions, "initial")
        self.assertEqual(saved_config.tools_added, ["initial"])
        self.assertEqual(saved_config.tools_removed, ["initial"])
        self.assertEqual(len(original.items), 5)
        self.assertEqual(message.text_content, "Changed after admission")
        self.assertEqual(call.arguments, '{"request":"changed"}')
        self.assertEqual(config.tools_added, ["initial", "changed"])
        self.assertEqual(len(copied.items), 6)
        self.assertTrue(all(a is b for a, b in zip(chunks, self.model.chunks, strict=True)))
        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0].total_tokens, 26)

    async def test_multimodal_wrappers_are_copied_and_runtime_media_references_are_borrowed(self):
        copied_hooks = []

        class RuntimeValue:
            def __deepcopy__(self, memo):
                copied_hooks.append(1)
                raise RuntimeError(PRIVATE)

        runtime = RuntimeValue()
        binary = b"immutable provider signature"
        frame = rtc.AudioFrame.create(sample_rate=16000, num_channels=1, samples_per_channel=160)
        video = rtc.VideoFrame(1, 1, rtc.VideoBufferType.RGBA, b"\x00\x00\x00\xff")
        audio = llm.AudioContent(frame=[frame], transcript="initial transcript")
        image = llm.ImageContent(image=video, inference_width=1, inference_height=1)
        marker = llm.CacheBreakpoint()
        message = llm.ChatMessage(
            role="user",
            content=["original text", audio, image, marker],
            extra={"runtime": runtime, "binary": binary, "nested": (["initial"],)},
        )
        original = llm.ChatContext([message])
        self.reader.release = asyncio.Event()
        stream = self.wrapped.chat(chat_ctx=original)
        await self.reader.entered.wait()
        audio.transcript = "changed transcript"
        audio.frame.append(frame)
        image.image = "https://example.invalid/changed"
        image.inference_width = 2
        message.extra["nested"][0].append("changed")
        self.reader.release.set()
        async with stream:
            chunks = [chunk async for chunk in stream]
        copied = self.model.calls[0]["chat_ctx"].items[0]
        self.assertIsNot(copied, message)
        self.assertIsNot(copied.content, message.content)
        saved_audio, saved_image, saved_marker = copied.content[1:]
        self.assertIsInstance(saved_audio, llm.AudioContent)
        self.assertIsInstance(saved_image, llm.ImageContent)
        self.assertIsInstance(saved_marker, llm.CacheBreakpoint)
        self.assertIsNot(saved_audio, audio)
        self.assertIsNot(saved_audio.frame, audio.frame)
        self.assertEqual(len(saved_audio.frame), 1)
        self.assertIs(saved_audio.frame[0], frame)
        self.assertEqual(saved_audio.transcript, "initial transcript")
        self.assertIsNot(saved_image, image)
        self.assertIs(saved_image.image, video)
        self.assertEqual(saved_image.inference_width, 1)
        self.assertIsNot(saved_marker, marker)
        self.assertIs(copied.extra["runtime"], runtime)
        self.assertIs(copied.extra["binary"], binary)
        self.assertEqual(copied.extra["nested"], (["initial"],))
        self.assertEqual(copied_hooks, [])
        self.assertTrue(all(a is b for a, b in zip(chunks, self.model.chunks, strict=True)))
        self.assertEqual((len(audio.frame), audio.transcript), (2, "changed transcript"))
        self.assertEqual(len(original.items), 1)

    async def test_cyclic_deep_and_oversized_snapshot_containers_fail_before_fetch_then_progress(
        self,
    ):
        cycle = []
        cycle.append(cycle)
        deep = []
        for _ in range(m.MAX_CONTEXT_SNAPSHOT_DEPTH + 1):
            deep = [deep]
        for value in [cycle, deep, ["item"] * (m.MAX_CONTEXT_SNAPSHOT_NODES + 1)]:
            original = self.context()
            original.items[0].extra["bounded"] = value
            with self.assertRaisesRegex(m.CurrentResultContextError, "^invalid_input$"):
                self.wrapped.chat(chat_ctx=original)
        frame = rtc.AudioFrame.create(sample_rate=16000, num_channels=1, samples_per_channel=160)
        audio = llm.AudioContent(frame=[frame] * (m.MAX_CONTEXT_SNAPSHOT_NODES + 1))
        original = llm.ChatContext([llm.ChatMessage(role="user", content=[audio])])
        with self.assertRaisesRegex(m.CurrentResultContextError, "^invalid_input$"):
            self.wrapped.chat(chat_ctx=original)
        self.assertEqual((self.reader.calls, self.model.calls), (0, []))
        self.assertTrue(await self.generate())
        self.assertEqual((self.reader.calls, len(self.model.calls)), (1, 1))

    async def test_added_fact_contains_only_five_fields_without_body_capabilities_or_tools(self):
        await self.generate()
        text, fact = self.fact()
        self.assertEqual(
            fact,
            {
                "state": "current",
                "eligible": True,
                "uncertainty": "none",
                "revision": "1",
                "asOf": self.value.read_completed_at,
            },
        )
        for private in [
            self.value.result.intent.body,
            self.binding.profile_id,
            self.binding.scope.tenant_id,
            self.value.result.operation_key,
            self.value.result.intent.work_id,
            PRIVATE,
        ]:
            self.assertNotIn(private, text)
        self.assertEqual(self.model.calls[0]["tools"], [])

    async def test_noncurrent_states_remain_distinct_asof_facts(self):
        for state in ["no_delivery", "not_applicable"]:
            self.reader.value = replace(self.value, state=state, result=None)
            await self.generate()
            _, fact = self.fact()
            self.assertEqual(
                fact,
                {
                    "state": state,
                    "eligible": None,
                    "uncertainty": None,
                    "revision": None,
                    "asOf": self.value.read_completed_at,
                },
            )

    async def test_unreadable_current_is_unavailable_fact_with_same_selected_model(self):
        self.reader.error = RuntimeError(PRIVATE)
        chunks = await self.generate()
        text, fact = self.fact()
        self.assertEqual(
            fact,
            {
                "state": "unavailable",
                "eligible": None,
                "uncertainty": None,
                "revision": None,
                "asOf": None,
            },
        )
        self.assertNotIn(PRIVATE, text)
        self.assertEqual(chunks, self.model.chunks)
        self.assertEqual(len(self.model.calls), 1)

    async def test_invalid_current_body_metadata_is_unavailable_not_empty_or_stale_body(self):
        self.reader.value = replace(
            self.value,
            result=replace(self.value.result, case=replace(self.value.result.case, revision="2")),
        )
        await self.generate()
        _, fact = self.fact()
        self.assertEqual(fact["state"], "unavailable")
        self.assertIsNone(fact["eligible"])

    async def test_upstream_options_and_tools_remain_selected_and_no_outer_retry_layer(self):
        options = APIConnectOptions(max_retry=2, retry_interval=0.01, timeout=2)
        extra = {"selected_extension": True}
        tools = []
        stream = self.wrapped.chat(
            chat_ctx=self.context(),
            tools=tools,
            conn_options=options,
            parallel_tool_calls=False,
            tool_choice="none",
            extra_kwargs=extra,
        )
        async with stream:
            chunks = [chunk async for chunk in stream]
        call = self.model.calls[0]
        self.assertIs(call["conn_options"], options)
        self.assertIs(call["extra"], extra)
        self.assertEqual((call["parallel"], call["choice"], call["tools"]), (False, "none", []))
        self.assertTrue(chunks)
        self.assertEqual(stream._conn_options.max_retry, 0)

    async def test_selected_upstream_failure_propagates_without_fallback_or_extra_model_call(self):
        self.model.error = RuntimeError("unavailable")
        with self.assertRaisesRegex(m.CurrentResultContextError, "^unavailable$"):
            await self.generate(conn_options=APIConnectOptions(max_retry=0))
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(self.reader.calls, 1)

    async def test_two_owned_streams_bound_fetches_and_close_borrows_dependencies(self):
        self.reader.release = asyncio.Event()
        a = self.wrapped.chat(chat_ctx=self.context())
        b = self.wrapped.chat(chat_ctx=self.context())
        with self.assertRaisesRegex(m.CurrentResultContextError, "capacity"):
            self.wrapped.chat(chat_ctx=self.context())
        async with asyncio.timeout(1):
            while self.reader.calls < 2:
                await asyncio.sleep(0)
        await self.wrapped.aclose()
        self.assertEqual((len(self.model.calls), self.model.closed, self.reader.closed), (0, 0, 0))
        with self.assertRaisesRegex(m.CurrentResultContextError, "closed"):
            self.wrapped.chat(chat_ctx=self.context())
        await a.aclose()
        await b.aclose()

    async def test_actual_inner_close_remains_owned_after_incomplete_wrapper_observer(self):
        self.model.hold_run = asyncio.Event()
        self.model.hold_close = asyncio.Event()
        stream = self.wrapped.chat(chat_ctx=self.context())
        async with asyncio.timeout(1):
            while not self.model.streams:
                await asyncio.sleep(0)
        with self.assertRaisesRegex(m.CurrentResultContextError, "cleanup_incomplete"):
            await self.wrapped.aclose()
        self.assertFalse(self.model.hold_close.is_set())
        self.assertEqual(self.model.closed, 0)
        self.model.hold_close.set()
        await self.wrapped.aclose()
        await stream.aclose()
        self.assertEqual(self.model.streams[0].close_calls, 1)

    async def test_cancelled_close_observer_preserves_actual_drain_and_later_retry(self):
        self.model.hold_run = asyncio.Event()
        self.model.hold_close = asyncio.Event()
        stream = self.wrapped.chat(chat_ctx=self.context())
        async with asyncio.timeout(1):
            while not self.model.streams:
                await asyncio.sleep(0)
        task = asyncio.create_task(self.wrapped.aclose())
        self.tasks.append(task)
        await self.model.streams[0].close_entered.wait()
        task.cancel()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.model.hold_close.set()
        await self.wrapped.aclose()
        await stream.aclose()
        self.assertEqual(self.model.closed, 0)

    async def test_close_allocation_failure_keeps_streams_and_restored_cleanup_is_useful(self):
        self.reader.release = asyncio.Event()
        self.wrapped.chat(chat_ctx=self.context())
        await self.reader.entered.wait()

        def fail(action):
            raise RuntimeError(PRIVATE)

        with (
            patch.object(m.asyncio, "create_task", side_effect=fail),
            self.assertRaisesRegex(m.CurrentResultContextError, "cleanup_incomplete"),
        ):
            await self.wrapped.aclose()
        await self.wrapped.aclose()
        self.assertEqual(self.model.calls, [])
        fresh = m.with_current_result(self.model, Reader(self.value))
        self.wrappers.append(fresh)
        self.assertTrue(await self.generate(wrapped=fresh))

    async def test_eager_reader_close_waits_actual_stream_publication(self):
        value = self.value
        closes = []
        seen = []
        release = asyncio.Event()
        self.releases.append(release)

        class Reentrant:
            async def read(self):
                closes.append(asyncio.create_task(wrapped.aclose()))
                seen.append(closes[0].done())
                await release.wait()
                return value

        wrapped = m.with_current_result(self.model, Reentrant())
        self.wrappers.append(wrapped)
        loop = asyncio.get_running_loop()
        prior = loop.get_task_factory()
        loop.set_task_factory(asyncio.eager_task_factory)
        try:
            stream = wrapped.chat(chat_ctx=self.context())
            self.assertEqual(seen, [False])
            release.set()
            await closes[0]
            await stream.aclose()
        finally:
            release.set()
            loop.set_task_factory(prior)
            await asyncio.gather(*closes, return_exceptions=True)
        self.assertEqual(self.model.calls, [])

    async def test_reader_method_snapshot_and_descriptor_rejection_before_work(self):
        calls = []

        class Hostile:
            @property
            def read(self):
                calls.append(1)
                raise RuntimeError(PRIVATE)

        with self.assertRaisesRegex(m.CurrentResultContextError, "invalid_input"):
            m.with_current_result(self.model, Hostile())
        self.assertEqual(calls, [])
        self.reader.read = lambda: (_ for _ in ()).throw(RuntimeError(PRIVATE))
        await self.generate()
        _, fact = self.fact()
        self.assertEqual(fact["state"], "current")

    async def test_prewarm_delegates_to_genuine_model_and_wrapper_close_does_not_close_it(self):
        self.wrapped.prewarm()
        self.assertEqual(self.model.prewarmed, 1)
        await self.wrapped.aclose()
        self.wrapped.prewarm()
        self.assertEqual((self.model.prewarmed, self.model.closed, self.reader.closed), (1, 0, 0))

    async def test_telemetry_failure_does_not_change_selected_chunks_or_summary(self):
        with patch.object(m.LOGGER, "info", side_effect=RuntimeError(PRIVATE)):
            chunks = await self.generate()
        self.assertEqual(chunks, self.model.chunks)
        _, fact = self.fact()
        self.assertEqual(fact["state"], "current")

    async def test_invalid_factory_budget_and_non_sdk_model_are_finite_before_fetch(self):
        for value in [True, 10**1000, float("nan"), float("inf"), 0, 6]:
            with self.assertRaisesRegex(m.CurrentResultContextError, "invalid_input"):
                m.with_current_result(self.model, self.reader, cleanup_timeout_s=value)
        with self.assertRaisesRegex(m.CurrentResultContextError, "invalid_input"):
            m.with_current_result(object(), self.reader)
        self.assertEqual((self.reader.calls, self.model.calls), (0, []))
