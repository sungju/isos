#!/bin/bash
# Clear Python bytecode cache
# Run this if you get import errors after updating isos

echo "Clearing Python bytecode cache..."

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Change to the source directory relative to script location
cd "$SCRIPT_DIR/source"

# Remove all .pyc files and __pycache__ directories
find . -type f -name "*.pyc" -delete 2>/dev/null
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

echo "✓ Cache cleared in: $SCRIPT_DIR/source"
echo ""
echo "You can now run isos from any sosreport directory"
