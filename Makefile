PYTHON ?= python3.14
PNPM ?= corepack pnpm
VENV := .venv
POSTGRES_REPORT ?= .local/validation/postgres/latest.json
P1_SOURCE := projects/agent-continuity/python/src/continuity_lab
P2_SOURCE := projects/channel-continuity/python/src/channel_continuity
P3_SOURCE := projects/delegation-reliability/python/src/delegation_reliability
QUALITY_PATHS := $(P1_SOURCE) $(P2_SOURCE) $(P3_SOURCE) services harness local-setup tests projects/agent-continuity/tests projects/agent-continuity/examples projects/channel-continuity/tests projects/channel-continuity/examples projects/delegation-reliability/tests projects/delegation-reliability/examples
STRICT_TYPE_PATHS := \
	services/channel_policy_demo/__init__.py \
	services/channel_policy_demo/wire.py \
	services/channel_policy_demo/origin.py \
	services/channel_policy_demo/origin_http.py \
	services/channel_policy_demo/discovery.py \
	services/channel_policy_demo/current_result.py \
	services/channel_policy_demo/current_result_producer.py \
	services/channel_policy_demo/executor.py \
	services/channel_policy_demo/worker_client.py \
	services/channel_policy_demo/origin_router.py \
	services/channel_policy_demo/jobs.py \
	services/channel_policy_demo/case_bridge.py \
	services/channel_policy_demo/result_receiver.py \
	services/channel_policy_demo/public_clients.py \
	services/channel_policy_demo/owner_config.py \
	services/channel_policy_demo/application.py \
	services/channel_policy_demo/__main__.py \
	services/channel_policy_demo/_bounded_loopback_http.py \
	services/channel_policy_demo/_loopback_json.py \
	services/channel_policy_demo/_native_models_sdk.py \
	services/channel_policy_demo/current_result_context.py \
	services/channel_policy_demo/current_result_http.py \
	services/channel_policy_demo/native_models.py \
	services/channel_policy_demo/native_prepare_http.py \
	services/channel_policy_demo/native_worker.py \
	services/channel_policy_demo/native_worker_config.py \
	services/channel_policy_demo/native_room.py \
	services/channel_policy_demo/native_room_admin.py \
	services/channel_policy_demo/native_room_state.py \
	services/channel_policy_demo/native_worker_process.py \
	services/channel_policy_demo/native_provider_models.py \
	services/channel_policy_demo/operator.py \
	services/channel_policy_demo/operator_contract.py \
	services/channel_policy_demo/operator_http.py \
	services/channel_policy_demo/operator_sms.py \
	services/channel_policy_demo/parent.py \
	services/channel_policy_demo/room_control.py \
	services/channel_policy_demo/room_control_client.py \
	services/channel_policy_demo/room_result_client.py \
	services/channel_policy_demo/worker_current_result.py \
	local-setup/scripts/channel_policy_setup.py \
	local-setup/scripts/channel_policy_launch.py \
	local-setup/scripts/channel_policy_launch_child.py \
	local-setup/scripts/p2_prepared_read_check.py \
	local-setup/scripts/p2_prepared_read_evidence.py \
	local-setup/scripts/p2_channel_origin_check.py \
	local-setup/scripts/p3_channel_origin_host.py \
	local-setup/scripts/p3_channel_origin_consumer.py \
	local-setup/scripts/p3_channel_origin_evidence.py \
	local-setup/scripts/p3_channel_origin_http.py \
	local-setup/scripts/p3_channel_origin.py \
	local-setup/scripts/p2_channel_origin_wire.py \
	local-setup/scripts/p2_result_receiver_package_check.py \
	local-setup/scripts/p3_result_return_cases.py \
	local-setup/scripts/p2_result_receiver_evidence.py \
	local-setup/scripts/p2_result_receiver_check.py \
	local-setup/scripts/p3_channel_receiver.py \
	local-setup/scripts/p3_native_policy_check.py \
	projects/delegation-reliability/tests/pg_native_policy_cases.py \
	local-setup/scripts/p3_native_policy_http.py \
	projects/delegation-reliability/examples/native_fixed_policy.py \
	local-setup/scripts/p2_starter_p1.py \
	local-setup/scripts/p2_starter_p1_check.py \
	local-setup/scripts/p2_starter_p1_evidence.py \
	local-setup/scripts/p3_fixed_work_evidence.py \
	local-setup/scripts/p2_standalone_check.py \
	local-setup/scripts/p3_durable_fixed_policy_check.py \
	projects/delegation-reliability/examples/durable_fixed_policy.py \
	projects/delegation-reliability/tests/pg_fixed_policy_execution_cases.py \
	local-setup/scripts/p2_operations_check.py \
	local-setup/scripts/p3_fixed_policy_check.py \
	projects/delegation-reliability/examples/fixed_policy_evaluation.py \
	projects/delegation-reliability/tests/fixed_policy_consumer.py \
	local-setup/scripts/p2_workload_check.py \
	local-setup/scripts/p3_document_check.py \
	local-setup/scripts/p3_document_evidence.py \
	local-setup/scripts/p3_document_package.py \
	projects/delegation-reliability/tests/document_cases.py \
	projects/delegation-reliability/examples/document_extraction.py \
	$(P2_SOURCE) \
	$(P3_SOURCE) \
	harness/process_control.py \
	harness/root_unittest.py \
	local-setup/scripts/p2_current_case_bridge.py \
	local-setup/scripts/p2_rehydration_p1.py \
	local-setup/scripts/p2_rehydration_check.py \
	local-setup/scripts/p2_rehydration_media_check.py \
	local-setup/scripts/p3_package_check.py \
	projects/channel-continuity/examples/rehydration_lab.py \
	projects/delegation-reliability/examples/standalone_policy.py \
	projects/delegation-reliability/tests/pg_standalone_cases.py \
	harness/workload_models.py \
	local-setup/scripts/p1_benchmark.py \
	harness/reliability_models.py \
	local-setup/scripts/p1_reliability.py \
	harness/report_runner.py \
	local-setup/scripts/p1_acceptance.py \
	harness/package_check.py \
	local-setup/scripts/p2_postgres_check.py \
	local-setup/scripts/p3_coordinator_check.py \
	projects/delegation-reliability/tests/pg_coordinator_cases.py \
	local-setup/scripts/p3_execution_check.py \
	projects/delegation-reliability/tests/pg_execution_cases.py \
	local-setup/scripts/p3_case_fixture.py \
	local-setup/scripts/p3_completion_check.py \
	projects/delegation-reliability/tests/pg_completion_cases.py \
	local-setup/scripts/p3_acceptance.py \
	local-setup/scripts/p3_contract_acceptance_check.py \
	projects/delegation-reliability/tests/pg_acceptance_cases.py \
	local-setup/scripts/p2_case_bridge.py \
	local-setup/scripts/p2_routing_check.py \
	local-setup/scripts/p2_confirmation_check.py \
	local-setup/scripts/p3_projection_check.py \
	projects/delegation-reliability/tests/pg_projection_cases.py \
	local-setup/scripts/p2_outbox_check.py \
	local-setup/scripts/p3_processing_check.py \
	projects/delegation-reliability/tests/pg_processing_cases.py \
	local-setup/scripts/p2_callbacks_check.py \
	local-setup/scripts/p3_applicability_check.py \
	projects/delegation-reliability/tests/pg_applicability_cases.py \
	projects/delegation-reliability/examples/result_applicability.py \
	local-setup/scripts/p2_send_policy_check.py \
	local-setup/scripts/p3_action_races_check.py \
	local-setup/scripts/p2_native_check.py \
	local-setup/scripts/p3_deadlines_check.py \
	local-setup/scripts/p2_playback_check.py \
	local-setup/scripts/p2_communication_check.py \
	local-setup/scripts/p2_communication_diagnostics.py \
	local-setup/scripts/p3_recovery_check.py \
	projects/delegation-reliability/tests/pg_recovery_cases.py \
	projects/channel-continuity/examples/native_lab.py \
	projects/channel-continuity/examples/native_scripted.py \
	projects/delegation-reliability/tests/pg_deadline_cases.py \
	local-setup/scripts/p3_action_case_fixture.py \
	projects/delegation-reliability/tests/pg_action_race_cases.py \
	projects/delegation-reliability/examples/policy_completion.py \
	projects/delegation-reliability/examples/result_projection.py \
	projects/delegation-reliability/examples/result_processing.py \
	$(P1_SOURCE)/api.py \
	$(P1_SOURCE)/postgres_api.py \
	$(P1_SOURCE)/testing.py \
	$(P1_SOURCE)/work_models.py \
	$(P1_SOURCE)/work_schema.py \
	$(P1_SOURCE)/work_admin.py \
	$(P1_SOURCE)/work_store.py \
	$(P1_SOURCE)/work_api.py \
	$(P1_SOURCE)/issued_models.py \
	$(P1_SOURCE)/execution_store.py \
	$(P1_SOURCE)/execution_api.py \
	$(P1_SOURCE)/action_models.py \
	$(P1_SOURCE)/action_store.py \
	$(P1_SOURCE)/action_api.py \
	$(P1_SOURCE)/case_control_api.py \
	$(P1_SOURCE)/result_feed_api.py \
	$(P1_SOURCE)/result_feed_models.py \
	$(P1_SOURCE)/result_feed_store.py \
	$(P1_SOURCE)/delivery_models.py \
	$(P1_SOURCE)/delivery_store.py \
	$(P1_SOURCE)/delivery_api.py \
	$(P1_SOURCE)/receiver_api.py \
	services/conversation_agent/inference_settings.py \
	services/conversation_agent/inference_http.py \
	services/conversation_agent/inference_speech.py \
	services/conversation_agent/inference_llm.py \
	local-setup/scripts/local_models.py \
	local-setup/inference/engine.py \
	local-setup/inference/engine_child.py \
	local-setup/scripts/p1_demo_ownership.py \
	local-setup/scripts/p1_real_media.py \
	local-setup/scripts/p1_runtime_acceptance.py \
	local-setup/scripts/prepare_business.py \
	local-setup/provider_config.py \
	services/conversation_agent/provider_settings.py \
	services/conversation_agent/provider_http.py \
	services/conversation_agent/provider_llm.py \
	services/conversation_agent/provider_speech.py \
	services/conversation_agent/provider_inference.py
