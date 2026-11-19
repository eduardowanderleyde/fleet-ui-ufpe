#!/usr/bin/env bash
set -e

source "/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash"

if [ -f "${FLEET_ROOT:-/workspace}/fleet_ws/install/setup.bash" ]; then
  source "${FLEET_ROOT:-/workspace}/fleet_ws/install/setup.bash"
fi

# Robô real: na rede do TurtleBot4 do CIn a descoberta do DDS por multicast não
# chega ao PC (19/11/2026). Com ROBOT_IP e CycloneDDS, gera um XML com o robô
# como peer unicast, a menos que CYCLONEDDS_URI já tenha sido definido à mão.
# ROBOT_DDS_UNICAST=false desliga.
if [ -n "${ROBOT_IP:-}" ] && [ -z "${CYCLONEDDS_URI:-}" ] \
   && [ "${RMW_IMPLEMENTATION:-}" = "rmw_cyclonedds_cpp" ] \
   && [ "${ROBOT_DDS_UNICAST:-true}" != "false" ]; then
  cdds_xml="$(python3 "${FLEET_ROOT:-/workspace}/fleet_ws/scripts/cyclone_unicast.py" "${ROBOT_IP}" || true)"
  if [ -n "${cdds_xml}" ] && [ -f "${cdds_xml}" ]; then
    export CYCLONEDDS_URI="file://${cdds_xml}"
  fi
fi

exec "$@"
