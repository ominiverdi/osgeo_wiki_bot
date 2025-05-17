#!/bin/bash

# Find the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Debug information
echo "Using Python at: $(which python)"
echo "Python version: $(python --version)"
python -c "import sys; print('Python path:', sys.path)"

# Run the Matrix client
python -m mcp_client.matrix.client "$@"