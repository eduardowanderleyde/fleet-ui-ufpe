#!/usr/bin/env bash
# Lado do PC para o TurtleBot4 real (make robot-up): mapa + AMCL + Nav2, sem Gazebo.
set -euo pipefail

cd "${FLEET_ROOT:-/workspace}/fleet_ws"
exec ros2 launch fleet_orchestrator turtlebot4_real.launch.py \
  "map:=${ROBOT_MAP:-hall_cin_v4}" \
  "x_pose:=${X_POSE:-1.0216323137283325}" \
  "y_pose:=${Y_POSE:-16.61626625061035}" \
  "yaw:=${YAW:-0.0}"
