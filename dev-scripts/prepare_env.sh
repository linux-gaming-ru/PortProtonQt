#!/usr/bin/env bash

# PortProtonQt: Setup development environment script
# This script prepares the environment for development.

set -e

# Ensure we are in the project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "🚀 Preparing PortProtonQt development environment..."

# 1. Check for uv
if ! command -v uv &> /dev/null; then
    echo "❌ Error: 'uv' is not installed. Please install it first: https://docs.astral.sh/uv/"
    exit 1
fi

# 2. Check if Python 3.11 is already installed via uv
# We look for cpython-3.11 and ensure it doesn't say "<download available>"
if uv python list | grep "cpython-3.11" | grep -qv "<download available>"; then
    echo "✅ Python 3.11 is already available."
else
    echo "🐍 Installing Python 3.11..."
    uv python install 3.11
fi

# 3. Sync dependencies
echo "📦 Syncing dependencies..."
uv sync --all-extras --dev

# 4. Source the virtual environment for this script
# Since this script is bash, we source the bash-compatible activate script
if [ -f ".venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
else
    echo "❌ Error: Virtual environment not found at .venv"
    exit 1
fi

# 5. Install pre-commit hooks
echo "⚓ Installing pre-commit hooks..."
pre-commit install --install-hooks

# 6. Generate translations (.mo files)
echo "🌐 Generating localization files..."
python dev-scripts/l10n.py

echo ""
echo "✅ Environment is ready for development!"

# 7. Inform user how to activate the environment based on their actual shell
detect_current_shell() {
    local parent_pid
    local shell_name

    parent_pid="$(ps -o ppid= -p "$$" | tr -d ' ')"

    if [ -n "$parent_pid" ]; then
        shell_name="$(ps -o comm= -p "$parent_pid" | tr -d ' ')"
    fi

    if [ -z "$shell_name" ]; then
        shell_name="$(basename "${SHELL:-sh}")"
    fi

    echo "$shell_name"
}

CURRENT_SHELL="$(detect_current_shell)"

case "$CURRENT_SHELL" in
    fish)
        ACTIVATE_CMD="source .venv/bin/activate.fish"
        ;;
    nu)
        ACTIVATE_CMD="overlay use .venv/bin/activate.nu"
        ;;
    tcsh|csh)
        ACTIVATE_CMD="source .venv/bin/activate.csh"
        ;;
    *)
        ACTIVATE_CMD="source .venv/bin/activate"
        ;;
esac

echo ""
echo "----------------------------------------------------------------"
echo "Detected shell: $CURRENT_SHELL"
echo "To activate the environment:"
echo "  $ACTIVATE_CMD"
echo "----------------------------------------------------------------"
