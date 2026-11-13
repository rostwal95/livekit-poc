ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE} AS build
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN python -m pip install --no-cache-dir uv==0.13.7
COPY pyproject.toml uv.lock ./
COPY projects/agent-continuity/python/pyproject.toml projects/agent-continuity/python/README.md projects/agent-continuity/python/MANIFEST.in ./projects/agent-continuity/python/
COPY projects/channel-continuity/python/pyproject.toml projects/channel-continuity/python/README.md ./projects/channel-continuity/python/
COPY projects/delegation-reliability/python/pyproject.toml projects/delegation-reliability/python/README.md ./projects/delegation-reliability/python/
# Serving extras only: the joined channel-demo extra runs on the host and needs
# P2/P3 sources that this P1/application runtime image does not contain.
ARG SERVING_EXTRAS="--extra local --extra agent --extra inference --extra provider"
RUN uv sync --frozen ${SERVING_EXTRAS} --no-dev --no-install-workspace
COPY projects/agent-continuity/python/src ./projects/agent-continuity/python/src
COPY services ./services
RUN uv sync --frozen ${SERVING_EXTRAS} --no-dev --no-editable --compile-bytecode

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" XDG_CACHE_HOME=/tmp/cache
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --create-home app \
    && mkdir /data /business && chown 10001:10001 /data /business
WORKDIR /app
COPY --from=build --chown=10001:10001 /app /app
COPY --chown=10001:10001 local-setup/scripts ./local-setup/scripts
USER 10001:10001
CMD ["uvicorn", "services.control_api.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--limit-concurrency", "32", "--timeout-keep-alive", "5", "--no-access-log"]
