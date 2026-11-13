ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE} AS build
ARG WHISPER_SOURCE_COMMIT=d1be6fde11ac6e0407606b4e42fe72d34add8037
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp.git /build/whisper \
    && test "$(git -C /build/whisper rev-parse HEAD)" = "${WHISPER_SOURCE_COMMIT}" \
    && cmake -S /build/whisper -B /build/whisper/build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=ON -DWHISPER_BUILD_SERVER=OFF -DWHISPER_CURL=OFF -DWHISPER_COMMON_FFMPEG=OFF -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DGGML_METAL=OFF -DGGML_CUDA=OFF \
    && cmake --build /build/whisper/build --target whisper-cli --parallel 2

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp XDG_CACHE_HOME=/tmp
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 --create-home app \
    && mkdir -p /opt/inference /opt/whisper/bin /opt/licenses /models
COPY --from=build /build/whisper/build/bin/whisper-cli /opt/whisper/bin/whisper-cli
COPY --from=build /build/whisper/LICENSE /opt/licenses/whisper.LICENSE
COPY local-setup/inference/engine.py local-setup/inference/engine_child.py /opt/inference/
USER 10001:10001
EXPOSE 8080
CMD ["python", "/opt/inference/engine.py", "stt"]
