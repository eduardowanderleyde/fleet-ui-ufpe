#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[check] Python syntax"
python3 -m py_compile \
  "$ROOT/backend/main.py" \
  "$ROOT/backend/ros_bridge.py" \
  "$ROOT/backend/agents/executor.py" \
  "$ROOT/backend/agents/analyst.py" \
  "$ROOT/backend/agents/planner.py" \
  "$ROOT/backend/agents/tools.py" \
  "$ROOT/fleet_ws/scripts/health_check.py" \
  "$ROOT/fleet_ws/scripts/experiment_repeatability.py" \
  "$ROOT/fleet_ws/scripts/analyze_runs.py" \
  "$ROOT/fleet_ws/src/fleet_orchestrator/fleet_orchestrator/main.py" \
  "$ROOT/fleet_ws/src/fleet_data_collector/fleet_data_collector/main.py"

if ! python3 -c "import numpy" >/dev/null 2>&1; then
  echo "[check] Installing Python analysis dependencies"
  python3 -m pip install --user numpy
fi

if ! python3 -c "import httpx, anthropic" >/dev/null 2>&1; then
  echo "[check] Installing Python agent dependencies"
  python3 -m pip install --user httpx anthropic
fi

echo "[check] Unit tests"
python3 -m unittest discover -s "$ROOT/tests"

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "[check] Installing frontend dependencies"
  npm --prefix "$ROOT/frontend" ci
fi

echo "[check] Frontend build"
npm --prefix "$ROOT/frontend" run build

echo "[check] Done"
