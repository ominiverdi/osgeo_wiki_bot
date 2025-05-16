# mcp_client/cli/run.sh
#!/bin/bash

# Find the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Run the CLI with any provided arguments
python "$SCRIPT_DIR/cli.py" "$@"