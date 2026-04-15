#!/bin/bash
# Validation script for Docker Compose setup
# Checks prerequisites and configuration before starting services

set -e

echo "=========================================="
echo "Voice Kiosk Chatbot - Setup Validation"
echo "=========================================="
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track validation status
ERRORS=0
WARNINGS=0

# Function to print success
success() {
    echo -e "${GREEN}✓${NC} $1"
}

# Function to print error
error() {
    echo -e "${RED}✗${NC} $1"
    ERRORS=$((ERRORS + 1))
}

# Function to print warning
warning() {
    echo -e "${YELLOW}⚠${NC} $1"
    WARNINGS=$((WARNINGS + 1))
}

# Check Docker installation
echo "Checking Docker installation..."
if command -v docker &> /dev/null; then
    DOCKER_VERSION=$(docker --version | awk '{print $3}' | sed 's/,//')
    success "Docker installed: $DOCKER_VERSION"
else
    error "Docker is not installed"
fi

# Check Docker Compose installation
echo "Checking Docker Compose installation..."
if docker compose version &> /dev/null; then
    COMPOSE_VERSION=$(docker compose version --short)
    success "Docker Compose installed: $COMPOSE_VERSION"
else
    error "Docker Compose is not installed"
fi

# Check NVIDIA driver
echo "Checking NVIDIA driver..."
if command -v nvidia-smi &> /dev/null; then
    NVIDIA_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1)
    success "NVIDIA driver installed: $NVIDIA_VERSION"
    
    # Check GPU memory
    GPU_MEMORY=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1)
    if [ "$GPU_MEMORY" -ge 12000 ]; then
        success "GPU memory: ${GPU_MEMORY}MB (sufficient)"
    else
        warning "GPU memory: ${GPU_MEMORY}MB (recommended: ≥12GB)"
    fi
else
    error "NVIDIA driver is not installed"
fi

# Check NVIDIA Container Toolkit
echo "Checking NVIDIA Container Toolkit..."
if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &> /dev/null; then
    success "NVIDIA Container Toolkit is working"
else
    error "NVIDIA Container Toolkit is not working"
fi

# Check directory structure
echo "Checking directory structure..."
REQUIRED_DIRS=("models" "building_kb" "chroma_data" "searxng" "server" "client" "scripts")
for dir in "${REQUIRED_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        success "Directory exists: $dir/"
    else
        warning "Directory missing: $dir/ (run: make setup)"
    fi
done

# Check docker-compose.yml
echo "Checking docker-compose.yml..."
if [ -f "docker-compose.yml" ]; then
    success "docker-compose.yml exists"
    
    # Validate docker-compose.yml syntax
    if docker compose config &> /dev/null; then
        success "docker-compose.yml syntax is valid"
    else
        error "docker-compose.yml has syntax errors"
    fi
else
    error "docker-compose.yml not found"
fi

# Check .env file
echo "Checking environment configuration..."
if [ -f ".env" ]; then
    success ".env file exists"
    
    # Check for required variables
    REQUIRED_VARS=("VLLM_BASE_URL" "OLLAMA_BASE_URL" "TTS_JP_URL" "CHROMADB_PATH")
    for var in "${REQUIRED_VARS[@]}"; do
        if grep -q "^${var}=" .env; then
            success "Environment variable set: $var"
        else
            warning "Environment variable missing: $var (check .env.example)"
        fi
    done
else
    warning ".env file not found (copy from .env.example)"
fi

# Check disk space
echo "Checking disk space..."
AVAILABLE_SPACE=$(df -BG . | tail -1 | awk '{print $4}' | sed 's/G//')
if [ "$AVAILABLE_SPACE" -ge 50 ]; then
    success "Available disk space: ${AVAILABLE_SPACE}GB (sufficient)"
else
    warning "Available disk space: ${AVAILABLE_SPACE}GB (recommended: ≥50GB)"
fi

# Check if models are downloaded
echo "Checking AI models..."
MODEL_DIRS=("models/whisper" "models/embeddings" "models/cosyvoice")
MODELS_FOUND=0
for dir in "${MODEL_DIRS[@]}"; do
    if [ -d "$dir" ] && [ "$(ls -A $dir 2>/dev/null)" ]; then
        success "Models found in: $dir/"
        MODELS_FOUND=$((MODELS_FOUND + 1))
    else
        warning "No models in: $dir/ (run: ./scripts/download_models.sh)"
    fi
done

# Check if building knowledge base exists
echo "Checking building knowledge base..."
if [ -d "building_kb" ] && [ "$(find building_kb -name '*.md' 2>/dev/null | wc -l)" -gt 0 ]; then
    KB_FILES=$(find building_kb -name '*.md' | wc -l)
    success "Knowledge base documents found: $KB_FILES files"
else
    warning "No knowledge base documents found in building_kb/"
fi

# Check if ChromaDB data exists
echo "Checking ChromaDB data..."
if [ -d "chroma_data" ] && [ "$(ls -A chroma_data 2>/dev/null)" ]; then
    success "ChromaDB data exists"
else
    warning "ChromaDB data not found (run: ./scripts/ingest_kb.sh after starting services)"
fi

# Check if services are running
echo "Checking running services..."
if docker compose ps --services --filter "status=running" &> /dev/null; then
    RUNNING_SERVICES=$(docker compose ps --services --filter "status=running" 2>/dev/null | wc -l)
    if [ "$RUNNING_SERVICES" -gt 0 ]; then
        success "Running services: $RUNNING_SERVICES"
        docker compose ps
    else
        warning "No services are currently running (run: make up)"
    fi
else
    warning "No services are currently running (run: make up)"
fi

# Summary
echo ""
echo "=========================================="
echo "Validation Summary"
echo "=========================================="
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed!${NC}"
    echo ""
    echo "You can now start the services with:"
    echo "  make up"
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠ Validation completed with $WARNINGS warning(s)${NC}"
    echo ""
    echo "You can proceed, but some features may not work correctly."
    echo "Review the warnings above and fix them if needed."
else
    echo -e "${RED}✗ Validation failed with $ERRORS error(s) and $WARNINGS warning(s)${NC}"
    echo ""
    echo "Please fix the errors above before starting the services."
    exit 1
fi

echo ""
echo "Next steps:"
echo "1. Start services: make up"
echo "2. Check health: make health"
echo "3. View logs: make logs"
echo "4. Ingest knowledge base: ./scripts/ingest_kb.sh"
