# Voice Kiosk Chatbot — backend server image.
#
# CUDA runtime base so faster-whisper / torch can use the GPU. The tag targets
# CUDA 12.x; adjust to match the driver on the target server if needed
# (`nvidia-smi` -> "CUDA Version").
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# System deps: python, curl (used by the container health check), and audio libs
# required by soundfile/torchaudio.
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

# Install Python deps first for layer caching. Build context is ./server (see
# docker-compose.yml), so requirements.txt sits at the context root.
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r /app/requirements.txt

# Copy the backend source. The package is imported as `server.*`, so it must
# live under /app/server to match `python -m server.main`.
COPY . /app/server

EXPOSE 8765

# Health check mirrors docker-compose; served by the same app on SERVER_PORT.
HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT:-8765}/health || exit 1

CMD ["python", "-m", "server.main"]