.PHONY: business-setup browser-setup p1-package-check p1-reliability-plan p1-reliability p1-benchmark p1-benchmark-plan phase-g-demo phase-f-demo phase-e-demo phase-d-demo postgres-check bootstrap check test typecheck format-check frontend-check start stop smoke doctor
bootstrap:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install uv==0.13.7
	$(VENV)/bin/uv sync --frozen --all-extras --dev
check:
	HARNESS_PYTHON=$(VENV)/bin/python sh scripts/harness-check.sh
	$(VENV)/bin/ruff check $(QUALITY_PATHS)
	$(VENV)/bin/mypy services $(P1_SOURCE) $(P2_SOURCE) $(P3_SOURCE) --check-untyped-defs
	$(VENV)/bin/mypy --strict --follow-imports=silent $(STRICT_TYPE_PATHS)
test:
	$(VENV)/bin/python -m unittest discover -s tests -v
	$(VENV)/bin/python -m unittest discover -s projects/agent-continuity/tests -v
	$(VENV)/bin/python -m unittest discover -s projects/channel-continuity/tests -v
	$(VENV)/bin/python -m unittest discover -s projects/delegation-reliability/tests -v
typecheck:
	$(VENV)/bin/mypy services $(P1_SOURCE) $(P2_SOURCE) $(P3_SOURCE) --check-untyped-defs
	$(VENV)/bin/mypy --strict --follow-imports=silent $(STRICT_TYPE_PATHS)
