# Standardized designs and engineering acceptance gates

Status: Completed
Last reviewed: 9 November 2026

## Behavior and scope

Standardize all ten maintained Design.md files and a reusable template with
business/technical tables, sizing, high-level/sequence/low-level Mermaid views,
component ownership, security, observability, metrics, exception handling,
trade-offs and acceptance gates. Add a shared Python engineering guide and make
the documentation harness enforce the structural standard with negative tests.
Preserve the 54 product requirements and existing implementation boundaries.

The boundary review also identified a six-byte echo-prefix mismatch at the
largest accepted diagnostic input. Correct only the authenticated agent-chat
reply bound, preserve request/audio/API bounds and verify exact UTF-8 edges.
Add narrow safe diagnostic-worker event logging at real lifecycle/error producers.
Add bounded allowlisted service-specific logs and preserve diagnostic stderr.
Close the existing read-only SQLite test fixture connection explicitly. Do not
invent product telemetry or change supplier/conversation semantics.

## Interfaces and ownership

Design.md owns component design; charters still own requirements. The validation
plan owns engineering gate sufficiency and the Python guide owns implementation
practices. Optional role fields in documentation.json enforce ordered sections,
populated tables and section-owned diagram types. Structural checks do not prove
Mermaid syntax/meaning or product behavior. The diagnostic text contract adds
explicit request/reply byte bounds without truncation. Worker events must use
fixed safe categories, finite fields and explicit application logger setup.

## Failure cases and validation

Run the documentation rule's positive/negative fixtures, actual Mermaid parser,
granular traceability audit and full fast lane. Check comments, indented/fenced
examples, escaped table pipes, wrong/missing/misplaced diagrams and invalid policy.
For the echo fix, exercise exact and excessive ASCII/multibyte requests/replies,
source trust and reader cleanup. Logging needs schema/level, exception-sentinel,
duplicate-handler, cancellation and context-isolation assertions. Run the affected
frontend lane and actual stack smoke after runtime changes; keep actual browser
and product/live evidence separate. Capture exact commands and outcomes below.

## Results and handoff

All ten maintained Design.md files now follow the 15-section standard, with a
reusable template and shared Python engineering guide. Design policy is enforced
by the documentation harness with positive and negative fixtures. Shared and
project plans/work-item guidance require applicable engineering gates, explicit
Given/When/Then safety and useful-progress criteria, and real diagnostic evidence.
The original 22 PLAN work packages and 54 requirement mappings are unchanged.

Foundation corrections are implemented: explicit 16,384-byte requests versus
16,390-byte authenticated echo replies, shared Unicode/overflow fixtures, safe
fixed-schema worker events from actual producers, and bounded per-service log
inspection. Logs merge both child streams only in the diagnostic action; other
commands preserve their stdout contract. The aggregate log tail can omit earlier
service output; this run's direct Compose worker events were on stdout, so the
observed omission was not attributed to stderr loss. A separate real-child test
verifies stderr preservation. Existing SQLite test cleanup was corrected rather
than suppressing ResourceWarning.

Observed verification:

- Full make check: 161 Python tests passed, zero skips, no ResourceWarning in
  retained suite output; static/module/documentation checks and Ruff passed.
  Mypy passed for ten service files. Forty files passed make format-check.
- Forty Python tests were added over the recorded 121-test baseline, covering
  design-rule bypasses, typed safe logging and actual worker callback/task
  producers, UTF-8 edges and real subprocess output/redaction/CLI behavior.
- Frontend: 66 tests passed, TypeScript checked and production build passed under
  supported Node 24.22.2 and declared pnpm 12.18.0 in an isolated temporary tool
  cache. This adds seven frontend cases. The initial fallback-wrapper run used
  an unsupported Node patch/pnpm and was repeated with the correct toolchain;
  it is not the promoted frontend evidence. Existing large-bundle warning remains.
- Documentation: 60 maintained documents, zero violations. Real Mermaid 11.12.0
  parsing with jsdom 26.1.0 validated all 33 diagrams across ten designs and the
  template; a malformed fixture was rejected. Five initial sequence-text syntax
  errors were corrected. Parsing proves syntax, not rendered layout/behavior.
- Actual preserved-volume local rebuild/start and container smoke passed API
  readiness/authentication, M1 replay/conflict, named dispatch, ordinary echo,
  the full multi-byte 16,384/16,390-byte request/reply and real audio frames.
- The actual logs --service rtc-agent command returned five inspected safe JSON
  producer records: start, completion, cancellation and finish observations.
- Granular traceability remains acyclic with all task references/54 rows intact.
  Deep product result remains incomplete, exit 2: one baseline passed and all
  54 product cases remain not implemented. Working diff whitespace passed.

Retained sanitized evidence is under .local/validation/design-standard, including
fast.txt, format.txt, frontend-pinned.txt, mermaid.json, smoke.json,
worker-events.json, traceability-summary.json and deep.json. Discarded initial
checks remain labelled separately. No dependency locks or infrastructure image
pins changed. Services remain running with data preserved; no reset was used.

Planning, source and tests used AI assistance and independent component reviews.
No product requirement is completed by this work. Browser microphone/playback,
network-loss recovery, exported product traces, Linux execution, real-model
quality/cost and capacity still require their stated evidence. Harness child
capture remains time-bounded but not byte-capped; add a tested cap before noisy
product/media runners. New Python packages still need their own typing/discovery
and advertised-interpreter matrix. Continue with P1-I01 and the first real
inquiry/recovery slice; keep these requirements in its acceptance packet.
