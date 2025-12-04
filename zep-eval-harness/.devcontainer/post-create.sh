#!/bin/bash
set -e

echo "=========================================="
echo "  Setting up Zep Eval Harness Environment"
echo "=========================================="
echo ""

# Navigate to the project directory
cd /workspaces/*/zep-eval-harness 2>/dev/null || cd /workspaces/zep-eval-harness 2>/dev/null || true

# Install dependencies with uv
echo "Installing dependencies with uv..."
uv sync

echo ""
echo "Dependencies installed successfully!"
echo ""

# Check if .env exists, if not copy from .env.example
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "Created .env from .env.example"
    fi
fi

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "IMPORTANT: Before running the evaluation, you need to add your API keys."
echo ""
echo "Edit the .env file and replace the placeholder values:"
echo "  - ZEP_API_KEY=your_zep_api_key_here"
echo "  - OPENAI_API_KEY=<provided-in-workshop>"
echo ""
echo "Get your Zep API key from: https://app.getzep.com"
echo "(The dataset is already pre-loaded in your Zep account)"
echo ""
echo "Then run the evaluation:"
echo "  uv run zep_evaluate.py"
echo ""
echo "=========================================="
