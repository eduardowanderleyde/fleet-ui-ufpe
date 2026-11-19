#!/usr/bin/env bash
set -euo pipefail

cd "${FLEET_ROOT:-/workspace}"
exec npm --prefix frontend run dev -- --host 0.0.0.0
