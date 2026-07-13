# Voice Kiosk Chatbot — backend server image.
#
# CUDA runtime base so faster-whisper / torch can use the GPU. The tag targets
# CUDA 12.x; adjust to match the driver on the target server if needed
# (`nvidia-smi` -> "CUDA Version").

# ---------------------------------------------------------------------------
# Stage 1: builder — compiles the deps that have no prebuilt wheels.
#
# misaki[ja] (Japanese G2P, required for Japanese TTS) pulls in pyopenjtalk,
# which is published as an sdist ONLY — there is no binary wheel for any Python
# or platform, so pip must build it from source with CMake and a C/C++ compiler.
# The CUDA *runtime* base has no toolchain, so installing it there dies with
# "CMAKE_C_COMPILER not set" / "unable to find a build program".
#
# The toolchain lives here and is thrown away: only the built wheels are copied
# into the runtime stage, so the shipped image does not carry gcc/g++/cmake.
# ---------------------------------------------------------------------------
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 \
        python3-pip \
        python3.10-dev \
        build-essential \
        cmake \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt /build/requirements.txt

# Build every requirement to a wheel. Packages that already publish wheels are
# passed through unchanged; only the sdist-only ones (pyopenjtalk, and any C
# extensions like mojimoji) are actually compiled here.
RUN python -m pip install --upgrade pip wheel setuptools \
    && python -m pip wheel --wheel-dir /wheels -r /build/requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# System deps: python, curl (used by the container health check), and audio libs
# required by soundfile/torchaudio. No compiler — see the builder stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 \
        python3-pip \
        python3.10-venv \
        curl \
        libsndfile1 \
        ffmpeg \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install from the prebuilt wheels. --no-index so this can never silently fall
# back to building from source (which would fail here — there is no compiler).
COPY --from=builder /wheels /wheels
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-index --find-links=/wheels -r /app/requirements.txt \
    && rm -rf /wheels

# unidic ships without its dictionary; misaki[ja]'s tokenizer (fugashi) needs it
# downloaded once at build time, or Japanese G2P fails at runtime.
RUN python -m unidic download

# OPTIONAL: local faster-whisper STT backend (STT_BACKEND=local).
# The default deployment uses the remote STT service, so this is NOT installed.
# To bake in the local backend, uncomment below AND add the PyAV build deps to
# the apt-get block above (pkg-config libavformat-dev libavcodec-dev
# libavdevice-dev libavutil-dev libavfilter-dev libswscale-dev libswresample-dev):
# COPY requirements-local-stt.txt /app/requirements-local-stt.txt
# RUN python -m pip install -r /app/requirements-local-stt.txt

# Copy the backend source. The package is imported as `server.*`, so it must
# live under /app/server to match `python -m server.main`.
COPY . /app/server

EXPOSE 8765

# Health check mirrors docker-compose; served by the same app on SERVER_PORT.
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT:-8765}/health || exit 1

CMD ["python", "-m", "server.main"]
