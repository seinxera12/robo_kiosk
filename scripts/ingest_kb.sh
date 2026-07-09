#!/bin/bash
# Knowledge base ingestion script
# Ingests building knowledge documents into ChromaDB

set -e

KB_PATH="${KB_PATH:-./building_kb}"
CHROMA_PATH="${CHROMA_PATH:-./chroma_data}"

echo "=== Knowledge Base Ingestion Script ==="
echo "KB Path: $KB_PATH"
echo "ChromaDB Path: $CHROMA_PATH"
echo ""

# Check if KB directory exists
if [ ! -d "$KB_PATH" ]; then
    echo "Error: Knowledge base directory not found: $KB_PATH"
    exit 1
fi

# Run ingestion script
echo "Starting ingestion..."
python3 server/rag/ingest.py \
    --kb-path "$KB_PATH" \
    --chroma-path "$CHROMA_PATH"

echo ""
echo "=== Ingestion Complete ==="
echo "ChromaDB data stored in: $CHROMA_PATH"