format-check:
	$(VENV)/bin/ruff format --check $(QUALITY_PATHS)
business-setup:
	$(PYTHON) local-setup/stack.py prepare-business

browser-setup:
	$(PNPM) --filter @livekit-ecosystem/local-console exec playwright install chromium

frontend-check:
	@command -v pnpm >/dev/null 2>&1 || { echo "frontend-check: root scripts call pnpm; run 'corepack enable' once (Node ships corepack)." >&2; exit 2; }
	$(PNPM) format:check
	$(PNPM) check
	$(PNPM) test
	$(PNPM) build
	$(PNPM) --filter @livekit-ecosystem/local-console exec vite build --config vite.operations.config.ts
	$(PNPM) --filter @livekit-ecosystem/local-console exec vite build --config vite.p3-background.config.ts
	VITE_P1_CONSOLE_URL=$(P1_CONSOLE_URL) $(PNPM) --filter @livekit-ecosystem/local-console run channel-policy:build
start stop smoke doctor:
	$(PYTHON) local-setup/stack.py $@

postgres-check:
	$(VENV)/bin/python local-setup/scripts/postgres_check.py --report $(POSTGRES_REPORT)

phase-d-demo:
	$(VENV)/bin/python local-setup/scripts/phase_d_demo.py

phase-e-demo:
	$(VENV)/bin/python local-setup/scripts/phase_e_demo.py

