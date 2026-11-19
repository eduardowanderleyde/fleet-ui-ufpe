#!/usr/bin/env bash
set -euo pipefail

cd "${FLEET_ROOT:-/workspace}/fleet_ws"
exec ros2 launch fleet_orchestrator turtlebot4_sim.launch.py \
  "world:=${WORLD:-warehouse}" \
  "localization:=${LOCALIZATION:-slam}" \
  "headless:=${HEADLESS:-False}" \
  "x_pose:=${X_POSE:-0.0}" \
  "y_pose:=${Y_POSE:-0.0}" \
  "yaw:=${YAW:-0.0}"
