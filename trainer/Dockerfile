FROM python:3.13-slim-trixie@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39 AS source
ADD --checksum=sha256:495fa6f41f7c0d0a68a44e2053c663fb6291fd44a552577039822c02733b9a5c https://codeload.github.com/ggml-org/llama.cpp/tar.gz/1a24df163920a4744a95373d178d790b72a9bb2f /tmp/llama.tar.gz
RUN mkdir /llama && tar -xzf /tmp/llama.tar.gz -C /llama --strip-components=1

FROM source AS llama-build
RUN apt-get update && apt-get install -y --no-install-recommends cmake make g++ libssl-dev \
    && rm -rf /var/lib/apt/lists/*
RUN cmake -S /llama -B /llama/build -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF \
    -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_OPENSSL=OFF \
    -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF \
    && cmake --build /llama/build --target llama-server -j 2

FROM python:3.13-slim-trixie@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39 AS runtime
LABEL org.opencontainers.image.source="https://github.com/ggml-org/llama.cpp" \
      org.opencontainers.image.revision="1a24df163920a4744a95373d178d790b72a9bb2f"
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=llama-build /llama/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=source /llama/LICENSE /licenses/llama.cpp-LICENSE
COPY --from=source /llama/vendor /licenses/llama.cpp-vendor
USER 10001:10001
ENTRYPOINT ["llama-server"]

FROM python:3.13-slim-trixie@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39 AS trainer
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PATH="/opt/trainer/.venv/bin:$PATH" \
    HF_HUB_DISABLE_TELEMETRY=1 DO_NOT_TRACK=1 HF_HOME=/tmp/huggingface \
    TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2
WORKDIR /opt/trainer
RUN python -m pip install --no-cache-dir uv==0.12.19
COPY trainer/pyproject.toml trainer/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev
COPY --from=source /llama /llama
COPY quartermaster/contracts /opt/trainer/quartermaster/contracts
COPY quartermaster/spike /opt/trainer/quartermaster/spike
COPY quartermaster/__init__.py /opt/trainer/quartermaster/__init__.py
COPY trainer/worker.py /opt/trainer/worker.py
COPY LICENSE /licenses/QuarterMaster-LICENSE
ENV HF_HUB_DISABLE_XET=1 TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor \
    TORCH_EXTENSIONS_DIR=/tmp/torch-extensions TRITON_CACHE_DIR=/tmp/triton
ENTRYPOINT ["python", "/opt/trainer/worker.py"]
