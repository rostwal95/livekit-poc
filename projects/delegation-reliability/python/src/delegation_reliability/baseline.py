"""Real local AgentSession tools and AgentTask/TaskGroup with controlled outcomes.

Only orchestration is under test. The native task temporarily controls the same
session; it is not an independently executing model, service or durable worker.
"""

from __future__ import annotations

import asyncio
import logging
import math
import sys
import time
from dataclasses import dataclass, field

from livekit.agents import Agent, AgentSession, AgentTask, RunContext, function_tool, llm
from livekit.agents.beta.workflows import TaskGroup, TaskGroupResult
from livekit.agents.voice.events import (
    ConversationItemAddedEvent,
    ToolCallStarted,
    ToolExecutionUpdatedEvent,
)
from livekit.agents.voice.run_result import RunResult

from .models import (
    BaselineCleanupError,
    BaselineError,
    BaselineInputError,
    BaselineInvariantError,
    BaselineMode,
    BaselineObservation,
    BaselineTimeout,
    PolicyInput,
    PolicyResult,
    evaluate_policy,
)
from .scripted import (
    COMPLETED_REPLY,
    EVALUATE_COMMAND,
    QUESTION_COMMAND,
    USEFUL_REPLY,
    FixtureLLM,
)

_LOGGER = logging.getLogger(__name__)
MAX_RUN_SECONDS = 15.0
CLOSE_SECONDS = 3.0


@dataclass(slots=True)
class _Experiment:
    value: PolicyInput
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    returned: asyncio.Event = field(default_factory=asyncio.Event)
    output_seen: asyncio.Event = field(default_factory=asyncio.Event)
    tasks: list[_PolicyTask] = field(default_factory=list)
    result: PolicyResult | None = None
    group_completed: bool = False
    active: int = 0
    completed: int = 0
    abort: bool = False

    async def evaluate(self) -> PolicyResult:
        if self.entered.is_set():
            raise BaselineInvariantError()
        self.active += 1
        self.entered.set()
        _LOGGER.info("policy_evaluation_started", extra={"outcome": "held"})
        try:
            await self.release.wait()
            if self.abort:
                raise asyncio.CancelledError()
            self.result = evaluate_policy(self.value)
            self.completed += 1
            return self.result
        finally:
            self.active -= 1
            _LOGGER.info("policy_evaluation_closed", extra={"outcome": "closed"})


class _PolicyTask(AgentTask[PolicyResult]):
    def __init__(self, experiment: _Experiment) -> None:
        super().__init__(instructions="Evaluate the fixed synthetic policy without mutation.")
        self.experiment = experiment
        experiment.tasks.append(self)

    async def on_enter(self) -> None:
        # Let on_enter return; holding it would hold a session.run guard open.
        self.session.generate_reply(user_input=EVALUATE_COMMAND)

    @function_tool(on_duplicate="reject")
    async def evaluate_policy(self, ctx: RunContext[None]) -> str:
        """Run the fixed read-only fixture and return its typed task result."""
        await ctx.update("policy_review_pending")
        try:
            result = await self.experiment.evaluate()
        except asyncio.CancelledError:
            if not self.done():
                self.cancel()
            raise
        self.complete(result)
        return result.as_tool_output()


class _PolicyAgent(Agent):
    def __init__(self, experiment: _Experiment, mode: BaselineMode) -> None:
        super().__init__(
            instructions="Explain read-only policy evaluation; never change a booking."
        )
        self.experiment = experiment
        self.mode = mode

    @function_tool(on_duplicate="reject")
    async def evaluate_policy(self, ctx: RunContext[None]) -> str:
        """Evaluate synthetic policy while allowing another bounded text question."""
        await ctx.update("policy_review_pending")
        if self.mode == "single_tool":
            result = await self.experiment.evaluate()
        else:
            group = TaskGroup(summarize_chat_ctx=False)
            group.add(
                lambda: _PolicyTask(self.experiment),
                id="policy",
                description="Evaluate the fixed read-only policy",
            )
            async with ctx.foreground():
                grouped: TaskGroupResult = await group
            candidate = grouped.task_results.get("policy")
            if not isinstance(candidate, PolicyResult):
                raise BaselineInvariantError()
            result = candidate
            self.experiment.group_completed = True
        self.experiment.returned.set()
        return result.as_tool_output()


def _validate_parameters(mode: BaselineMode, value: PolicyInput, timeout_seconds: float) -> None:
    if (
        type(mode) is not str
        or mode not in {"single_tool", "native_task_group"}
        or type(value) is not PolicyInput
    ):
        raise BaselineInputError()
    if (
        type(timeout_seconds) not in {int, float}
        or not 0 < timeout_seconds <= MAX_RUN_SECONDS
        or not math.isfinite(timeout_seconds)
    ):
        raise BaselineInputError()


