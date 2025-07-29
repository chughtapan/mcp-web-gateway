#!/bin/bash
# Prepare script - Downloads and extracts StableToolBench data

set -e

echo "Preparing StableToolBench data..."
echo "================================"

# Create data directory
mkdir -p data

# Download server cache if not present
if [ ! -f "data/server_cache.zip" ]; then
    echo "Downloading server_cache.zip (230MB)..."
    wget -q --show-progress \
        "https://huggingface.co/datasets/stabletoolbench/Cache/resolve/main/server_cache.zip" \
        -O data/server_cache.zip
fi

# Extract cache (all categories)
echo "Extracting cache (all categories)..."
echo "This may take a few minutes..."
cd data
unzip -q server_cache.zip
cd ..

echo ""
echo "Data preparation complete!"
echo "========================="
echo "Tool categories: $(ls data/tools/ | wc -l)"
echo "Tools: $(find data/tools -name "*.json" | wc -l)"