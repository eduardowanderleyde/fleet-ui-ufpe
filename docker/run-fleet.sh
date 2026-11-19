#!/usr/bin/env bash
set -euo pipefail

sleep "${FLEET_START_DELAY:-18}"
cd "${FLEET_ROOT:-/workspace}/fleet_ws"
exec ros2 launch fleet_orchestrator fleet.launch.py single_robot_sim:=true
