#!/usr/bin/env bash
set -e

source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"

if [ -f "${FLEET_ROOT:-/workspace}/fleet_ws/install/setup.bash" ]; then
  source "${FLEET_ROOT:-/workspace}/fleet_ws/install/setup.bash"
fi

exec "$@"
