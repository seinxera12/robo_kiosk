#!/bin/bash
# Setup script for CosyVoice2 TTS Service

set -e  # Exit on error

echo "=========================================="
echo "CosyVoice2 TTS Service Setup"
echo "=========================================="
echo ""

# Check if running from project root
if [ ! -d "cosyvoice_service" ]; then
    echo "❌ Error: Must run from project root directory"
    exit 1
fi

echo "Step 1: Creating Python virtual environment..."
cd cosyvoice_service

if [ -d "venv" ]; then
    echo "⚠ Virtual environment already exists, skipping creation"
else
    python3 -m venv venv
    echo "✓ Virtual environment created"
fi

echo ""
echo "Step 2: Activating virtual environment..."
source venv/bin/activate

echo ""
echo "Step 3: Installing basic requirements..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "Step 4: Cloning CosyVoice repository..."
if [ -d "cosyvoice_repo" ]; then
    echo "⚠ CosyVoice repo already exists, skipping clone"
else
    git clone https://github.com/FunAudioLLM/CosyVoice.git cosyvoice_repo
    echo "✓ Repository cloned"
fi

echo ""
echo "Step 5: Installing CosyVoice dependencies..."
cd cosyvoice_repo
pip install -r requirements.txt

echo ""
echo "Step 6: Installing CosyVoice in editable mode..."
cd ..
pip install -e cosyvoice_repo

echo ""
echo "Step 7: Testing installation..."
python -c "
try:
    from cosyvoice.cli.cosyvoice import CosyVoice2
    print('✓ CosyVoice library imported successfully')
except ImportError as e:
    print(f'❌ Import failed: {e}')
    exit(1)
"

echo ""
echo "Step 8: Testing service startup..."
timeout 10s python app.py &
SERVICE_PID=$!
sleep 5

# Test health endpoint
if curl -f http://localhost:5002/ > /dev/null 2>&1; then
    echo "✓ Service started successfully"
    kill $SERVICE_PID 2>/dev/null || true
else
    echo "❌ Service failed to start"
    kill $SERVICE_PID 2>/dev/null || true
    exit 1
fi

cd ..

echo ""
echo "=========================================="
echo "✓ CosyVoice2 TTS Service setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Start the service:"
echo "     cd cosyvoice_service"
echo "     source venv/bin/activate"
echo "     python app.py"
echo ""
echo "  2. Or use Docker:"
echo "     docker-compose -f docker-compose.cosyvoice.yml up -d"
echo ""
echo "  3. Test the service:"
echo "     curl -X POST http://localhost:5002/synthesize \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"text\": \"Hello, this is a test\"}' \\"
echo "       --output test.wav"
echo ""