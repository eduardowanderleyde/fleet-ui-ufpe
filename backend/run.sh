#!/bin/bash
# Starts the backend with ROS 2 environment pre-sourced.
# Prerequisites: sudo apt install python3-fastapi python3-uvicorn python3-websockets python3-yaml
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_WS="$WS/fleet_ws"
cd "$WS"

source /opt/ros/jazzy/setup.bash 2>/dev/null || true
source "$ROS_WS/install/setup.bash" 2>/dev/null || true

if ! python3 -c "import fastapi" 2>/dev/null; then
  echo "Error: fastapi not found. Install with:"
  echo "  sudo apt install python3-fastapi python3-uvicorn python3-websockets python3-yaml"
  exit 1
fi

exec python3 "$SCRIPT_DIR/main.py"