async def _close_owned(
    session: AgentSession[None] | None,
    model: FixtureLLM | None,
    experiment: _Experiment,
) -> bool:
    """Attempt every owned close inside one budget; failures cannot become a pass."""
    closed = True
    experiment.abort = True
    for task in experiment.tasks:
        if not task.done():
            try:
                task.cancel()
            except Exception:  # noqa: BLE001 - Owned SDK cancellation cleanup boundary.
                # SDK cleanup containment only; never serialize its exception.
                closed = False
    experiment.release.set()
    deadline = asyncio.get_running_loop().time() + CLOSE_SECONDS
    for resource in (session, model):
        if resource is None:
            continue
        try:
            async with asyncio.timeout_at(deadline):
                await resource.aclose()
        except Exception:  # noqa: BLE001 - Attempt every owned resource close.
            closed = False
    return closed and experiment.active == 0


async def run_baseline(
    mode: BaselineMode,
    value: PolicyInput,
    *,
    timeout_seconds: float = MAX_RUN_SECONDS,
) -> BaselineObservation:
    """Run one held fixture, meaningful text follow-up and eventual real SDK result.

    Limits: one evaluation, 24 scripted-model calls, 2048 input JSON bytes and a
    bounded close. Cancellation propagates after closing owned SDK resources.
    No durable acceptance, tenant authorization, browser or model-quality claim.
    """
    _validate_parameters(mode, value, timeout_seconds)
    experiment = _Experiment(value)
    model: FixtureLLM | None = None
    session: AgentSession[None] | None = None

    tool_calls = 0
    handoffs = 0

    def observe(event: ConversationItemAddedEvent) -> None:
        nonlocal handoffs
        if isinstance(event.item, llm.AgentHandoff):
            handoffs += 1
        if (
            isinstance(event.item, llm.ChatMessage)
            and event.item.role == "assistant"
            and event.item.text_content == COMPLETED_REPLY
        ):
            experiment.output_seen.set()

    def observe_tools(event: ToolExecutionUpdatedEvent) -> None:
        nonlocal tool_calls
        if isinstance(event.update, ToolCallStarted):
            tool_calls += 1

    started = time.monotonic()
    useful_seconds = 0.0
    absent = False
    completed_seconds = 0.0
    cleanup_complete = False
    try:
        model = FixtureLLM()
        session = AgentSession(llm=model, max_tool_steps=3)
        session.on("conversation_item_added", observe)
        session.on("tool_execution_updated", observe_tools)
        async with asyncio.timeout(timeout_seconds):
            await session.start(_PolicyAgent(experiment, mode), record=False)
            await session.run(user_input=EVALUATE_COMMAND)
            await experiment.entered.wait()
            absent = experiment.result is None and experiment.completed == 0
            useful_started = time.monotonic()
            follow_up: RunResult[None] = await session.run(user_input=QUESTION_COMMAND)
            useful_seconds = time.monotonic() - useful_started
            if (
                not any(
                    event.type == "message"
                    and event.item.role == "assistant"
                    and event.item.text_content == USEFUL_REPLY
                    for event in follow_up.events
                )
                or experiment.result is not None
                or experiment.release.is_set()
            ):
                raise BaselineInvariantError()
            experiment.release.set()
            await experiment.returned.wait()
            await experiment.output_seen.wait()
            completed_seconds = time.monotonic() - started
            if experiment.result != evaluate_policy(value) or experiment.completed != 1:
                raise BaselineInvariantError()
    except BaselineError:
        raise
    except TimeoutError:
        raise BaselineTimeout() from None
    except Exception:  # noqa: BLE001 - Public SDK operation containment.
        # One public operation boundary; retain no external text in diagnostics.
        _LOGGER.error("baseline_failed", extra={"mode": mode, "code": "sdk_boundary_failed"})
        raise BaselineError() from None
    finally:
        primary = sys.exception()
        cleanup_complete = await _close_owned(session, model, experiment)
        if session is not None:
            try:
                session.off("conversation_item_added", observe)
                session.off("tool_execution_updated", observe_tools)
            except Exception:  # noqa: BLE001 - Cleanup must preserve the primary failure.
                cleanup_complete = False
        if not cleanup_complete:
            _LOGGER.error("baseline_cleanup_failed", extra={"mode": mode})
            if primary is not None:
                primary.add_note("baseline_cleanup_failed")
            else:
                raise BaselineCleanupError()
    if experiment.result is None or model is None or not absent:
        raise BaselineInvariantError()
    _LOGGER.info("baseline_completed", extra={"mode": mode, "outcome": "completed"})
    return BaselineObservation(
        mode=mode,
        result=experiment.result,
        input_fingerprint=value.fingerprint,
        held_response_code="read_only_explained",
        held_response_seconds=useful_seconds,
        completion_seconds=completed_seconds,
        result_absent_while_held=absent,
        result_observed_in_sdk=experiment.output_seen.is_set(),
        native_task_count=len(experiment.tasks),
        native_group_completed=experiment.group_completed,
        sdk_tool_calls=tool_calls,
        sdk_handoffs=handoffs,
        fixture_model_calls=model.calls,
        evaluations_completed=experiment.completed,
        active_after_cleanup=experiment.active,
        cleanup_complete=cleanup_complete,
    )
