ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE} AS build
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
RUN python -m pip install --no-cache-dir uv==0.13.7
WORKDIR /opt/piper
COPY local-setup/inference/piper/pyproject.toml local-setup/inference/piper/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp XDG_CACHE_HOME=/tmp PATH="/opt/piper/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libgomp1 && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --create-home app \
    && mkdir -p /opt/inference /models
COPY --from=build /opt/piper/.venv /opt/piper/.venv
RUN /opt/piper/.venv/bin/python -c "import onnxruntime; from piper.voice import PiperVoice; assert callable(PiperVoice.load)"
COPY local-setup/inference/engine.py local-setup/inference/engine_child.py /opt/inference/
COPY local-setup/inference/NOTICES.md /opt/inference/NOTICES.md
USER 10001:10001
EXPOSE 5000
CMD ["python", "/opt/inference/engine.py", "tts"]