phase-f-demo:
	$(VENV)/bin/python local-setup/scripts/phase_f_demo.py

phase-g-demo:
	$(VENV)/bin/python local-setup/scripts/phase_g_demo.py

p1-benchmark-plan:
	$(VENV)/bin/python local-setup/scripts/p1_benchmark.py

p1-benchmark:
	$(VENV)/bin/python local-setup/scripts/p1_benchmark.py --run

p1-package-check:
	$(VENV)/bin/python -m harness.package_check

p1-reliability-plan:
	$(VENV)/bin/python local-setup/scripts/p1_reliability.py

p1-reliability:
	$(VENV)/bin/python local-setup/scripts/p1_reliability.py --run

.PHONY: provider-setup provider-check provider-start provider-stop
provider-setup:
	$(VENV)/bin/python local-setup/stack.py init-providers
provider-check:
	$(VENV)/bin/python local-setup/stack.py check-providers
provider-start:
	$(VENV)/bin/python local-setup/stack.py start-provider
provider-stop:
	$(VENV)/bin/python local-setup/stack.py stop-provider

.PHONY: p2-postgres-check
p2-postgres-check:
	$(VENV)/bin/python local-setup/scripts/p2_postgres_check.py

.PHONY: p2-demo
p2-demo:
	$(VENV)/bin/python local-setup/scripts/p2_postgres_check.py --example

.PHONY: p3-demo
p3-demo:
	$(PNPM) --filter @livekit-ecosystem/delegation-specialist demo

.PHONY: p2-dispatch-check p3-coordinator-check
p2-dispatch-check:
	$(VENV)/bin/python local-setup/scripts/p2_postgres_check.py --dispatch

p3-coordinator-check:
	$(VENV)/bin/python local-setup/scripts/p3_coordinator_check.py

.PHONY: p2-gateway-check p3-execution-check
p2-gateway-check:
	$(VENV)/bin/python local-setup/scripts/p2_postgres_check.py --gateway

p3-execution-check:
	$(VENV)/bin/python local-setup/scripts/p3_execution_check.py

.PHONY: p2-agent-check p3-completion-check
p2-agent-check:
	$(VENV)/bin/python local-setup/scripts/p2_postgres_check.py --agent

p3-completion-check:
	$(VENV)/bin/python local-setup/scripts/p3_completion_check.py

.PHONY: p2-routing-check p3-contract-check
p2-routing-check:
	$(VENV)/bin/python local-setup/scripts/p2_routing_check.py
p3-contract-check:
	$(VENV)/bin/python local-setup/scripts/p3_contract_acceptance_check.py --case P3-03
	$(VENV)/bin/python local-setup/scripts/p3_contract_acceptance_check.py --case P3-11

.PHONY: p2-confirmation-check p3-projection-check
p2-confirmation-check:
	$(VENV)/bin/python local-setup/scripts/p2_confirmation_check.py
p3-projection-check:
	$(VENV)/bin/python local-setup/scripts/p3_projection_check.py

.PHONY: p2-outbox-check p3-processing-check
p2-outbox-check:
	$(VENV)/bin/python local-setup/scripts/p2_outbox_check.py
p3-processing-check:
	$(VENV)/bin/python local-setup/scripts/p3_processing_check.py

