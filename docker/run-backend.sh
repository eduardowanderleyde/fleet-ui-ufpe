#!/usr/bin/env bash
set -euo pipefail

sleep "${BACKEND_START_DELAY:-22}"
cd "${FLEET_ROOT:-/workspace}"
exec bash backend/run.sh
