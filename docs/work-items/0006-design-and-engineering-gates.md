# Standardized designs and engineering acceptance gates

| Field | Value |
| --- | --- |
| Status | Completed |
| Purpose | Record the plan, observed verification and handoff for standardized designs, engineering gates and the related foundation corrections |
| Audience | Engineers writing designs or engineering gates, or changing diagnostic logging; coding agents |
| Scope | Ten maintained Design.md files, the design template, the Python engineering guide, design checks, the echo reply bound and diagnostic logging; excludes product requirements and new product telemetry |
| Owns | Change plan, observed verification and handoff for the design and engineering gate standard |
| Related | [Work item 0005](0005-granular-implementation-plan.md) · [Work item 0007](0007-p1-phase-a-execution-foundation.md) · [Design template](../design-template.md) · [Python engineering](../python-engineering.md) · [Validation plan](../validation-plan.md) |

## Behavior and scope

Standardize all ten maintained Design.md files and a reusable template with
business and technical tables, sizing, high-level, sequence and low-level Mermaid
views, component ownership, security, observability, metrics, exception handling,
trade-offs and acceptance gates. Add a shared Python engineering guide and make the
documentation harness enforce the structural standard with negative tests.
Preserve the 54 product requirements and existing implementation boundaries.

The boundary review also identified a six-byte echo-prefix mismatch at the largest
accepted diagnostic input. Correct only the authenticated agent-chat reply bound.
Preserve request, audio and API bounds, and verify exact UTF-8 edges. Add narrow
safe diagnostic-worker event logging at real lifecycle and error producers. Add
bounded allowlisted service-specific logs and preserve diagnostic stderr. Close the
existing read-only SQLite test fixture connection explicitly. Do not invent product
telemetry or change supplier or conversation semantics.

## Interfaces and ownership

| Document | Owns |
| --- | --- |
| Design.md | Component design |
| Charters | Requirements |
| Validation plan | Engineering gate sufficiency |
| Python guide | Implementation practices |

Optional role fields in documentation.json enforce ordered sections, populated
tables and section-owned diagram types. Structural checks do not prove Mermaid
syntax or meaning, or product behavior. The diagnostic text contract adds explicit
request and reply byte bounds without truncation. Worker events must use fixed
safe categories, finite fields and explicit application logger setup.

## Failure cases and validation

Run the documentation rule's positive and negative fixtures, the actual Mermaid
parser, the granular traceability audit and the full fast lane. Check comments,
indented and fenced examples, escaped table pipes, wrong, missing or misplaced
diagrams, and invalid policy.

For the echo fix, exercise exact and excessive ASCII and multibyte requests and
replies, source trust and reader cleanup. Logging needs schema and level,
exception-sentinel, duplicate-handler, cancellation and context-isolation
assertions. Run the affected frontend lane and actual stack smoke after runtime
changes. Keep actual browser evidence and product or live evidence separate.
Capture exact commands and outcomes below.

## Results and handoff

All ten maintained Design.md files now follow the 15-section standard, with a
reusable template and shared Python engineering guide. Design policy is enforced
by the documentation harness with positive and negative fixtures. Shared and
project plans and the work-item guidance require applicable engineering gates,
explicit Given/When/Then safety and useful-progress criteria, and real diagnostic
evidence. The original 22 PLAN work packages and 54 requirement mappings are
unchanged.

Foundation corrections are implemented: explicit diagnostic text bounds, shared
Unicode and overflow fixtures, safe fixed-schema worker events from actual
producers, and bounded per-service log inspection.

| Limit | Value |
| --- | --- |
| Diagnostic request | 16,384 bytes |
| Authenticated echo reply | 16,390 bytes |

Logs merge both child streams only in the diagnostic action. Other commands
preserve their stdout contract. The aggregate log tail can omit earlier service
output. This run's direct Compose worker events were on stdout, so the observed
omission was not attributed to stderr loss. A separate real-child test verifies
stderr preservation. Existing SQLite test cleanup was corrected rather than
suppressing ResourceWarning.

### Observed gates

| Observed gate | Command or mode | Result |
| --- | --- | --- |
| Offline checks | Full `make check` | 161 Python tests passed with zero skips and no ResourceWarning in retained suite output; static, module and documentation checks and Ruff passed; mypy passed for ten service files |
| Formatting | `make format-check` | Forty files passed |
| Frontend | Supported Node 24.22.2 and declared pnpm 12.18.0 in an isolated temporary tool cache | 66 tests passed, TypeScript checked and the production build passed |
| Documentation | Documentation checker | 60 maintained documents, zero violations |
| Diagrams | Real Mermaid 11.12.0 parsing with jsdom 26.1.0 | All 33 diagrams across ten designs and the template validated; a malformed fixture was rejected |
| Local runtime | Actual preserved-volume local rebuild and start, and container smoke | Passed API readiness and authentication, M1 replay and conflict, named dispatch, ordinary echo, the full multi-byte 16,384-byte request and 16,390-byte reply, and real audio frames |
| Worker events | Actual `logs --service rtc-agent` command | Five inspected safe JSON producer records: start, completion, cancellation and finish observations |
| Traceability | Granular traceability audit | Remains acyclic with all task references and 54 rows intact |
| Deep gate | Deep product gate | Incomplete (exit 2): one baseline passed and all 54 product cases remain not implemented |
| Whitespace | Working diff whitespace check | Passed |

Observation details:

- Forty Python tests were added over the recorded 121-test baseline. They cover
  design-rule bypasses, typed safe logging and actual worker callback and task
  producers, UTF-8 edges and real subprocess output, redaction and CLI behavior.
- The frontend run adds seven frontend cases. The initial fallback-wrapper run
  used an unsupported Node patch and pnpm and was repeated with the correct
  toolchain. It is not the promoted frontend evidence. The existing large-bundle
  warning remains.
- Five initial sequence-text syntax errors were corrected. Parsing proves syntax,
  not rendered layout or behavior.
- M1 is the original SQLite confirmed-investigation intake.

### Evidence and next step

Retained sanitized evidence is under `.local/validation/design-standard`,
including:

| Artifact | Content |
| --- | --- |
| `fast.txt` | Fast lane output |
| `format.txt` | Format check output |
| `frontend-pinned.txt` | Frontend lane under the supported toolchain |
| `mermaid.json` | Mermaid parse results |
| `smoke.json` | Container smoke result |
| `worker-events.json` | Inspected worker producer events |
| `traceability-summary.json` | Granular traceability summary |
| `deep.json` | Deep product result |

Discarded initial checks remain labelled separately. No dependency locks or
infrastructure image pins changed. Services remain running with data preserved.
No reset was used.

Planning, source and tests used AI assistance and independent component reviews.
No product requirement is completed by this work. Browser microphone and playback,
network-loss recovery, exported product traces, Linux execution, real-model
quality and cost, and capacity still require their stated evidence. Harness child
capture remains time-bounded but not byte-capped. Add a tested cap before noisy
product or media runners. New Python packages still need their own typing,
discovery and advertised-interpreter matrix. Continue with P1-I01 and the first
real inquiry and recovery slice. Keep these requirements in its acceptance packet.