.PHONY: p2-callbacks-check p3-applicability-check
p2-callbacks-check:
	$(VENV)/bin/python local-setup/scripts/p2_callbacks_check.py
p3-applicability-check:
	$(VENV)/bin/python local-setup/scripts/p3_applicability_check.py

.PHONY: p2-send-policy-check p3-action-races-check
p2-send-policy-check:
	$(VENV)/bin/python local-setup/scripts/p2_send_policy_check.py
p3-action-races-check:
	$(VENV)/bin/python local-setup/scripts/p3_action_races_check.py

.PHONY: p2-native-check p2-native-build p3-deadlines-check
p2-native-check:
	$(VENV)/bin/python local-setup/scripts/p2_native_check.py
p2-native-build:
	$(PNPM) --filter @livekit-ecosystem/channel-continuity build
	$(PNPM) --filter @livekit-ecosystem/local-console exec vite build --config vite.native.config.ts
p3-deadlines-check:
	$(VENV)/bin/python local-setup/scripts/p3_deadlines_check.py

.PHONY: p2-playback-check p3-recovery-check
p2-playback-check:
	$(VENV)/bin/python local-setup/scripts/p2_playback_check.py
p3-recovery-check:
	$(VENV)/bin/python local-setup/scripts/p3_recovery_check.py

.PHONY: p2-communication-check
p2-communication-check:
	$(VENV)/bin/python local-setup/scripts/p2_communication_check.py


.PHONY: p2-rehydration-check p2-rehydration-media-check p3-package-check p3-package-lab-check
p2-rehydration-check:
	$(VENV)/bin/python local-setup/scripts/p2_rehydration_check.py
p2-rehydration-media-check:
	$(VENV)/bin/python local-setup/scripts/p2_rehydration_media_check.py
p3-package-check:
	$(VENV)/bin/python local-setup/scripts/p3_package_check.py
p3-package-lab-check:
	$(VENV)/bin/python local-setup/scripts/p3_package_check.py --lab

.PHONY: p2-workload-plan p2-workload-check p3-document-plan p3-document-check p3-document-package-check
p2-workload-plan:
	$(VENV)/bin/python local-setup/scripts/p2_workload_check.py --plan
p2-workload-check:
	$(VENV)/bin/python local-setup/scripts/p2_workload_check.py
p3-document-plan:
	$(VENV)/bin/python local-setup/scripts/p3_document_check.py --plan
p3-document-check:
	$(VENV)/bin/python local-setup/scripts/p3_document_check.py
p3-document-package-check:
	$(VENV)/bin/python local-setup/scripts/p3_document_check.py --installed

.PHONY: p2-operations-plan p2-operations-check p2-operations-build p3-fixed-policy-plan p3-fixed-policy-check p3-fixed-policy-package-check
p2-operations-plan:
	$(VENV)/bin/python local-setup/scripts/p2_operations_check.py --plan
p2-operations-check:
	$(VENV)/bin/python local-setup/scripts/p2_operations_check.py
p2-operations-build:
	$(PNPM) --filter @livekit-ecosystem/channel-continuity build
	$(PNPM) --filter @livekit-ecosystem/local-console exec tsc --project tsconfig.operations.json
	$(PNPM) --filter @livekit-ecosystem/local-console exec vite build --config vite.operations.config.ts
p3-fixed-policy-plan:
	$(VENV)/bin/python local-setup/scripts/p3_fixed_policy_check.py --plan
p3-fixed-policy-check:
	$(VENV)/bin/python local-setup/scripts/p3_fixed_policy_check.py
p3-fixed-policy-package-check:
	$(VENV)/bin/python local-setup/scripts/p3_fixed_policy_check.py --installed

.PHONY: p2-standalone-plan p2-standalone-check p3-fixed-work-plan p3-fixed-work-check p3-fixed-work-package-check
p2-standalone-plan:
	$(VENV)/bin/python local-setup/scripts/p2_standalone_check.py --plan
p2-standalone-check:
	$(VENV)/bin/python local-setup/scripts/p2_standalone_check.py
p3-fixed-work-plan:
	$(VENV)/bin/python local-setup/scripts/p3_durable_fixed_policy_check.py --plan
