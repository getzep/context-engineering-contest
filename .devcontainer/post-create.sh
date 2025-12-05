#!/bin/bash
set -e

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                                                                ║"
echo "║      Welcome to the Context Engineering Contest! 🎯           ║"
echo "║                                                                ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "Setting up your environment..."
echo ""

# Navigate to zep-eval-harness directory
cd zep-eval-harness

# Install dependencies with uv
echo "📦 Installing dependencies with uv..."
uv sync

echo "✅ Dependencies installed successfully!"
echo ""

# Check if .env exists in workspace root, if not copy from .env.example
cd ..
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ Created .env file from template in workspace root"
    fi
fi
cd zep-eval-harness

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    Setup Complete! ✨                          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "What we've done for you:"
echo "  ✅ Installed Python dependencies with uv"
echo "  ✅ Created a .env file from template"
echo "  ✅ Set up your development environment"
echo ""
echo "Next steps:"
echo ""
echo "1. Add your API keys to the .env file:"
echo "   📝 Edit: .env (in workspace root)"
echo ""
echo "   You'll need:"
echo "   • ZEP_API_KEY - Get yours at https://app.getzep.com"
echo "     (The marcus_chen_001 dataset is already pre-loaded!)"
echo "   • OPENAI_API_KEY - Provided in the workshop"
echo ""
echo "2. Run your first evaluation:"
echo "   🚀 uv run zep_evaluate.py"
echo ""
echo "3. Check the README for optimization strategies:"
echo "   📖 cat README.md"
echo ""
echo "Your terminal is already in the zep-eval-harness directory."
echo "You're ready to start optimizing! Good luck! 🎯"
echo ""
echo "════════════════════════════════════════════════════════════════"
echo ""
