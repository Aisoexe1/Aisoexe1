#!/bin/bash
# Moodle Assistant — one-time setup

set -e

echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

echo "🌐 Installing Playwright browser..."
playwright install chromium

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next:"
echo "  1. Copy .env.example to .env and fill in your GEMINI_API_KEY"
echo "  2. Run:  python app.py"
echo "  3. Open: http://localhost:8888"
