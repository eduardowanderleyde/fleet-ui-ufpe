COMPOSE ?= docker compose

# Percurso do experimento BLE do CBSoft'26 num mundo aberto (ver fleet_ws/scripts/cbsoft/).
# HEADLESS: sem a janela do Gazebo (o frontend mostra o robô); com ela a CPU
# satura e o Nav2 aborta trajetos longos.
# NAV2_*: rota de ~95 m precisa de mais folga no BT e de A* no planner
# (ver _make_nav2_params em turtlebot4_sim.launch.py).
# Domínio ROS próprio: com o padrão (0) a simulação se mistura, na mesma rede,
# com TurtleBot4 reais (que também usam 0) — o Nav2 simulado poderia comandar
# um robô de verdade. Troque com `make cbsoft-up CBSOFT_DOMAIN=<n>`.
CBSOFT_DOMAIN ?= 42
CBSOFT_ENV = ROS_DOMAIN_ID=$(CBSOFT_DOMAIN) WORLD=cbsoft_open LOCALIZATION=amcl HEADLESS=True \
	NAV2_DEFAULT_SERVER_TIMEOUT_MS=1000 NAV2_NAVFN_USE_ASTAR=true \
	X_POSE=1.0216323137283325 Y_POSE=16.61626625061035 YAW=0.0

.PHONY: docker-build docker-up docker-down docker-logs docker-shell docker-check cbsoft-up cbsoft-run cbsoft-csv cbsoft-analise robot-check robot-up

# Fuso local no container: o Timestamp_Legivel do CSV precisa casar com o
# horário do celular (log do nRF Connect), que é local.
TZ_LOCAL := $(shell cat /etc/timezone 2>/dev/null || echo UTC)
# Gravação mais recente, relativa a fleet_ws/ (onde os comandos rodam no container).
LATEST_BAG = $(patsubst fleet_ws/%/,%,$(firstword $(shell ls -td fleet_ws/collections/default/*/ 2>/dev/null)))
# Roda com o usuário do host: assim os CSV/PNG gerados são seus, não do root.
HOST_IDS := $(shell id -u):$(shell id -g)
CBSOFT_RUN = $(COMPOSE) run --rm --no-deps --user $(HOST_IDS) -e HOME=/tmp -e TZ=$(TZ_LOCAL) \
	-v $(CURDIR)/fleet_ws/scripts/cbsoft:/workspace/fleet_ws/scripts/cbsoft:ro -w /workspace/fleet_ws backend
# collections/cbsoft pode ter sido criada pelo root (nav_3points.py roda como
# root no container); devolve só a pasta pro usuário, e só se precisar.
CBSOFT_OWN_DIR = mkdir -p fleet_ws/collections/cbsoft 2>/dev/null; test -w fleet_ws/collections/cbsoft || \
	$(COMPOSE) run --rm --no-deps backend chown $(HOST_IDS) /workspace/fleet_ws/collections/cbsoft

docker-build:
	$(COMPOSE) build

docker-up:
	$(COMPOSE) up

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f

docker-shell:
	$(COMPOSE) run --rm backend bash

docker-check:
	$(COMPOSE) run --rm backend bash check.sh

cbsoft-up:
	mkdir -p fleet_ws/routes/default
	cp fleet_ws/scripts/cbsoft/percurso_cbsoft.yaml fleet_ws/routes/default/
	$(CBSOFT_ENV) $(COMPOSE) up

cbsoft-run:
	$(COMPOSE) exec -w /workspace/fleet_ws sim bash -c "source /opt/ros/jazzy/setup.bash && source install/setup.bash && python3 -u scripts/cbsoft/nav_3points.py --sim --log-dir collections/cbsoft"

# Gravação do replay (MCAP) → CSV no formato do nav_3points.py, em collections/cbsoft/.
#   make cbsoft-csv                       (gravação mais recente)
#   make cbsoft-csv BAG=collections/default/<pasta> POSE=ground_truth
cbsoft-csv:
	@$(CBSOFT_OWN_DIR)
	$(CBSOFT_RUN) python3 scripts/cbsoft/bag_to_nav_csv.py $(or $(BAG),$(LATEST_BAG)) \
		--route routes/default/percurso_cbsoft.yaml --out-dir collections/cbsoft --pose-source $(or $(POSE),amcl)

# Gráficos RSSI × posição (scripts das autoras do experimento). Os arquivos têm de
# estar dentro de fleet_ws/collections/ (pasta montada no container):
#   make cbsoft-analise NAV=collections/cbsoft/<nav>.csv NRF="collections/cbsoft/nrf/<log>.txt"
cbsoft-analise:
	@$(CBSOFT_OWN_DIR)
	$(CBSOFT_RUN) python3 scripts/cbsoft/analise/sync_rssi_nav.py "$(NAV)" "$(NRF)" \
		--out "$(basename $(NAV))_rssi.png"

# Checagem pré-voo contra o TurtleBot4 real (só escuta, não publica nada).
# O robô do CIn usa domínio 0 e CycloneDDS; ajuste se mudar:
#   make robot-check ROBOT_DOMAIN=0 ROBOT_RMW=rmw_cyclonedds_cpp
ROBOT_DOMAIN ?= 0
ROBOT_RMW ?= rmw_cyclonedds_cpp
robot-check:
	$(COMPOSE) run --rm --no-deps -e ROS_DOMAIN_ID=$(ROBOT_DOMAIN) -e RMW_IMPLEMENTATION=$(ROBOT_RMW) \
		-e TZ=$(TZ_LOCAL) -v $(CURDIR)/fleet_ws/scripts:/workspace/fleet_ws/scripts:ro -w /workspace/fleet_ws backend \
		bash -c "source /opt/ros/jazzy/setup.bash && python3 scripts/robot_preflight.py"

# Fleet UI contra o TurtleBot4 real: mapa hall_cin_v4 + AMCL + Nav2 no PC, sem
# Gazebo, relógio do sistema, mesmo domínio e middleware do robô. Rode
# `make robot-check` antes e desligue qualquer Nav2 que já esteja no domínio.
robot-up:
	mkdir -p fleet_ws/routes/default
	cp fleet_ws/scripts/cbsoft/percurso_cbsoft.yaml fleet_ws/routes/default/
	ROS_DOMAIN_ID=$(ROBOT_DOMAIN) RMW_IMPLEMENTATION=$(ROBOT_RMW) TZ=$(TZ_LOCAL) \
		$(COMPOSE) -f docker-compose.yml -f docker-compose.robot.yml up
