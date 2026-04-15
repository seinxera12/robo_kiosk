#!/bin/bash
# Setup script for Docker Compose directory structure
# Creates all required directories for the voice chatbot system

set -e

echo "Setting up Docker Compose directory structure..."

# Create model directories
echo "Creating model directories..."
mkdir -p models/whisper
mkdir -p models/embeddings
mkdir -p models/cosyvoice
mkdir -p models/ollama

# Create building knowledge base directories
echo "Creating building knowledge base directories..."
mkdir -p building_kb/floors
mkdir -p building_kb/facilities
mkdir -p building_kb/rooms
mkdir -p building_kb/japanese

# Create ChromaDB persistent storage directory
echo "Creating ChromaDB data directory..."
mkdir -p chroma_data

# Create SearXNG configuration directory (already has settings.yml)
echo "Ensuring SearXNG directory exists..."
mkdir -p searxng

# Set appropriate permissions
echo "Setting directory permissions..."
chmod -R 755 models
chmod -R 755 building_kb
chmod -R 755 chroma_data
chmod -R 755 searxng

echo "✓ Directory structure created successfully!"
echo ""
echo "Next steps:"
echo "1. Download AI models: ./scripts/download_models.sh"
echo "2. Create building knowledge documents in building_kb/"
echo "3. Configure environment variables in .env file"
echo "4. Start services: docker compose up -d"
echo "5. Ingest knowledge base: ./scripts/ingest_kb.sh"
