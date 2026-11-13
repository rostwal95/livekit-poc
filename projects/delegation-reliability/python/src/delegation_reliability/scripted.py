"""Explicit finite local LLM fixture; no provider factory, credentials or network."""

from __future__ import annotations

import json
from typing import Any, Never
from uuid import uuid4

from livekit.agents import llm
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)

PENDING_REPLY = "The read-only policy review is pending; no result is available yet."
USEFUL_REPLY = "A read-only policy review can explain the rule; it cannot change the booking."
COMPLETED_REPLY = (
    "The synthetic policy result is available; it does not authorize a booking change."
)
SAFE_REPLY = "This controlled example only supports policy review and read-only questions."
EVALUATE_COMMAND = "evaluate the synthetic policy"
QUESTION_COMMAND = "what does read only mean?"


class FixtureLLM(llm.LLM[Never]):
    """Dispatch exact fixture commands through real SDK tools, not model reasoning."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    @property
    def model(self) -> str:
        return "p3-policy-scripted-v1"

    @property
    def provider(self) -> str:
        return "local-fixture"

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> llm.LLMStream:
        # Any is the SDK provider-extension signature, deliberately unused.
        self.calls += 1
        if self.calls > 24:
            raise RuntimeError("fixture_call_limit")
        return _FixtureStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


class _FixtureStream(llm.LLMStream):
    async def _run(self) -> None:
        item = next(
            (
                entry
                for entry in reversed(self.chat_ctx.items)
                if not (
                    isinstance(entry, llm.ChatMessage) and entry.role in {"system", "developer"}
                )
            ),
            None,
        )
        request_id = "fixture-" + uuid4().hex
        available = {
            tool.info.name
            for tool in self.tools
            if isinstance(tool, (llm.FunctionTool, llm.RawFunctionTool))
        }
        if (
            isinstance(item, llm.ChatMessage)
            and item.role == "user"
            and item.text_content == EVALUATE_COMMAND
            and "evaluate_policy" in available
        ):
            delta = llm.ChoiceDelta(
                role="assistant",
                tool_calls=[
                    llm.FunctionToolCall(
                        name="evaluate_policy", arguments="{}", call_id="fixture-" + uuid4().hex
                    )
                ],
            )
        else:
            reply = SAFE_REPLY
            if isinstance(item, llm.ChatMessage) and item.text_content == QUESTION_COMMAND:
                reply = USEFUL_REPLY
            elif isinstance(item, llm.FunctionCallOutput):
                reply = PENDING_REPLY
                try:
                    value = json.loads(item.output)
                except (ValueError, TypeError):
                    value = None
                if type(value) is dict and value.get("status") == "completed" and not item.is_error:
                    reply = COMPLETED_REPLY
            delta = llm.ChoiceDelta(role="assistant", content=reply)
        self._event_ch.send_nowait(llm.ChatChunk(id=request_id, delta=delta))
        # Fixture execution has no paid/model token usage. Do not manufacture usage.
