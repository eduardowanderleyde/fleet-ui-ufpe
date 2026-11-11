#!/bin/bash
# Build all ROS 2 packages and apply the ament_python hook fix.
# Run this after cloning or after any source change.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/fleet_ws"

ROS_DISTRO="${ROS_DISTRO:-jazzy}"
echo "[build] Sourcing ROS 2 ${ROS_DISTRO}..."
source /opt/ros/${ROS_DISTRO}/setup.bash

echo "[build] Building ROS 2 packages..."
colcon build --symlink-install

echo "[build] Fixing ament_python hooks (colcon-ros 0.5.0 workaround)..."
bash fix_ament_hooks.sh

echo ""
echo "[build] Done. Source the workspace before running:"
echo "  source $SCRIPT_DIR/fleet_ws/install/setup.bash"
