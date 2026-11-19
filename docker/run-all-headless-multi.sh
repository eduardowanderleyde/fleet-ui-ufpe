#!/usr/bin/env bash
set -euo pipefail

# Windows Docker Desktop mode, adapted for the multi-robot (tb1/tb2[/tb3])
# simulation. Everything runs in one container so ROS 2 DDS discovery stays
# local, which avoids cross-container discovery issues that network_mode:
# host would need on Linux (not available the same way on Docker Desktop for
# Windows/macOS).

FLEET_ROBOTS="${FLEET_ROBOTS:-tb1,tb2}"
# Off by default: the SimulationPanel/"Missão Coordenada" UI (added in
# mission-coordinate-large-scale) launches the sim itself via
# POST /api/simulation/start, tracked in the backend's own _sim_state. That
# endpoint has no idea a sim launched here at boot even exists, so having
# both paths active means clicking "Iniciar simulação" in the browser spawns
# a SECOND Gazebo/Nav2/SLAM on top of this one — same robot names, same
# topics, guaranteed conflict. Set AUTOSTART_SIM=true to get the old
# boots-with-a-running-sim behavior back (e.g. for a headless/CI smoke test
# that never touches the UI's own launch button).
AUTOSTART_SIM="${AUTOSTART_SIM:-false}"

PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  wait || true
}
trap cleanup EXIT INT TERM

# Polls `ros2 topic list` until every pattern given is present, instead of
# sleeping a fixed guess. Falls back to the fixed delay if it times out, so a
# slower-than-expected boot still proceeds instead of hanging forever.
wait_for_topics() {
  local timeout_s="$1"; shift
  local patterns=("$@")
  local waited=0
  while (( waited < timeout_s )); do
    local topics
    topics="$(ros2 topic list 2>/dev/null || true)"
    local missing=0
    for p in "${patterns[@]}"; do
      grep -q "$p" <<<"$topics" || missing=1
    done
    if [ "$missing" -eq 0 ]; then
      echo "[docker] Ready after ${waited}s: ${patterns[*]}"
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  echo "[docker] Timed out after ${timeout_s}s waiting for: ${patterns[*]} (continuing anyway)"
  return 1
}

cd "${FLEET_ROOT:-/workspace}/fleet_ws"

if [ "$AUTOSTART_SIM" = "true" ]; then
  echo "[docker] AUTOSTART_SIM=true: starting headless simulation (${WORLD:-warehouse}, robots=${FLEET_ROBOTS})..."
  ros2 launch fleet_orchestrator turtlebot4_multi_sim.launch.py "world:=${WORLD:-warehouse}" headless:=true &
  PIDS+=("$!")

  # Espera scan+tf de cada robô configurado (não fixo em tb1/tb2/tb3, senão
  # rodar com menos robôs sempre estoura o timeout esperando um tópico que
  # nunca vai existir).
  SCAN_TOPICS=()
  IFS=',' read -ra _robots <<<"$FLEET_ROBOTS"
  for r in "${_robots[@]}"; do SCAN_TOPICS+=("/${r}/scan"); done
  echo "[docker] Waiting for scan+tf topics (up to ${FLEET_START_DELAY:-90}s)..."
  wait_for_topics "${FLEET_START_DELAY:-90}" "${SCAN_TOPICS[@]}" "/${_robots[0]}/tf"

  echo "[docker] Starting fleet nodes (orchestrator + sensor collector)..."
  ros2 launch fleet_orchestrator fleet.launch.py &
  PIDS+=("$!")

  echo "[docker] Waiting for fleet/status (up to ${BACKEND_START_DELAY:-30}s)..."
  wait_for_topics "${BACKEND_START_DELAY:-30}" "/fleet/status"
else
  echo "[docker] AUTOSTART_SIM=false: simulation not launched at boot — use the"
  echo "[docker] 'Missão Coordenada' panel (or POST /api/simulation/start) in the UI."
fi

echo "[docker] Starting backend..."
cd "${FLEET_ROOT:-/workspace}"
bash backend/run.sh &
PIDS+=("$!")

echo "[docker] Starting frontend on http://localhost:5173 ..."
npm --prefix frontend run dev -- --host 0.0.0.0
