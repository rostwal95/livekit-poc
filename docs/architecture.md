# Architecture

The application composes three continuity libraries around one LiveKit
deployment and one PostgreSQL service. The agent session handles the current
interaction. Persistent services own the case, input receipts, and policy work.

## Components and authority

```mermaid
flowchart LR
    User[Browser] <-->|WebRTC audio and text| LK[LiveKit]
    LK <-->|Room media and session events| Agent[LiveKit Agents worker]
    User -->|Join, End, simulate SMS| Parent[Python application]
    Parent -->|Owns worker and room| Agent
    Agent -->|Accept native turn| Gateway[Node channel gateway]
    Parent -->|Signed simulated SMS| Gateway
    Gateway -->|Original input and dispatch identity| Parent
    Parent -->|Issued policy request| Specialist[Fixed-policy specialist]
    Specialist -->|Read-only result| Parent
    Gateway <-->|Channel input and receipts| PG[(PostgreSQL)]
    Parent <-->|Case and delegated work| PG
    User -->|Read case and policy observations| Parent
    Agent -->|Read current result| Parent
    User -->|Approve exact quote| Operator[Operator API]
    Operator -->|Commit guarded intent| PG
    Worker[Leased booking worker] <-->|Claim and record effects| PG
    Worker -->|Apply and deliver| Ledgers[(Synthetic supplier and receiver)]
```

| Data or process | Authority |
| --- | --- |
| Live session | LiveKit carries media and text. The Python room owner binds each activation to one room and worker. [Room owner](../services/channel_policy_demo/native_room.py) |
| Case and delegated work | The Agent Continuity library owns case revisions, accepted work, issued attempts, stored results, and result delivery intent. It also owns exact confirmation in the separate operator workflow. [Agent Continuity](../projects/agent-continuity/python/) |
| Channel inputs and receipts | The Channel Continuity library owns scoped native and simulated SMS input, dispatch state, and receiver receipts. [Channel Continuity](../projects/channel-continuity/) |
| Policy evaluation | The specialist evaluates fixed rules against the issued request and returns a read-only answer. The orchestration layer retains the work and result. [Delegation Reliability](../projects/delegation-reliability/) |

PostgreSQL separates booking, delegated work, and channel state into three
schemas installed by baseline `0001_initial`. A one-shot owner initializes the
schemas. Serving processes use a restricted role and validate the baseline.
The synthetic supplier and receiver keep independent receipts outside PostgreSQL.

| Schema | Durable records |
| --- | --- |
| Booking | Case and revision, investigation, exact confirmation, leases, effect intent and completion |
| Delegated work | Original work identity, issued attempt, result, result feed and receiver binding |
| Channel | Scoped input, dispatch, room binding and result delivery receipt |

Each accepted channel input has a stable, scoped identity and immutable payload.
Replaying the same payload can return its original receipt. A changed payload
with the same identity conflicts. Dispatch binds a work item to that original
input and its case revision. Room identifiers can change while the case and
work identifiers remain stable.

## End, continue, and rejoin

```mermaid
sequenceDiagram
    actor Caller
    participant Agent as LiveKit Agents session
    participant Channel as Channel gateway
    participant Work as Case and work authority
    participant Policy as Fixed-policy specialist
    Caller->>Agent: Send text or commit recorded voice turn
    Agent->>Channel: Submit original scoped input
    Channel-->>Agent: Durable input receipt
    Channel->>Work: Dispatch with original operation identity
    Work->>Policy: Run issued check against the case revision
    Agent-->>Caller: Reply from available observations
    Caller->>Agent: End original session through the room owner
    Note over Channel,Work: Room input drains to known handoff before closure
    Caller->>Channel: Send signed simulated SMS via local API
    Channel->>Work: Dispatch follow-up for the same case
    Policy-->>Work: Return read-only result
    Work->>Channel: Deliver to the bound receiver
    Caller->>Agent: Join a new session
    Agent->>Work: Read current case and policy result
    Agent-->>Caller: Resume with current result
```

An input receipt proves that the input was accepted. A dispatch observation
reports its handoff to the work authority. A result read reports applicability
at the time of the read. The three can arrive at different times. Known results
remain available after the original media session ends.

## Room lifecycle

```mermaid
stateDiagram-v2
    [*] --> idle
    idle --> preparing: Join
    preparing --> waiting_browser: Worker and room created
    waiting_browser --> ready: Browser and agent ready
    preparing --> closing: Startup fails or End
    waiting_browser --> closing: Startup fails or End
    ready --> closing: End or disconnect
    closing --> closing: Original cleanup pending
    closing --> closed: Room absent and worker reaped
    closing --> recovery_required: Ownership unresolved
    closed --> preparing: Next Join
```

Closure fences native input, drains accepted handoffs, retires the room grant,
and reaps the owning worker. A closing or unresolved room blocks another Join.
Delegated work has an independent lifetime. Keep a missing acknowledgement
uncertain and reconcile it with the original operation identity.

In the operator flow, the browser explicitly confirms the current quote before
the authority commits booking intent. The fake supplier call runs outside that
transaction. Supplier outcome and receiver delivery remain separate from the
confirmation record.

## Source map

| Path | Responsibility |
| --- | --- |
| [Browser](../apps/local-console/) | LiveKit web client and the showcase and operator views |
| [Python application](../services/channel_policy_demo/) | Room ownership, origin-bound dispatch and background execution |
| [Node gateway](../services/channel-policy-gateway/) | Native and SMS intake and fixed-policy service entry point |
| [Local setup](../local-setup/) | Compose configuration, isolated initialization and lifecycle helpers |
