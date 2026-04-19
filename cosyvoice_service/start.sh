#!/bin/bash
# Start CosyVoice2 TTS Service

cd "$(dirname "$0")"

echo "Starting CosyVoice2 TTS Service..."

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Run setup.sh first."
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Check if CosyVoice is installed
if ! python -c "from cosyvoice.cli.cosyvoice import CosyVoice2" 2>/dev/null; then
    echo "❌ CosyVoice not installed. Run setup.sh first."
    exit 1
fi

# Start the service
echo "✓ Starting service on http://localhost:5002"
python app.py