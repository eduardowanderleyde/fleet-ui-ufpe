#!/usr/bin/env bash
# Prepara um clone novo do Fleet UI pra rodar: cria o venv do backend,
# instala as dependências Python e Node, e builda os pacotes ROS 2.
# Roda uma vez (depois de clonar o repo); depois disso é só ./run_all.sh.
#
# Pré-requisito que este script NÃO instala (é do sistema operacional,
# não do repositório): ROS 2 Jazzy desktop + os pacotes de simulação
# listados no README (seção Prerequisites). Instala isso primeiro.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
ROOT="$(pwd)"

echo "[setup] Verificando ROS 2 Jazzy..."
if [ ! -f /opt/ros/jazzy/setup.bash ]; then
  echo "✗ /opt/ros/jazzy/setup.bash não encontrado."
  echo "  Instale o ROS 2 Jazzy (desktop) e os pacotes de simulação listados"
  echo "  no README antes de rodar este script: https://docs.ros.org/en/jazzy/Installation.html"
  exit 1
fi
echo "✓ ROS 2 Jazzy encontrado."

echo "[setup] Build dos pacotes ROS 2 (fleet_orchestrator, fleet_data_collector, fleet_msgs)..."
bash "$ROOT/build.sh"

echo "[setup] Criando venv do backend (backend/venv/)..."
if [ ! -x "$ROOT/backend/venv/bin/python3" ]; then
  python3 -m venv "$ROOT/backend/venv"
fi
"$ROOT/backend/venv/bin/pip" install --quiet --upgrade pip
"$ROOT/backend/venv/bin/pip" install --quiet -r "$ROOT/backend/requirements.lock.txt"
echo "✓ Dependências Python do backend instaladas."

echo "[setup] Instalando dependências do frontend (npm install)..."
( cd "$ROOT/frontend" && npm install --no-fund --no-audit )
echo "✓ Dependências do frontend instaladas."

echo ""
echo "Tudo pronto. Próximo passo: ./run_all.sh"
