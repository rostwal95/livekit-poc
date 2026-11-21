# check=skip=InvalidDefaultArgInFrom
ARG NODE_IMAGE
ARG PYTHON_IMAGE
FROM ${NODE_IMAGE} AS web
WORKDIR /app
RUN npm install --global pnpm@12.18.0
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/local-console/package.json apps/local-console/
COPY services/channel-policy-gateway/package.json services/channel-policy-gateway/
COPY projects/channel-continuity/package.json projects/channel-continuity/
COPY projects/delegation-reliability/specialist-ts/package.json projects/delegation-reliability/specialist-ts/
RUN pnpm install --frozen-lockfile
COPY apps/local-console apps/local-console
COPY services/channel-policy-gateway services/channel-policy-gateway
COPY projects/channel-continuity projects/channel-continuity
COPY projects/delegation-reliability/specialist-ts projects/delegation-reliability/specialist-ts
RUN pnpm --filter @livekit-ecosystem/channel-continuity build \
    && pnpm --filter @livekit-ecosystem/delegation-specialist build \
    && pnpm --filter @livekit-ecosystem/channel-policy-gateway build \
    && pnpm --filter @livekit-ecosystem/local-console run channel-policy:build

FROM ${PYTHON_IMAGE} AS build
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN python -m pip install --no-cache-dir --root-user-action ignore uv==0.13.7
COPY pyproject.toml uv.lock ./
COPY projects/agent-continuity/python/pyproject.toml projects/agent-continuity/python/
COPY projects/channel-continuity/python/pyproject.toml projects/channel-continuity/python/
COPY projects/delegation-reliability/python/pyproject.toml projects/delegation-reliability/python/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --extra local --extra channel-demo --extra agent
COPY README.md ./
COPY projects/agent-continuity/python projects/agent-continuity/python
COPY projects/channel-continuity/python projects/channel-continuity/python
COPY projects/delegation-reliability/python projects/delegation-reliability/python
COPY services services
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --extra local --extra channel-demo --extra agent \
      --refresh-package agent-continuity --refresh-package channel-continuity \
      --refresh-package delegation-reliability --refresh-package livekit-agent-ecosystem

FROM ${PYTHON_IMAGE}
ENV PATH="/app/.venv/bin:$PATH" LANG=C.UTF-8 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 XDG_CACHE_HOME=/tmp/cache
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 libstdc++6 libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 demo && useradd --no-create-home -u 10001 -g demo demo \
    && install -d -m 0700 -o demo -g demo /app/.local
WORKDIR /app
COPY --from=web /usr/local/bin/node /usr/local/bin/node
# Git checkouts can use an owner-only umask. The runtime user owns its files
# inside the image, including source assets and private launch script inputs.
COPY --chown=10001:10001 --from=web /app /app
COPY --chown=10001:10001 --from=build /app/.venv /app/.venv
COPY --chown=10001:10001 --from=build /app/services/channel_policy_demo /app/services/channel_policy_demo
COPY --chown=10001:10001 local-setup/scripts/channel_policy_launch.py local-setup/scripts/channel_policy_launch_child.py \
    local-setup/scripts/channel_policy_setup.py local-setup/scripts/demo_runtime.py \
    local-setup/scripts/verify_demo_state.py local-setup/scripts/
USER 10001:10001
ENTRYPOINT ["/app/.venv/bin/python"]
