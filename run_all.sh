#!/usr/bin/env bash
# Sobe os 4 processos do Fleet UI (simulação, nós da frota, backend,
# frontend) numa ordem e com as esperas certas, tudo num só comando.
# Ctrl+C aqui encerra tudo de forma limpa: cada processo nasce em sua
# própria sessão (setsid), então um kill no grupo alcança todos os
# sub-processos que ele spawna (gz sim, ros2 launch filhos etc.), o que
# um `kill` simples no PID principal não alcançaria.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
ROOT="$(pwd)"
LOG_DIR="$ROOT/.run_all_logs"
mkdir -p "$LOG_DIR"

PIDS=()
cleanup() {
  echo ""
  echo "Encerrando..."
  for pid in "${PIDS[@]}"; do
    kill -TERM "-$pid" 2>/dev/null
  done
  sleep 1
  for pid in "${PIDS[@]}"; do
    kill -KILL "-$pid" 2>/dev/null
  done
  echo "Tudo encerrado."
}
trap cleanup EXIT INT TERM

wait_for() {
  local logfile="$1" pattern="$2" label="$3" timeout="${4:-60}"
  local waited=0
  until grep -qE "$pattern" "$logfile" 2>/dev/null; do
    sleep 1
    waited=$((waited + 1))
    if [ "$waited" -ge "$timeout" ]; then
      echo "✗ $label não ficou pronto em ${timeout}s — veja $logfile"
      exit 1
    fi
  done
  echo "✓ $label pronto (${waited}s)"
}

echo "[1/4] Simulação (Gazebo + Nav2 + SLAM)..."
setsid bash -c "
  source /opt/ros/jazzy/setup.bash
  source '$ROOT/fleet_ws/install/setup.bash'
  cd '$ROOT/fleet_ws'
  exec ros2 launch fleet_orchestrator turtlebot4_sim.launch.py
" > "$LOG_DIR/1_sim.log" 2>&1 &
PIDS+=($!)
wait_for "$LOG_DIR/1_sim.log" "Managed nodes are active" "simulação" 90

echo "[2/4] Nós da frota (record/replay + coleta)..."
setsid bash -c "
  source /opt/ros/jazzy/setup.bash
  source '$ROOT/fleet_ws/install/setup.bash'
  cd '$ROOT/fleet_ws'
  exec ros2 launch fleet_orchestrator fleet.launch.py single_robot_sim:=true
" > "$LOG_DIR/2_fleet.log" 2>&1 &
PIDS+=($!)
wait_for "$LOG_DIR/2_fleet.log" "sensor_collector ready" "nós da frota" 30

echo "[3/4] Backend (FastAPI)..."
PYTHON_BIN="python3"
[ -x "$ROOT/backend/venv/bin/python3" ] && PYTHON_BIN="$ROOT/backend/venv/bin/python3"
setsid bash -c "
  source /opt/ros/jazzy/setup.bash
  source '$ROOT/fleet_ws/install/setup.bash'
  cd '$ROOT/backend'
  exec '$PYTHON_BIN' main.py
" > "$LOG_DIR/3_backend.log" 2>&1 &
PIDS+=($!)
wait_for "$LOG_DIR/3_backend.log" "Uvicorn running" "backend" 20

echo "[4/4] Frontend (Vite)..."
setsid bash -c "
  cd '$ROOT/frontend'
  exec npm run dev
" > "$LOG_DIR/4_frontend.log" 2>&1 &
PIDS+=($!)
wait_for "$LOG_DIR/4_frontend.log" "Local:" "frontend" 30

echo ""
echo "Tudo pronto -> http://localhost:5173"
echo "Logs em $LOG_DIR/ -- Ctrl+C aqui encerra tudo."
wait