p3-fixed-work-check:
	$(VENV)/bin/python local-setup/scripts/p3_durable_fixed_policy_check.py
p3-fixed-work-package-check:
	$(VENV)/bin/python local-setup/scripts/p3_durable_fixed_policy_check.py --installed

.PHONY: p2-starter-p1-plan p2-starter-p1-check
p2-starter-p1-plan:
	$(VENV)/bin/python local-setup/scripts/p2_starter_p1_check.py --plan
p2-starter-p1-check:
	$(VENV)/bin/python local-setup/scripts/p2_starter_p1_check.py

.PHONY: p3-native-policy-plan p3-native-policy-check p3-native-policy-package-check p3-native-policy-build
p3-native-policy-plan:
	$(VENV)/bin/python local-setup/scripts/p3_native_policy_check.py --plan
p3-native-policy-check:
	$(VENV)/bin/python local-setup/scripts/p3_native_policy_check.py
p3-native-policy-package-check:
	$(VENV)/bin/python local-setup/scripts/p3_native_policy_check.py --installed
p3-native-policy-build:
	$(PNPM) --filter @livekit-ecosystem/local-console exec vite build --config vite.p3-background.config.ts

.PHONY: p2-result-receiver-plan p2-result-receiver-check
p2-result-receiver-plan:
	$(VENV)/bin/python local-setup/scripts/p2_result_receiver_check.py --plan
p2-result-receiver-check:
	$(VENV)/bin/python local-setup/scripts/p2_result_receiver_check.py

.PHONY: p2-result-receiver-package-plan p2-result-receiver-package-check
p2-result-receiver-package-plan:
	$(VENV)/bin/python local-setup/scripts/p2_result_receiver_package_check.py --plan
p2-result-receiver-package-check:
	$(VENV)/bin/python local-setup/scripts/p2_result_receiver_package_check.py

.PHONY: channel-origin-unit channel-origin-package-plan channel-origin-package-check
channel-origin-unit:
	$(VENV)/bin/python -m unittest discover -s tests -p 'test_p*channel_origin*.py' -v
	$(VENV)/bin/python -m unittest discover -s projects/delegation-reliability/tests -p 'test_channel_policy*.py' -v
channel-origin-package-plan:
	$(VENV)/bin/python local-setup/scripts/p2_result_receiver_package_check.py --channel-origin --plan
channel-origin-package-check:
	$(VENV)/bin/python local-setup/scripts/p2_result_receiver_package_check.py --channel-origin

.PHONY: channel-origin-plan channel-origin-check
channel-origin-plan:
	$(VENV)/bin/python local-setup/scripts/p2_channel_origin_check.py --plan
channel-origin-check:
	$(VENV)/bin/python local-setup/scripts/p2_channel_origin_check.py

.PHONY: p2-prepared-read-unit p2-prepared-read-plan p2-prepared-read-check channel-policy-unit channel-policy-package-plan channel-policy-package-check
p2-prepared-read-unit:
	$(VENV)/bin/python -m unittest tests.test_p2_prepared_read_evidence tests.test_p2_prepared_read_gate -v
p2-prepared-read-plan:
	$(VENV)/bin/python local-setup/scripts/p2_prepared_read_check.py --plan
p2-prepared-read-check:
	$(VENV)/bin/python local-setup/scripts/p2_prepared_read_check.py
channel-policy-unit:
	$(VENV)/bin/python -m unittest tests.test_p2_channel_origin_wire tests.test_p3_channel_origin tests.test_p3_channel_origin_http tests.test_p3_channel_origin_composition tests.test_p2_current_case_bridge tests.test_p3_channel_receiver -v
	$(VENV)/bin/python -m unittest discover -s tests -p 'test_channel_policy_*.py' -v
	$(PNPM) --filter @livekit-ecosystem/channel-policy-gateway test

.PHONY: channel-policy-native-worker-plan
channel-policy-native-worker-plan:
	$(VENV)/bin/python -m services.channel_policy_demo.native_worker --plan
channel-policy-package-plan:
	$(VENV)/bin/python local-setup/scripts/p2_result_receiver_package_check.py --root-application --plan
