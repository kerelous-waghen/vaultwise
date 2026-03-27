#!/bin/bash
# Launch the Family Budget Tracker
cd "$(dirname "$0")"
source .venv/bin/activate

# Check for API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "⚠️  ANTHROPIC_API_KEY not set."
    echo "   Set it with: export ANTHROPIC_API_KEY='your-key-here'"
    echo "   Or enter it in the app's Settings page."
    echo ""
fi

echo "🚀 Starting Family Budget Tracker..."
echo "   Local:   http://localhost:8501"
echo "   Phone:   http://$(ipconfig getifaddr en0 2>/dev/null || echo '<your-ip>'):8501"
echo ""

streamlit run app.py --server.address 0.0.0.0 --server.port 8501
