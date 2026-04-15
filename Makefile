.PHONY: help setup up down restart logs ps health clean rebuild pull

# Default target
help:
	@echo "Voice Kiosk Chatbot - Docker Compose Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make setup          - Create directory structure"
	@echo "  make pull           - Pull latest Docker images"
	@echo ""
	@echo "Service Management:"
	@echo "  make up             - Start all services"
	@echo "  make down           - Stop all services"
	@echo "  make restart        - Restart all services"
	@echo "  make rebuild        - Rebuild and restart services"
	@echo ""
	@echo "Monitoring:"
	@echo "  make logs           - View logs from all services"
	@echo "  make logs-server    - View voice-server logs"
	@echo "  make logs-vllm      - View vLLM logs"
	@echo "  make logs-ollama    - View Ollama logs"
	@echo "  make logs-voicevox  - View VOICEVOX logs"
	@echo "  make logs-searxng   - View SearXNG logs"
	@echo "  make ps             - Show service status"
	@echo "  make health         - Check service health"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean          - Remove stopped containers"
	@echo "  make clean-all      - Remove containers and volumes (WARNING: deletes data)"
	@echo ""
	@echo "Individual Services:"
	@echo "  make restart-server - Restart voice-server only"
	@echo "  make restart-vllm   - Restart vLLM only"
	@echo "  make restart-ollama - Restart Ollama only"

# Setup directory structure
setup:
	@echo "Setting up directory structure..."
	@chmod +x scripts/setup_docker_dirs.sh
	@./scripts/setup_docker_dirs.sh

# Pull latest images
pull:
	@echo "Pulling latest Docker images..."
	@docker compose pull

# Start all services
up:
	@echo "Starting all services..."
	@docker compose up -d
	@echo ""
	@echo "Services started! Check status with: make ps"
	@echo "View logs with: make logs"

# Stop all services
down:
	@echo "Stopping all services..."
	@docker compose down

# Restart all services
restart:
	@echo "Restarting all services..."
	@docker compose restart

# Rebuild and restart services
rebuild:
	@echo "Rebuilding and restarting services..."
	@docker compose up -d --build

# View logs from all services
logs:
	@docker compose logs -f

# View logs from specific services
logs-server:
	@docker compose logs -f voice-server

logs-vllm:
	@docker compose logs -f vllm

logs-ollama:
	@docker compose logs -f ollama

logs-voicevox:
	@docker compose logs -f voicevox

logs-searxng:
	@docker compose logs -f searxng

# Show service status
ps:
	@docker compose ps

# Check service health
health:
	@echo "Checking service health..."
	@echo ""
	@echo "=== Docker Compose Status ==="
	@docker compose ps
	@echo ""
	@echo "=== voice-server health ==="
	@curl -f http://localhost:8000/health 2>/dev/null && echo "✓ voice-server is healthy" || echo "✗ voice-server is unhealthy"
	@echo ""
	@echo "=== vLLM health ==="
	@curl -f http://localhost:8001/health 2>/dev/null && echo "✓ vLLM is healthy" || echo "✗ vLLM is unhealthy"
	@echo ""
	@echo "=== VOICEVOX health ==="
	@curl -f http://localhost:50021/version 2>/dev/null && echo "✓ VOICEVOX is healthy" || echo "✗ VOICEVOX is unhealthy"
	@echo ""
	@echo "=== SearXNG health ==="
	@curl -f http://localhost:8080/ 2>/dev/null && echo "✓ SearXNG is healthy" || echo "✗ SearXNG is unhealthy"
	@echo ""
	@echo "=== GPU Status ==="
	@nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>/dev/null || echo "✗ nvidia-smi not available"

# Clean up stopped containers
clean:
	@echo "Removing stopped containers..."
	@docker compose rm -f

# Clean up everything (WARNING: deletes volumes)
clean-all:
	@echo "WARNING: This will remove all containers and volumes (including ChromaDB data)!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker compose down -v; \
		echo "All containers and volumes removed."; \
	else \
		echo "Cancelled."; \
	fi

# Restart individual services
restart-server:
	@echo "Restarting voice-server..."
	@docker compose restart voice-server

restart-vllm:
	@echo "Restarting vLLM..."
	@docker compose restart vllm

restart-ollama:
	@echo "Restarting Ollama..."
	@docker compose restart ollama

restart-voicevox:
	@echo "Restarting VOICEVOX..."
	@docker compose restart voicevox

restart-searxng:
	@echo "Restarting SearXNG..."
	@docker compose restart searxng

# Ollama model management
ollama-pull:
	@echo "Pulling Qwen2.5:7b-instruct model in Ollama..."
	@docker compose exec ollama ollama pull qwen2.5:7b-instruct

ollama-list:
	@echo "Listing Ollama models..."
	@docker compose exec ollama ollama list

# Development helpers
dev-server:
	@echo "Starting voice-server in development mode with hot reload..."
	@docker compose up voice-server

shell-server:
	@echo "Opening shell in voice-server container..."
	@docker compose exec voice-server /bin/bash

shell-vllm:
	@echo "Opening shell in vLLM container..."
	@docker compose exec vllm /bin/bash

shell-ollama:
	@echo "Opening shell in Ollama container..."
	@docker compose exec ollama /bin/bash