channel-policy-package-check:
	$(VENV)/bin/python local-setup/scripts/p2_result_receiver_package_check.py --root-application

.PHONY: channel-policy-setup-plan channel-policy-python-plan
channel-policy-setup-plan:
	$(VENV)/bin/python local-setup/scripts/channel_policy_setup.py --plan
channel-policy-python-plan:
	$(VENV)/bin/python -m services.channel_policy_demo --plan

# The showcase landing page links the P1 console; only the non-secret UI_PORT is read.
P1_CONSOLE_URL ?= http://127.0.0.1:$(shell $(PYTHON) -c 'import sys; sys.path.insert(0, "local-setup"); import stack; print(stack.configured_ui_port())' 2>/dev/null || echo 13000)/
.PHONY: channel-policy-ui-build channel-policy-ui-dev
channel-policy-ui-build:
	VITE_P1_CONSOLE_URL=$(P1_CONSOLE_URL) $(PNPM) --filter @livekit-ecosystem/local-console run channel-policy:build
channel-policy-ui-dev:
	$(PNPM) --filter @livekit-ecosystem/local-console run channel-policy:dev

.PHONY: channel-policy-launch-plan
channel-policy-launch-plan:
	$(VENV)/bin/python local-setup/scripts/channel_policy_launch.py --plan

# Joined P1+P2+P3 showcase. The profile directory must not exist before setup;
# choose a new CHANNEL_POLICY_PROFILE for each fresh demonstration (the showcase
# window holds sixteen inputs per profile).
CHANNEL_POLICY_PROFILE ?= $(CURDIR)/.local/channel-policy-showcase
NODE_BIN ?= $(shell $(PYTHON) -c 'import os, shutil; print(os.path.realpath(shutil.which("node") or ""))')
DEMO_RECORDING ?= $(CURDIR)/.local/demo-recording

.PHONY: channel-policy-demo-build channel-policy-demo-setup channel-policy-demo-start channel-policy-demo-start-provider channel-policy-demo-record ecosystem-demo-record
channel-policy-demo-build:
	$(PNPM) --filter @livekit-ecosystem/channel-continuity build
	$(PNPM) --filter @livekit-ecosystem/delegation-specialist build
	$(PNPM) --filter @livekit-ecosystem/channel-policy-gateway build
	VITE_P1_CONSOLE_URL=$(P1_CONSOLE_URL) $(PNPM) --filter @livekit-ecosystem/local-console run channel-policy:build
channel-policy-demo-setup:
	$(VENV)/bin/python local-setup/scripts/channel_policy_setup.py prepare --directory $(CHANNEL_POLICY_PROFILE) --node $(NODE_BIN)
	$(VENV)/bin/python local-setup/scripts/channel_policy_setup.py associate-sms --directory $(CHANNEL_POLICY_PROFILE) --node $(NODE_BIN)
channel-policy-demo-start:
	$(VENV)/bin/python local-setup/scripts/channel_policy_launch.py serve --profile $(CHANNEL_POLICY_PROFILE)/owner-profile.json --node $(NODE_BIN)
# Real Deepgram/OpenAI/ElevenLabs voice: makes paid provider calls with local-setup/.env.providers.
channel-policy-demo-start-provider:
	$(VENV)/bin/python local-setup/scripts/channel_policy_launch.py serve --profile $(CHANNEL_POLICY_PROFILE)/owner-profile.json --node $(NODE_BIN) --provider
# Records the narrated demo against a running showcase on a fresh profile.
# Set FFMPEG=/path/to/ffmpeg when ffmpeg is not on PATH; without it only WebM is kept.
channel-policy-demo-record:
	cd apps/local-console && node scripts/record-channel-policy-demo.mjs $(CHANNEL_POLICY_PROFILE)/.runtime/operator.json $(DEMO_RECORDING)
# Landing page, the showcase and one P1 business case; needs stack.py start-business.
ecosystem-demo-record:
	cd apps/local-console && node scripts/record-channel-policy-demo.mjs $(CHANNEL_POLICY_PROFILE)/.runtime/operator.json $(DEMO_RECORDING) --complete
