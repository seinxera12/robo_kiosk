# #!/bin/bash
# # Start CosyVoice2 TTS Service

# cd "$(dirname "$0")"

# echo "Starting CosyVoice2 TTS Service..."

# # Check if virtual environment exists
# if [ ! -d "venv" ]; then
#     echo "❌ Virtual environment not found. Run setup first."
#     exit 1
# fi

# # Activate virtual environment
# source venv/bin/activate

# # Add cosyvoice_repo to Python path
# export PYTHONPATH="${PYTHONPATH}:$(pwd)/cosyvoice_repo"

# # Check if CosyVoice is accessible
# if ! python -c "
# import sys
# sys.path.insert(0, 'cosyvoice_repo')
# from cosyvoice.cli.cosyvoice import CosyVoice2
# " 2>/dev/null; then
#     echo "❌ CosyVoice not accessible. Check setup."
#     exit 1
# fi

# # Start the service
# echo "✓ Starting service on http://localhost:5002"
# python app.py

#!/bin/bash
# Start CosyVoice2 TTS Service (fixed stable version)

cd "$(dirname "$0")"

echo "Starting CosyVoice2 TTS Service..."

# Check venv
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found. Run setup first."
    exit 1
fi

# Activate venv
source venv/bin/activate

# =========================
# IMPORTANT FIXES
# =========================

# Ensure local repo import works
export PYTHONPATH="${PYTHONPATH}:$(pwd)/cosyvoice_repo"

# Force stable ModelScope cache usage (prevents weird temp downloads)
export MODELSCOPE_CACHE="$HOME/.cache/modelscope"

# Optional: avoid HF fallback instability
export HF_HUB_ENABLE_HF_TRANSFER=1

# =========================
# Safety check (no runtime import crash)
# =========================
python -c "
import sys
sys.path.insert(0, 'cosyvoice_repo')
from cosyvoice.cli.cosyvoice import CosyVoice2
print('✓ CosyVoice import OK')
" || {
    echo "❌ CosyVoice not accessible. Run setup first."
    exit 1
}

echo "✓ Starting service on http://localhost:5002"

# Run server
python app.py