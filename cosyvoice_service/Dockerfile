# CosyVoice2 TTS Service Docker Image
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    libsndfile1 \
    libsndfile1-dev \
    ffmpeg \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# Upgrade pip
RUN python3 -m pip install --upgrade pip setuptools wheel

# Set working directory
WORKDIR /app

# Copy requirements and install basic dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Clone and install CosyVoice
RUN git clone https://github.com/FunAudioLLM/CosyVoice.git cosyvoice_repo
WORKDIR /app/cosyvoice_repo
RUN pip install -r requirements.txt
WORKDIR /app
RUN pip install -e cosyvoice_repo

# Copy application code
COPY app.py .

# Expose port
EXPOSE 5002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5002/health || exit 1

# Set default environment variables
ENV COSYVOICE_MODEL_PATH=iic/CosyVoice2-0.5B
ENV COSYVOICE_DEVICE=cuda
ENV HOST=0.0.0.0
ENV PORT=5002

# Start the service
CMD ["python", "app.py"]