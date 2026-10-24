"""
Backend FastAPI: bridge para o fleet (ROS 2).
Rode com o workspace sourceado: source install/setup.bash && python main.py
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import shlex
import signal
import struct
import subprocess
import threading
import time
import zlib

import yaml
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ros_bridge import RosBridge
from agents import Analyst, Executor, Planner, MissionRouter, RobotCandidate, decompose_and_route

# Robôs simulados (mesma variável usada pelos launch files ROS 2 — precisa
# bater com quem realmente existe no Gazebo). SLAM/Nav2 publicam map,
# amcl_pose e tf por-robô em /<id>/..., não mais em tópicos globais. Ver
# fleet_orchestrator._setup_robot_tf.
_ROBOTS = [r.strip() for r in os.environ.get("FLEET_ROBOTS", "tb1,tb2").split(",") if r.strip()]
# Robô usado como default no campo "pose"/"/api/map" sem robot_id explícito
# (compat com clientes antigos que não sabem que existe mais de um robô).
_STATUS_ROBOT_ID = os.environ.get("FLEET_STATUS_ROBOT") or (_ROBOTS[0] if _ROBOTS else "tb1")

# Raiz do projeto (fleet-ui/). Use FLEET_WS para sobrescrever.
WORKSPACE = os.environ.get("FLEET_WS") or str(Path(__file__).resolve().parent.parent)
# Workspace colcon ROS 2 (fleet_ws/ dentro da raiz)
ROS_WS = os.environ.get("FLEET_ROS_WS") or str(Path(WORKSPACE) / "fleet_ws")
_bridge = RosBridge(ROS_WS, ros_distro=os.environ.get("ROS_DISTRO", "jazzy"))

# Status da frota (atualizado pelo subscriber ROS em thread)
_fleet_status: dict = {"robots": []}
_robot_poses: dict[str, dict] = {rid: {"x": 0.0, "y": 0.0, "yaw": 0.0, "valid": False} for rid in _ROBOTS}
_map_metas: dict[str, dict] = {}  # robot_id -> {resolution, origin_x, origin_y, width, height, png_b64}
_status_lock = threading.Lock()
# robot_id -> tf2_ros.Buffer, preenchido por _setup_robot() dentro do
# lifespan — usado por _reset_robot_pose_tracking() pra limpar o buffer
# quando a navegação sequencial desliga/religa um robô (ver comentário lá).
_robot_tf_buffers: dict[str, object] = {}
_robot_tf_last_rx: dict[str, dict[str, float]] = {}


def _reset_robot_pose_tracking(robot_id: str) -> None:
    """Achado ao vivo (2026-09-30): depois de desativar e reativar a
    navegação sequencial de um robô, /api/status parava de refletir a
    posição real dele — o robô navegava e chegava no alvo de verdade
    (confirmado no log do Nav2), mas a pose reportada ficava travada no
    último valor antes da desativação. Causa: o tf2_ros.Buffer de cada robô
    é criado 1x na subida do backend e nunca é resetado; quando o SLAM é
    religado do zero, ele publica /tf com timestamps de sim-time que
    recomeçam mais baixos que os já guardados no buffer velho — o tf2
    silenciosamente rejeita essas atualizações como "dados antigos"
    (mesma classe do aviso TF_OLD_DATA já filtrado como ruído noutro lugar
    deste arquivo). Chamado no início de activate_robot, antes do processo
    novo subir, pra não ter dado velho competindo com o novo."""
    buf = _robot_tf_buffers.get(robot_id)
    if buf is not None:
        buf.clear()
    with _status_lock:
        _robot_poses[robot_id] = {"x": 0.0, "y": 0.0, "yaw": 0.0, "valid": False}
_ws_clients: list[WebSocket] = []


def _ros_env():
    return _bridge.ros_env()


def _run_ros2_service(srv: str, srv_type: str, request_json: str, timeout: int = 10) -> tuple[bool, str]:
    return _bridge.run_service(srv, srv_type, request_json, timeout=timeout)


def _encode_map_png(data: list, width: int, height: int) -> bytes:
    """Codifica OccupancyGrid como PNG RGBA colorido (Y flipado para canvas).
    Paleta:
      desconhecido (-1): azul-cinza suave   #b0bcc8  semi-transparente
      livre        ( 0): branco quente      #f5f5f0
      ocupado      (>0): azul-escuro        #2d3748
    """
    # RGBA 4 bytes por pixel
    pixels: list[tuple[int, int, int, int]] = []
    for v in data:
        if v < 0:
            pixels.append((176, 188, 200, 210))  # desconhecido: azul-cinza
        elif v == 0:
            pixels.append((245, 245, 240, 255))  # livre: creme quase branco
        else:
            pixels.append((45, 55, 72, 255))     # ocupado: azul-escuro

    def make_row(row_idx: int) -> bytes:
        row = bytearray([0])  # filter type None
        for r, g, b, a in pixels[row_idx * width:(row_idx + 1) * width]:
            row.extend([r, g, b, a])
        return bytes(row)

    # Flipa Y: row 0 do PNG = maior y do mundo
    raw = b''.join(make_row(height - 1 - y) for y in range(height))
    compressed = zlib.compress(raw, 6)

    def png_chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack('>I', len(payload)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)

    png = b'\x89PNG\r\n\x1a\n'
    # color_type=6 → RGBA
    png += png_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
    png += png_chunk(b'IDAT', compressed)
    png += png_chunk(b'IEND', b'')
    return png


def _read_pgm(path: Path) -> tuple[int, int, int, bytes]:
    """Lê .pgm P2 (ASCII) ou P5 (binário, o formato padrão gerado pelo
    map_saver do Nav2/ROS). Devolve (width, height, maxval, pixels)."""
    data = path.read_bytes()
    pos = 0

    def next_token() -> bytes:
        nonlocal pos
        while True:
            while pos < len(data) and data[pos:pos + 1].isspace():
                pos += 1
            if pos < len(data) and data[pos:pos + 1] == b'#':
                while pos < len(data) and data[pos:pos + 1] != b'\n':
                    pos += 1
                continue
            break
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        return data[start:pos]

    magic = next_token()
    if magic not in (b'P2', b'P5'):
        raise ValueError(f"PGM inválido (magic={magic!r})")
    width  = int(next_token())
    height = int(next_token())
    _maxval = int(next_token())
    pos += 1  # 1 byte de whitespace exato separando o header dos dados (convenção PGM)

    if magic == b'P5':
        pixels = data[pos:pos + width * height]
    else:
        pixels = bytes(int(t) for t in data[pos:].split()[: width * height])

    return width, height, _maxval, pixels


def _pgm_to_occupancy_png(width: int, height: int, pixels: bytes, negate: bool,
                           occupied_thresh: float, free_thresh: float) -> bytes:
    """Converte pixels PGM em PNG RGBA com a mesma paleta de _encode_map_png,
    usando a fórmula de ocupação do map_server do Nav2 (modo trinary).
    PGM já é top-down como o PNG de saída — sem flip de Y aqui (diferente de
    _encode_map_png, que parte de OccupancyGrid, armazenado bottom-up)."""
    pixel_colors = []
    for v in pixels:
        occ = (v / 255.0) if negate else ((255 - v) / 255.0)
        if occ > occupied_thresh:
            pixel_colors.append((45, 55, 72, 255))     # ocupado
        elif occ < free_thresh:
            pixel_colors.append((245, 245, 240, 255))  # livre
        else:
            pixel_colors.append((176, 188, 200, 210))  # desconhecido

    def make_row(row_idx: int) -> bytes:
        row = bytearray([0])
        for r, g, b, a in pixel_colors[row_idx * width:(row_idx + 1) * width]:
            row.extend([r, g, b, a])
        return bytes(row)

    raw = b''.join(make_row(y) for y in range(height))
    compressed = zlib.compress(raw, 6)

    def png_chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack('>I', len(payload)) + body + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF)

    png = b'\x89PNG\r\n\x1a\n'
    png += png_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
    png += png_chunk(b'IDAT', compressed)
    png += png_chunk(b'IEND', b'')
    return png


class RunConfigRequest(BaseModel):
    command: Literal["record", "replay"] = "record"
    robot: str = "default"
    route: str = "percurso1"
    collect: bool = True
    topics: list[str] = Field(default_factory=lambda: ["scan", "odom", "imu", "pose"])
    initial_pose: list[float] | None = None
    points: list[list[float]] = Field(default_factory=list)
    return_to_start: list[float] | None = None
    run_label: str | None = None           # metadado livre (ex.: par de dispositivo BLE) — só viaja pro JSON exportado
    ble_target_address: str | None = None  # se dado, seta via `ros2 param set` antes de rodar (ble_rssi_publisher já tem que estar de pé)


class SaveRouteWaypointsRequest(BaseModel):
    robot_id: str = ""
    route_name: str
    waypoints: list[dict]


class SshTestRequest(BaseModel):
    host: str
    user: str = "ubuntu"
    port: int = 22


class AgentRunRequest(BaseModel):
    instruction: str
    model: str = "claude-sonnet-5"


class AgentFleetRunRequest(BaseModel):
    instructions: dict[str, str]  # robot_id → instrução
    model: str = "claude-sonnet-5"


class AgentMissionRequest(BaseModel):
    mission: str
    candidates: list[str] | None = None  # None = usa todos os robôs conhecidos em _fleet_status
    model: str = "claude-sonnet-5"


class RunCampaignRequest(BaseModel):
    robot: str = "default"
    route: str = "percurso1"
    points: list[list[float]] = Field(default_factory=list)  # waypoints da gravação baseline
    repetitions: int = 3
    collect: bool = True
    topics: list[str] = Field(default_factory=lambda: ["scan", "odom", "imu", "pose"])
    return_to_start: list[float] | None = None
    run_id: str | None = None  # gerado automaticamente se omitido


class StartSimulationRequest(BaseModel):
    mode: Literal["single", "multi"] = "single"
    world: str = "warehouse"
    robots: list[str] = Field(default_factory=lambda: ["tb1", "tb2"])  # ignorado se mode="single"
    # Só válido com mode="multi": sobe Gazebo + robôs spawnados SEM SLAM/Nav2
    # de ninguém (bringup_nav:=false no launch file) — a navegação de cada
    # robô liga sob demanda via /api/simulation/activate_robot. Existe pra
    # evitar rodar N pilhas de Nav2 completas ao mesmo tempo (teto real de
    # /clock confirmado com 2+ robôs simultâneos, ver orquestracion.md),
    # mantendo todos os robôs visíveis juntos na cena.
    sequential_nav: bool = False


def _model_dump(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _cors_origins() -> list[str]:
    raw = os.environ.get("FLEET_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    def run_ros():
        try:
            import rclpy
            from rclpy.node import Node
            import rclpy.callback_groups
            from fleet_msgs.msg import FleetStatus
            from geometry_msgs.msg import PoseWithCovarianceStamped
            from nav_msgs.msg import OccupancyGrid

            rclpy.init()
            node = Node("fleet_ui_bridge", parameter_overrides=[
                rclpy.parameter.Parameter("use_sim_time", rclpy.parameter.Parameter.Type.BOOL, FLEET_USE_SIM_TIME)
            ])

            def fleet_cb(msg):
                with _status_lock:
                    _fleet_status["robots"] = [
                        {
                            "robot_id": r.robot_id,
                            "role": r.role,
                            "nav_state": r.nav_state,
                            "current_route": r.current_route,
                            "collection_on": r.collection_on,
                            "collection_file": r.collection_file,
                            "last_error": r.last_error,
                            "bytes_written": r.bytes_written,
                        }
                        for r in msg.robots
                    ]
                    _fleet_status["robots_at"] = time.monotonic()

            # TF lookup: map -> base_link por robô (fallback contínuo; /pose
            # do slam_toolbox só publica esporadicamente, não dá pose ao
            # vivo). tf2_ros.TransformListener hardcoda a subscrição em /tf e
            # /tf_static (tópicos globais); nesse branch cada robô publica em
            # /<id>/tf, então replicamos manualmente 1 Buffer + subscrições
            # namespaced por robô (mesmo padrão de
            # fleet_orchestrator._setup_robot_tf). Executor trocado para
            # MultiThreadedExecutor logo abaixo para não deixar o volume alto
            # de /tf de N robôs atrasar fleet/status e os N maps.
            import tf2_ros
            from rclpy.time import Time as RclpyTime
            from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy, ReliabilityPolicy
            from tf2_msgs.msg import TFMessage

            def _setup_robot(rid: str) -> None:
                prefix = f"/{rid}" if rid else ""
                tf_buffer = tf2_ros.Buffer()
                _robot_tf_buffers[rid] = tf_buffer

                tf_last_rx: dict[str, float] = {}
                _robot_tf_last_rx[rid] = tf_last_rx

                def _tf_dynamic_cb(msg):
                    for t in msg.transforms:
                        tf_buffer.set_transform(t, "default_authority")
                        if t.child_frame_id in ("odom", "base_link"):
                            with _status_lock:
                                tf_last_rx[f"{t.header.frame_id}->{t.child_frame_id}"] = (
                                    t.header.stamp.sec + t.header.stamp.nanosec * 1e-9
                                )

                def _tf_static_cb(msg):
                    for t in msg.transforms:
                        tf_buffer.set_transform_static(t, "default_authority")

                node.create_subscription(
                    TFMessage, f"{prefix}/tf", _tf_dynamic_cb,
                    QoSProfile(depth=100, durability=DurabilityPolicy.VOLATILE, history=HistoryPolicy.KEEP_LAST),
                )
                node.create_subscription(
                    TFMessage, f"{prefix}/tf_static", _tf_static_cb,
                    QoSProfile(depth=100, durability=DurabilityPolicy.TRANSIENT_LOCAL, history=HistoryPolicy.KEEP_LAST),
                )

                def tf_timer_cb():
                    try:
                        t = tf_buffer.lookup_transform("map", "base_link", RclpyTime())
                        tr = t.transform.translation
                        q = t.transform.rotation
                        yaw = math.atan2(
                            2.0 * (q.w * q.z + q.x * q.y),
                            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
                        )
                        with _status_lock:
                            _robot_poses.setdefault(rid, {}).update(
                                {"x": tr.x, "y": tr.y, "yaw": yaw, "valid": True,
                                 "source": "tf", "tf_ok_at": time.time()}
                            )
                    except Exception as exc:
                        with _status_lock:
                            _robot_poses.setdefault(rid, {})["tf_error"] = f"{type(exc).__name__}: {exc}"[:200]

                node.create_timer(0.1, tf_timer_cb)

                def amcl_cb(msg):
                    p = msg.pose.pose.position
                    q = msg.pose.pose.orientation
                    yaw = math.atan2(
                        2.0 * (q.w * q.z + q.x * q.y),
                        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
                    )
                    with _status_lock:
                        cur = _robot_poses.setdefault(rid, {})
                        # O TF (map→base_link a 10 Hz) é mais novo que esta pose,
                        # que sai da última atualização do filtro; sobrescrever
                        # fazia o robô "pular pra trás" na tela. Só vale como
                        # reserva quando o TF parou de responder.
                        if time.time() - cur.get("tf_ok_at", 0.0) < _TF_FRESH_S:
                            return
                        cur.update(
                            {"x": p.x, "y": p.y, "yaw": yaw, "valid": True,
                             "source": "pose_topic", "pose_topic_at": time.time()}
                        )

                # AMCL publica /amcl_pose TRANSIENT_LOCAL e só republica com movimento.
                amcl_qos = QoSProfile(
                    depth=1,
                    reliability=ReliabilityPolicy.RELIABLE,
                    durability=DurabilityPolicy.TRANSIENT_LOCAL,
                )
                node.create_subscription(PoseWithCovarianceStamped, f"{prefix}/amcl_pose", amcl_cb, amcl_qos)
                node.create_subscription(PoseWithCovarianceStamped, f"{prefix}/pose", amcl_cb, 10)

                def map_cb(msg):
                    info = msg.info
                    if info.width == 0 or info.height == 0:
                        return
                    try:
                        png = _encode_map_png(list(msg.data), info.width, info.height)
                        b64 = base64.b64encode(png).decode()
                        with _status_lock:
                            _map_metas[rid] = {
                                "resolution": info.resolution,
                                "origin_x": info.origin.position.x,
                                "origin_y": info.origin.position.y,
                                "width": info.width,
                                "height": info.height,
                                "png_b64": b64,
                            }
                    except Exception as e:
                        node.get_logger().warning(f"map_cb({rid!r}) error: {e}")

                # TRANSIENT_LOCAL: map_server (modo AMCL) publica /map uma vez só;
                # assinatura VOLATILE nunca recebe esse mapa travado.
                map_qos = QoSProfile(
                    depth=1,
                    reliability=ReliabilityPolicy.RELIABLE,
                    durability=DurabilityPolicy.TRANSIENT_LOCAL,
                )
                node.create_subscription(OccupancyGrid, f"{prefix}/map", map_cb, map_qos)

            for _rid in _ROBOTS:
                _setup_robot(_rid)
            # modo single usa robot_id="" (tópicos sem prefixo, ex. /tf em
            # vez de /tb1/tf) — sem isso, pose/mapa do robô único nunca
            # ficam disponíveis via /api/status e /api/map.
            _setup_robot("")

            # Verifica Nav2 periodicamente. Usava `ros2 action list` e considerava
            # pronto assim que o nome da ação aparecesse no grafo — achado ao vivo
            # (2026-09-25): o action server do bt_navigator é criado durante
            # "Configuring", bem antes do lifecycle_manager terminar de ativar a
            # pilha inteira (confirmado cronometrando: ação aparecia ~1min antes
            # do log real dizer "Managed nodes are active"). Ou seja, media
            # "o server existe", não "o server aceita objetivos de verdade" — um
            # goToPoint mandado nessa janela falsa era descartado silenciosamente
            # (bt_navigator ainda não Active), sem log nenhum do lado do robô.
            # Agora confere o ESTADO REAL do lifecycle node via `ros2 lifecycle
            # get`, o mesmo sinal que o lifecycle_manager usa pra decidir
            # "Managed nodes are active" — só conta como pronto quando o estado
            # é literalmente "active" (não "inactive"/"configuring"/etc).
            def _bt_navigator_is_active(rid: str) -> bool:
                # `timeout` (o comando shell, não o parâmetro do subprocess.run)
                # de propósito: `ros2 lifecycle get` num nó que não existe
                # ainda fica esperando descoberta DDS sem limite próprio.
                # subprocess.run(timeout=) só mata o processo direto (o
                # `bash -c`), não o `ros2` que ele lança por baixo — achado ao
                # vivo virando zumbi de verdade (processos `ros2 lifecycle get`
                # sobrevivendo minutos, competindo por CPU/DDS com o bringup
                # real). O comando `timeout` do coreutils mata quem ELE lança
                # diretamente, então funciona onde o parâmetro do Python não
                # funcionava.
                node_name = f"/{rid}/bt_navigator" if rid else "/bt_navigator"
                try:
                    r = subprocess.run(
                        # 5 s: a chamada leva ~2,0 s mesmo com o daemon do ros2
                        # de pé (medido no Docker); com 2 s estourava sob carga
                        # e o frontend mostrava "Nav2 offline" com o robô andando.
                        ["bash", "-c", f"source /opt/ros/jazzy/setup.bash 2>/dev/null; timeout 5 ros2 lifecycle get {shlex.quote(node_name)} 2>/dev/null"],
                        capture_output=True, text=True, timeout=7,
                    )
                    return r.stdout.strip().lower().startswith("active")
                except Exception:
                    return False

            # Bug real achado ao vivo (2026-09-25): `ros2 lifecycle get` num nó
            # que ainda não existe (ex.: checando /tb1/bt_navigator durante uma
            # simulação single-robot, sem namespace nenhum — _ROBOTS é fixo,
            # lido 1x na subida do backend, não sabe o modo da simulação atual)
            # não falha rápido, ele espera o timeout inteiro de descoberta DDS.
            # Como o timer roda a cada 3s independente do tick anterior ter
            # terminado, isso empilhava dezenas de processos `ros2 lifecycle
            # get` concorrentes disputando CPU/DDS com o bringup de verdade —
            # confirmado ao vivo: 2 bringups single-robot seguidos travaram em
            # timeouts de lifecycle (`change_state`) com o pgrep mostrando
            # vários `ros2 lifecycle get` acumulados. Corrigido com (1) trava
            # simples pra nunca ter 2 ticks em voo ao mesmo tempo e (2) checar
            # só os robôs da simulação ATUAL (via _sim_state), não a lista fixa
            # de env var — pra single-robot isso é [""] (sem namespace), nunca
            # tb1/tb2 fantasma.
            _nav2_check_busy = threading.Lock()

            def nav2_check_cb():
                if not _nav2_check_busy.acquire(blocking=False):
                    return
                try:
                    with _sim_lock:
                        running = _sim_state["running"]
                        mode = _sim_state["mode"]
                        sim_robots = list(_sim_state.get("robots") or [])
                    if not running:
                        # Simulação subida fora do backend (Docker, run_all.sh):
                        # só dá pra ser single-robot sem namespace.
                        robots_to_check: list[str] = [""]
                    elif mode == "multi":
                        robots_to_check = sim_robots
                    else:
                        robots_to_check = [""]
                    ready_robots = [rid for rid in robots_to_check if _bt_navigator_is_active(rid)]
                    with _status_lock:
                        _fleet_status["nav2_ready"] = bool(ready_robots)
                        _fleet_status["nav2_ready_robots"] = ready_robots
                        _fleet_status["nav2_ready_robots_at"] = time.monotonic()
                finally:
                    _nav2_check_busy.release()

            # Grupo próprio: nav2_check_cb bloqueia ~2 s num subprocess. No grupo
            # padrão (mutuamente exclusivo) isso travava todos os outros callbacks
            # mesmo com MultiThreadedExecutor — /tf chegava em rajadas a cada 3 s,
            # o map→odom se perdia e a pose na tela ficava até 4 m atrasada.
            node.create_timer(
                3.0, nav2_check_cb,
                callback_group=rclpy.callback_groups.MutuallyExclusiveCallbackGroup(),
            )

            node.create_subscription(FleetStatus, "fleet/status", fleet_cb, 10)
            executor = rclpy.executors.MultiThreadedExecutor()
            executor.add_node(node)
            executor.spin()
            node.destroy_node()
            rclpy.shutdown()
        except Exception as e:
            print(f"[fleet_ui] ROS subscriber not started (source workspace?): {e}")

    t = threading.Thread(target=run_ros, daemon=True)
    t.start()
    yield


app = FastAPI(title="Fleet UI API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins(), allow_methods=["*"], allow_headers=["*"])


_EMPTY_POSE = {"x": 0.0, "y": 0.0, "yaw": 0.0, "valid": False}

# TF mais novo que isso → /amcl_pose (/pose) não sobrescreve a posição.
_TF_FRESH_S = 1.0
# Sem TF nem pose_topic por mais que isso (depois de o TF já ter funcionado)
# → posição marcada inválida: a localização parou (ex.: AMCL morreu) e a tela
# não deve continuar mostrando a última posição como se fosse atual.
_POSE_STALE_S = 2.0


def _pose_view(pose: dict, now: float) -> dict:
    view = dict(pose)
    if "tf_ok_at" in view:
        last = max(view["tf_ok_at"], view.get("pose_topic_at", 0.0))
        if now - last > _POSE_STALE_S:
            view["valid"] = False
            view["stale"] = True
    return view


def _default_robot_id() -> str:
    """modo single roda com robot_id="" (tópicos sem prefixo); multi usa
    _STATUS_ROBOT_ID (primeiro robô de FLEET_ROBOTS). Deriva de
    _fleet_status["robots"] (populado ao vivo via tópico /fleet/status) em
    vez de _sim_state["mode"]: _sim_state é só memória do processo do
    backend e zera se ele reiniciar, mesmo com a simulação (processo
    separado) continuando rodando — /fleet/status não tem esse problema."""
    robots = _fleet_status.get("robots") or []
    if len(robots) == 1:
        return robots[0].get("robot_id", "")
    return _STATUS_ROBOT_ID


def _status_payload() -> dict:
    # "pose" (singular) fica de compat com quem ainda não sabe que existe
    # mais de um robô; "poses" traz todos, é o que a UI multi-robô usa.
    # Cópias: chamado com _status_lock, mas o JSON é serializado depois que a
    # trava é liberada, enquanto as threads do ROS seguem alterando os dicts.
    now = time.time()
    poses = {rid: _pose_view(p, now) for rid, p in _robot_poses.items()}
    return {
        **_fleet_status,
        "pose": poses.get(_default_robot_id(), dict(_EMPTY_POSE)),
        "poses": poses,
        "tf_last_rx": {rid: dict(rx) for rid, rx in _robot_tf_last_rx.items()},
    }


@app.get("/api/status")
async def get_status():
    with _status_lock:
        return _status_payload()


@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        with _status_lock:
            payload = _status_payload()
        await websocket.send_text(json.dumps(payload))
        while True:
            await asyncio.sleep(0.25)
            with _status_lock:
                payload = _status_payload()
            await websocket.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in _ws_clients:
            _ws_clients.remove(websocket)


import uuid

_jobs: dict = {}   # job_id → {running, lines, result, error}
_job_procs: dict = {}  # job_id → Popen do experiment_repeatability (fora de _jobs: não vai no JSON)
_job_robots: dict = {}  # job_id → robot_id do orquestrador ("" = single-robot)

# Histórico persistente de execuções de /api/run_config — sobrevive a um
# restart do backend. O job em si (_jobs) é só memória e o JSON exportado
# por run_experiment_step é apagado logo depois de lido
# (ros_bridge.py::run_experiment_step); sem isso, todo resultado de record/
# replay (bag_metrics, run_label) desaparecia pra sempre ao reiniciar.
_RUNS_HISTORY_DIR = Path(ROS_WS) / "runs_history"


def _save_run_history(job_id: str, cfg_data: dict, job: dict) -> None:
    try:
        _RUNS_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "job_id": job_id,
            "timestamp": _now_iso(),
            "command": cfg_data.get("command"),
            "robot": cfg_data.get("robot"),
            "route": cfg_data.get("route"),
            "run_label": cfg_data.get("run_label"),
            "result": job.get("result"),
            "error": job.get("error"),
            "exit_code": job.get("exit_code"),
        }
        (_RUNS_HISTORY_DIR / f"{job_id}.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=2, default=str)
        )
    except Exception as exc:
        print(f"[fleet_ui] falha ao salvar run_history {job_id}: {exc}")


def _build_cmd(cfg: dict) -> list[str]:
    robot = cfg.get("robot", "")
    rid = "" if not robot or robot == "default" else robot
    with _status_lock:
        pose = _pose_view(_robot_poses.get(rid) or {}, time.time())
    if pose.get("valid"):
        cfg = {**cfg, "current_pose": [pose["x"], pose["y"]]}
    return _bridge.build_experiment_cmd(cfg)


@app.post("/api/run_config")
async def run_config(cfg: RunConfigRequest):
    cfg_data = _model_dump(cfg)
    job_id = str(uuid.uuid4())[:8]
    export_path = str(Path(ROS_WS) / f"_job_{job_id}.json")
    try:
        cmd = _build_cmd(cfg_data)
        cmd += ["--export", export_path]
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=400)

    _jobs[job_id] = {"running": True, "lines": [], "result": None, "error": None, "exit_code": None}
    robot = cfg_data.get("robot") or ""
    _job_robots[job_id] = "" if robot == "default" else robot

    def _run():
        job = _jobs[job_id]
        if cfg_data.get("ble_target_address"):
            ok, out = _bridge.run_param_set("/ble_rssi_publisher", "target_address", cfg_data["ble_target_address"])
            job["lines"].append(f"[ble_target_address] {'ok' if ok else 'falhou'}: {out}")
        job["lines"].append(f"[CMD] {' '.join(cmd)}")
        try:
            step = _bridge.run_experiment_step(
                cmd, export_path, line_callback=job["lines"].append,
                on_start=lambda p: _job_procs.__setitem__(job_id, p),
            )
            job["result"] = step["result"]
            job["error"] = step["error"]
            job["exit_code"] = step["exit_code"]
            if job["result"] is not None and cfg_data.get("run_label"):
                job["result"]["run_label"] = cfg_data["run_label"]
        except Exception as ex:
            job["error"] = str(ex)
        finally:
            _job_procs.pop(job_id, None)
            job["running"] = False
            _save_run_history(job_id, cfg_data, job)

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id}


@app.post("/api/job/{job_id}/stop")
def stop_job(job_id: str):
    """Para uma execução de verdade: encerra o experiment_repeatability (senão
    ele manda o próximo trecho, ex. na volta ao início), cancela a meta do Nav2
    (é isso que para o robô) e fecha a gravação que o script deixaria aberta.
    O botão antigo só parava de acompanhar a execução na tela."""
    job = _jobs.get(job_id)
    if job is None:
        return JSONResponse({"success": False, "message": f"job {job_id} não existe"}, status_code=404)
    robot_id = _job_robots.get(job_id, "")
    proc = _job_procs.get(job_id)
    if proc is not None and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    req = json.dumps({"robot_id": robot_id})
    cancel_ok, cancel_out = _run_ros2_service("cancel", "fleet_msgs/srv/Cancel", req)
    coll_ok, coll_out = _run_ros2_service("disable_collection", "fleet_msgs/srv/DisableCollection", req)
    job["lines"].append(f"[PARADO pelo usuário] cancelar navegação: {'ok' if cancel_ok else 'falhou'}; "
                        f"gravação: {'fechada' if coll_ok else 'não estava aberta ou falhou'}")
    return {"success": True, "cancel": cancel_ok, "collection_closed": coll_ok}


@app.get("/api/runs")
async def list_run_history(limit: int = 50):
    """Lista execuções passadas de /api/run_config (persistidas em disco por
    _save_run_history), mais recentes primeiro — sobrevive a um restart do
    backend. Cada entrada já vem com bag_metrics/run_label prontos pro
    frontend montar cards e comparar execuções lado a lado."""
    if not _RUNS_HISTORY_DIR.exists():
        return {"runs": []}
    files = sorted(_RUNS_HISTORY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    runs = []
    for f in files[:max(1, limit)]:
        try:
            runs.append(json.loads(f.read_text()))
        except Exception:
            continue
    return {"runs": runs}


@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return {
        "running": job["running"],
        "lines": job["lines"],
        "result": job["result"],
        "error": job["error"],
        "exit_code": job["exit_code"],
    }


_campaign_jobs: dict = {}  # run_id → {running, steps: [...], summary, analysis_log, error}


def _campaign_steps(cfg: dict) -> list[tuple[str, dict]]:
    """1 gravação baseline + N reproduções, na mesma convenção de labels
    (baseline, replay_01, ...) que analyze_runs.py/Analyst já esperam."""
    steps = [("baseline", {**cfg, "command": "record"})]
    for i in range(1, int(cfg.get("repetitions", 3)) + 1):
        steps.append((f"replay_{i:02d}", {**cfg, "command": "replay"}))
    return steps


def _run_campaign(run_id: str, cfg: dict) -> None:
    job = _campaign_jobs[run_id]
    bag_paths: list[str] = []
    labels: list[str] = []

    for label, step_cfg in _campaign_steps(cfg):
        step = {"label": label, "lines": [], "result": None, "error": None, "exit_code": None}
        job["steps"].append(step)
        try:
            cmd = _build_cmd(step_cfg)
        except Exception as e:
            step["error"] = str(e)
            job["error"] = f"{label}: {e}"
            job["running"] = False
            return
        export_path = str(Path(ROS_WS) / f"_campaign_{run_id}_{label}.json")
        cmd += ["--export", export_path]
        step["lines"].append(f"[CMD] {' '.join(cmd)}")
        outcome = _bridge.run_experiment_step(cmd, export_path, line_callback=step["lines"].append)
        step["result"] = outcome["result"]
        step["error"] = outcome["error"]
        step["exit_code"] = outcome["exit_code"]
        if outcome["error"] or outcome["exit_code"] not in (0, None):
            job["error"] = f"{label} falhou (exit={outcome['exit_code']}): {outcome['error'] or 'ver lines do passo'}"
            job["running"] = False
            return
        bag_path = (outcome["result"] or {}).get("rosbag_path")
        if not bag_path:
            job["error"] = f"{label}: rosbag_path ausente no export (coleta desligada nesse passo?)"
            job["running"] = False
            return
        bag_paths.append(bag_path)
        labels.append(label)

    out_dir = str(Path(ROS_WS) / "runs" / run_id / "analysis")
    ok, out = _bridge.analyze_bags(bag_paths, labels, out_dir)
    job["analysis_log"] = out
    if not ok:
        job["error"] = f"analyze_runs.py falhou: {out[-800:]}"
        job["running"] = False
        return

    summary_path = Path(out_dir) / "summary.json"
    if summary_path.exists():
        job["summary"] = json.loads(summary_path.read_text())
        job["run_id"] = run_id
    else:
        job["error"] = "analyze_runs.py terminou mas summary.json não foi encontrado"
    job["running"] = False


@app.post("/api/run_campaign")
async def run_campaign(cfg: RunCampaignRequest):
    """Fecha o loop planner→campanha→análise: grava 1 baseline + N reproduções
    da mesma rota, roda analyze_runs.py sobre os bags resultantes, e deixa o
    summary.json em fleet_ws/runs/<run_id>/analysis/ — o mesmo formato que
    Analyst.analyze_experiment/compare_runs já leem. Assíncrono como
    /api/run_config: devolve run_id, consulte com /api/campaign_job/{run_id}."""
    cfg_data = _model_dump(cfg)
    if cfg_data["repetitions"] < 1:
        return JSONResponse({"success": False, "message": "repetitions deve ser >= 1"}, status_code=400)
    run_id = cfg_data.get("run_id") or f"{cfg_data['route']}_{uuid.uuid4().hex[:8]}"
    if run_id in _campaign_jobs and _campaign_jobs[run_id]["running"]:
        return JSONResponse({"success": False, "message": f"Campanha '{run_id}' já em execução"}, status_code=409)

    _campaign_jobs[run_id] = {"running": True, "steps": [], "summary": None, "analysis_log": None, "error": None}
    threading.Thread(target=_run_campaign, args=(run_id, cfg_data), daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/campaign_job/{run_id}")
async def get_campaign_job(run_id: str):
    job = _campaign_jobs.get(run_id)
    if not job:
        return JSONResponse({"error": "campaign not found"}, status_code=404)
    return job


# ── Simulação (Terminais 1+2 do README, lançados pela UI) ──────────────────
#
# Recurso singleton (só 1 simulação por vez nesta v1) — diferente dos jobs
# acima, que rodam até terminar; aqui o processo fica de pé indefinidamente
# até /api/simulation/stop. `preexec_fn=os.setsid` é o que permite matar a
# árvore de processos inteira depois (gz sim + todos os nós do Nav2/SLAM) —
# sem isso, `pkill -f` sozinho deixou processos órfãos repetidas vezes ao
# testar isso manualmente nesta sessão.
_SIM_WORLDS = ["warehouse", "depot"]
_sim_state: dict = {
    "running": False, "ready": False, "mode": None, "world": None,
    "robots": [], "lines": [], "error": None, "started_at": None,
}
_sim_procs: list[tuple[str, subprocess.Popen]] = []
_sim_lock = threading.Lock()
_sim_nav_ready_count = 0
_sim_fleet_ready = False


# Robô real (make robot-up): sem /clock, relógio do sistema. Padrão: simulação.
FLEET_USE_SIM_TIME = os.environ.get("FLEET_USE_SIM_TIME", "true").strip().lower() not in ("false", "0", "no")


def _read_robot_roles() -> dict[str, str]:
    """robot_id -> papel (MUUT/FUUT/SU) declarado em roles.yaml. Fonte de
    verdade de quem existe e do que cada um pode fazer — só MUUT (Mobile
    Unit Under Tasking) aceita comandos de movimento; FUUT (sensor fixo) e
    SU (unidade de suporte/infra) não têm permissão de deslocamento."""
    path = Path(ROS_WS) / "src" / "fleet_orchestrator" / "config" / "roles.yaml"
    try:
        data = yaml.safe_load(path.read_text()) or {}
        return dict(data.get("roles") or {})
    except Exception:
        return {}


def _require_muut(robot_id: str) -> JSONResponse | None:
    """Bloqueia comando de movimento se o papel declarado em roles.yaml não
    for MUUT (inclui papel ausente ou desconhecido). Devolve None se o robô
    pode se mover, ou a JSONResponse 403 já pronta pra retornar."""
    # Sem namespace (single-robot, ou o TurtleBot4 real) é o próprio robô
    # móvel: mesma regra de FleetOrchestrator._role.
    role = "MUUT" if robot_id == "" else _read_robot_roles().get(robot_id)
    if role == "MUUT":
        return None
    reason = f"papel '{role}' não permite movimento" if role else "robot_id não declarado em roles.yaml"
    return JSONResponse({"success": False, "message": f"{robot_id}: {reason}"}, status_code=403)


def _read_configured_robots() -> list[str]:
    return list(_read_robot_roles().keys())


def _sim_append_line(tag: str, line: str) -> None:
    with _sim_lock:
        _sim_state["lines"].append(f"[{tag}] {line}")
        if len(_sim_state["lines"]) > 500:
            del _sim_state["lines"][: len(_sim_state["lines"]) - 500]


def _sim_reader_thread(tag: str, proc: subprocess.Popen, expected_nav_ready: int) -> None:
    global _sim_nav_ready_count, _sim_fleet_ready
    for raw in proc.stdout:
        line = raw.rstrip()
        if not line:
            continue
        _sim_append_line(tag, line)
        with _sim_lock:
            if "Managed nodes are active" in line:
                _sim_nav_ready_count += 1
            if "fleet_orchestrator ready" in line:
                _sim_fleet_ready = True
            if "Aborting bringup" in line or "Failed to bring up all requested nodes" in line:
                _sim_state["error"] = line
            if _sim_nav_ready_count >= expected_nav_ready and _sim_fleet_ready:
                _sim_state["ready"] = True


def _build_sim_commands(
    mode: str, world: str, robots: list[str], sequential_nav: bool = False,
) -> list[tuple[str, list[str], dict]]:
    """[(tag, cmd, extra_env), ...] — mesmos dois launches do README
    (Terminal 1 + Terminal 2), montados programaticamente."""
    env_extra: dict = {}
    if mode == "single":
        # nav2_minimal_tb4_sim usa PythonExpression (eval() de verdade) pra
        # decidir gzclient — precisa ser "True" com maiúscula (Python), não
        # "true": com minúscula dá `NameError: name 'true' is not defined`.
        # turtlebot4_multi_sim.launch.py não tem esse problema (usa outra
        # condição, tolerante a minúscula) — assimetria real do vendor, não
        # inconsistência nossa.
        sim_cmd = ["ros2", "launch", "fleet_orchestrator", "turtlebot4_sim.launch.py",
                   f"world:={world}", "headless:=True"]
        fleet_cmd = ["ros2", "launch", "fleet_orchestrator", "fleet.launch.py",
                     "single_robot_sim:=true"]
    else:
        env_extra["FLEET_ROBOTS"] = ",".join(robots)
        sim_cmd = ["ros2", "launch", "fleet_orchestrator", "turtlebot4_multi_sim.launch.py",
                   f"world:={world}", "headless:=true"]
        if sequential_nav:
            sim_cmd += ["bringup_nav:=false"]
        fleet_cmd = ["ros2", "launch", "fleet_orchestrator", "fleet.launch.py"]
    return [("sim", sim_cmd, env_extra), ("fleet", fleet_cmd, env_extra)]


def _start_simulation(mode: str, world: str, robots: list[str], sequential_nav: bool = False) -> None:
    global _sim_nav_ready_count, _sim_fleet_ready
    _sim_nav_ready_count = 0
    _sim_fleet_ready = False
    # Com sequential_nav, ninguém sobe Nav2 no bringup inicial — "pronto"
    # significa só "Gazebo + robôs spawnados + fleet_orchestrator no ar",
    # a navegação de cada um liga depois via activate_robot.
    expected_nav_ready = 0 if sequential_nav else (len(robots) if mode == "multi" else 1)
    for tag, cmd, env_extra in _build_sim_commands(mode, world, robots, sequential_nav):
        env = {**_bridge.ros_env(), "PYTHONUNBUFFERED": "1", **env_extra}
        shell_cmd = _bridge.ros_setup_prefix() + " ".join(shlex.quote(c) for c in cmd)
        proc = subprocess.Popen(
            ["bash", "-c", shell_cmd],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=ROS_WS, env=env,
            preexec_fn=os.setsid,
        )
        _sim_procs.append((tag, proc))
        threading.Thread(
            target=_sim_reader_thread, args=(tag, proc, expected_nav_ready), daemon=True,
        ).start()


# Padrões de processo da simulação — usados como rede de segurança no stop.
# Achado ao vivo: quando um robô aborta o bringup do Nav2 no meio do
# caminho (lifecycle_manager falhando), a árvore de processos do
# `ros2 launch` fica num estado irregular e alguns nós (ex.: route_server,
# waypoint_follower de outro robô que tinha subido bem) sobrevivem ao
# killpg do processo-grupo principal — supõe-se que ficam num
# processo-grupo próprio nesse cenário. killpg continua sendo a via
# principal (mais rápida, mais limpa); isto aqui só garante que nada some.
_SIM_PROCESS_PATTERNS = [
    "gz sim -r -s", "nav2_", "slam_toolbox", "fleet_orchestrator",
    "sensor_collector", "ros_gz_bridge/parameter_bridge", "robot_state_publisher",
]


def _stop_simulation() -> None:
    started_here = bool(_sim_procs)
    with _robot_nav_lock:
        active_robot_ids = list(_robot_nav_procs.keys())
    for rid in active_robot_ids:
        _deactivate_robot_nav(rid)

    for _tag, proc in _sim_procs:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            continue
    time.sleep(3)
    for _tag, proc in _sim_procs:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
    _sim_procs.clear()

    # Rede de segurança: mata por padrão de nome qualquer coisa que o
    # killpg não tenha alcançado (ver comentário acima). Só quando foi este
    # backend que subiu a simulação: senão derrubaria um stack de fora
    # (run_all.sh) ou outro processo da máquina com nome parecido.
    if started_here:
        for pattern in _SIM_PROCESS_PATTERNS:
            subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)

    with _sim_lock:
        _sim_state.update({
            "running": False, "ready": False, "mode": None, "world": None,
            "robots": [], "lines": [], "error": None, "started_at": None,
        })


@app.get("/api/simulation/options")
async def simulation_options():
    roles = _read_robot_roles()
    return {"worlds": _SIM_WORLDS, "robots": list(roles.keys()), "roles": roles}


@app.get("/api/simulation/status")
async def simulation_status():
    with _sim_lock:
        state = dict(_sim_state)
    # Cross-check contra o estado real do ROS (nav2_check_cb + fleet_cb, já
    # rodando independente disso) em vez de confiar só no scraping de log de
    # _sim_reader_thread — visto ao vivo ficando preso em ready=False com a
    # simulação genuinamente pronta (tb1+tb2 navegando, nav2_ready global
    # true). Não substitui o parsing de log (continua útil pra "error"), só
    # dá um segundo caminho pra "ready" virar true quando o estado real bate.
    #
    # Bug real achado ao vivo (2026-09-25): nav2_ready_robots/robots são
    # escritos por timers/subscrições de longa duração que nunca são
    # resetados entre sessões de simulação — se uma sessão anterior tinha
    # deixado tb1+tb2 nav2_ready antes de ser parada, esse cross-check
    # reportava "ready": true pra uma sessão NOVA em t=+0s, antes de
    # qualquer processo da simulação atual sequer ter subido (confirmado
    # cronometrando: ready=True no primeiro poll, instantaneamente após o
    # POST /api/simulation/start). Um agente/painel que dispara comandos de
    # navegação assim que vê "ready" acaba mandando o robô pra dentro de
    # uma simulação que ainda nem começou a existir. Corrigido exigindo que
    # os dois sinais tenham sido atualizados DEPOIS do início desta sessão
    # (started_at) — dado stale de uma sessão anterior não conta mais.
    if state["running"] and not state["ready"] and state.get("started_at") is not None:
        expected = set(state.get("robots") or [])
        started_at = state["started_at"]
        with _status_lock:
            nav_robots = set(_fleet_status.get("nav2_ready_robots", []))
            nav_fresh = _fleet_status.get("nav2_ready_robots_at", 0) > started_at
            fleet_robots = {r["robot_id"] for r in _fleet_status.get("robots", [])}
            fleet_fresh = _fleet_status.get("robots_at", 0) > started_at
        if expected and nav_fresh and fleet_fresh and expected.issubset(nav_robots) and expected.issubset(fleet_robots):
            with _sim_lock:
                _sim_state["ready"] = True
            state["ready"] = True
    return state


@app.post("/api/simulation/start")
async def simulation_start(cfg: StartSimulationRequest):
    with _sim_lock:
        if _sim_state["running"]:
            return JSONResponse(
                {"success": False, "message": "Já existe uma simulação rodando — pare antes de iniciar outra."},
                status_code=409,
            )
        robots = cfg.robots if cfg.mode == "multi" else []
        _sim_state.update({
            "running": True, "ready": False, "mode": cfg.mode, "world": cfg.world,
            "robots": robots, "lines": [], "error": None, "started_at": time.monotonic(),
        })
    _start_simulation(cfg.mode, cfg.world, robots, cfg.sequential_nav)
    return {"success": True}


@app.post("/api/simulation/stop")
def simulation_stop():  # def, não async: _stop_simulation dorme vários segundos
    _stop_simulation()
    return {"success": True}


# Navegação por robô, ligada/desligada sob demanda (modo sequential_nav) —
# processos à parte de _sim_procs (que é só Gazebo+fleet_orchestrator).
_robot_nav_procs: dict[str, subprocess.Popen] = {}
_robot_nav_lock = threading.Lock()


# Achado ao vivo (2026-09-27/30): ativar o robô seguinte logo depois de
# desligar o anterior faz a rajada de ~15-18 nós novos do Nav2+SLAM disputar
# recursos com o que quer que o SO/DDS ainda esteja limpando da ativação
# anterior — mesmo com os processos 100% mortos (confirmado via pgrep). Sem
# pausa: 484 avisos de "jump back in time", nunca fica pronto (75s+, timeout).
# Com 15s de pausa depois de matar o processo anterior: 9 avisos (menos que
# a primeira ativação da sessão), pronto em ~6s, navegação funcionando de
# verdade (confirmado pelo log do próprio Nav2: "Reached the goal!").
_ROBOT_NAV_SETTLE_SECONDS = 15


def _deactivate_robot_nav(robot_id: str) -> None:
    with _robot_nav_lock:
        proc = _robot_nav_procs.pop(robot_id, None)
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(2)
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(_ROBOT_NAV_SETTLE_SECONDS)


@app.post("/api/simulation/activate_robot")
async def activate_robot(robot_id: str):
    with _sim_lock:
        running = _sim_state["running"]
        sim_robots = list(_sim_state.get("robots") or [])
    if not running:
        return JSONResponse({"success": False, "message": "Nenhuma simulação rodando."}, status_code=409)
    if robot_id not in sim_robots:
        return JSONResponse(
            {"success": False, "message": f"'{robot_id}' não faz parte desta simulação ({sim_robots})."},
            status_code=400,
        )
    # Checagem e spawn sob a mesma trava: duas ativações simultâneas (clique
    # duplo, UI + agente) subiriam duas pilhas Nav2 e a primeira ficaria órfã.
    with _robot_nav_lock:
        if robot_id in _robot_nav_procs and _robot_nav_procs[robot_id].poll() is None:
            return {"success": True, "message": f"Navegação de '{robot_id}' já estava ativa."}

        _reset_robot_pose_tracking(robot_id)
        cmd = ["ros2", "launch", "fleet_orchestrator", "activate_robot_nav.launch.py", f"namespace:={robot_id}"]
        env = {**_bridge.ros_env(), "PYTHONUNBUFFERED": "1"}
        shell_cmd = _bridge.ros_setup_prefix() + " ".join(shlex.quote(c) for c in cmd)
        proc = subprocess.Popen(
            ["bash", "-c", shell_cmd],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=ROS_WS, env=env,
            preexec_fn=os.setsid,
        )
        _robot_nav_procs[robot_id] = proc
    tag = f"nav-{robot_id}"
    threading.Thread(
        target=lambda: [_sim_append_line(tag, line.rstrip()) for line in proc.stdout if line.rstrip()],
        daemon=True,
    ).start()
    return {"success": True}


@app.post("/api/simulation/deactivate_robot")
def deactivate_robot(robot_id: str):  # def, não async: dorme ~17 s
    _deactivate_robot_nav(robot_id)
    return {"success": True}


@app.post("/api/save_route_waypoints")
async def save_route_waypoints(body: SaveRouteWaypointsRequest):
    """Salva lista de waypoints diretamente como yaml (sem precisar do record flow)."""
    import yaml
    data_in = _model_dump(body)
    robot_id = data_in.get("robot_id", "") or ""
    route_name = (data_in.get("route_name") or "").strip()
    waypoints = data_in.get("waypoints", [])
    if not route_name:
        return JSONResponse(content={"success": False, "message": "route_name vazio"}, status_code=400)
    if not waypoints:
        return JSONResponse(content={"success": False, "message": "waypoints vazio"}, status_code=400)
    folder = "default" if not robot_id else robot_id
    routes_dir = Path(ROS_WS) / "routes" / folder
    routes_dir.mkdir(parents=True, exist_ok=True)
    path = routes_dir / f"{route_name}.yaml"
    data = {
        "route_name": route_name,
        "frame": "map",
        "poses": [{"x": float(w.get("x", 0)), "y": float(w.get("y", 0)), "yaw": float(w.get("yaw", 0))} for w in waypoints],
    }
    path.write_text(yaml.dump(data, default_flow_style=False))
    return {"success": True, "message": f"Salvo {len(waypoints)} waypoints em {path}"}


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-]+$")


@app.get("/api/route_poses")
async def route_poses(name: str, robot_id: str = ""):
    """Poses (x, y, yaw) de uma rota salva, pro frontend desenhar o percurso antes do replay."""
    if not _SAFE_NAME.match(name) or (robot_id and not _SAFE_NAME.match(robot_id)):
        return JSONResponse(content={"poses": [], "message": "nome inválido"}, status_code=400)
    path = Path(ROS_WS) / "routes" / (robot_id or "default") / f"{name}.yaml"
    if not path.exists():
        return {"poses": []}
    data = yaml.safe_load(path.read_text()) or {}
    poses = [
        [float(p.get("x", 0)), float(p.get("y", 0)), float(p.get("yaw", 0))]
        for p in data.get("poses") or []
    ]
    return {"poses": poses}


@app.get("/api/map")
async def get_map(robot_id: str = ""):
    rid = robot_id or _default_robot_id()
    with _status_lock:
        meta = _map_metas.get(rid)
        if not meta:
            return JSONResponse(content={"available": False})
        return {"available": True, "robot_id": rid, **meta}


@app.post("/api/save_background_map")
async def save_background_map(robot_id: str = ""):
    """Guarda o mapa SLAM actual como fundo persistente em public/slam_map.png + slam_map.json."""
    import base64 as _b64
    rid = robot_id or _default_robot_id()
    with _status_lock:
        meta = _map_metas.get(rid)
        if not meta or not meta.get("png_b64"):
            return JSONResponse({"success": False, "message": "Mapa SLAM não disponível ainda."}, status_code=400)
        meta = dict(meta)

    public_dir = Path(WORKSPACE) / "frontend" / "public"
    public_dir.mkdir(parents=True, exist_ok=True)

    png_bytes = _b64.b64decode(meta["png_b64"])
    (public_dir / "slam_map.png").write_bytes(png_bytes)

    import json as _json
    slam_meta = {k: v for k, v in meta.items() if k != "png_b64"}
    (public_dir / "slam_map.json").write_text(_json.dumps(slam_meta))

    return {"success": True, "message": f"Mapa guardado ({meta['width']}×{meta['height']} px, res={meta['resolution']:.3f} m/px)"}


def _map_prefix(name: str) -> str:
    return "slam_map" if (not name or name == "slam") else f"{name}_map"


@app.get("/api/slam_map_meta")
async def get_slam_map_meta(name: str = "slam"):
    """Devolve metadados do mapa de fundo guardado (slam_map.json por
    default, ou <name>_map.json pra um mapa importado via /api/import_map)."""
    meta_path = Path(WORKSPACE) / "frontend" / "public" / f"{_map_prefix(name)}.json"
    if not meta_path.exists():
        return JSONResponse({"available": False})
    import json as _json
    return {"available": True, **_json.loads(meta_path.read_text())}


@app.get("/api/list_maps")
async def list_maps():
    """Lista os mapas de fundo disponíveis (nomes, sem extensão) — 'slam'
    (se já foi salvo um SLAM ao vivo) + qualquer mapa importado via
    /api/import_map."""
    public_dir = Path(WORKSPACE) / "frontend" / "public"
    names = []
    if (public_dir / "slam_map.json").exists():
        names.append("slam")
    for p in sorted(public_dir.glob("*_map.json")):
        stem = p.stem[: -len("_map")]
        if stem and stem not in names:  # slam_map.json também casa com *_map.json
            names.append(stem)
    return {"maps": names}


class ImportMapRequest(BaseModel):
    name: str
    yaml_path: str


@app.post("/api/import_map")
async def import_map(req: ImportMapRequest):
    """Importa um mapa real já pronto (par .yaml+.pgm, convenção do
    map_server do Nav2 — ex.: o hall_cin_v4 do CIn) como fundo
    selecionável no MapView, sem precisar rodar SLAM nesse ambiente."""
    name = req.name.strip()
    if not name or not all(c.isalnum() or c in "_-" for c in name):
        return JSONResponse({"success": False, "message": "Nome inválido (use letras/números/_/-)."}, status_code=400)

    yaml_path = Path(req.yaml_path).expanduser()
    if not yaml_path.exists():
        return JSONResponse({"success": False, "message": f"YAML não encontrado: {yaml_path}"}, status_code=400)

    try:
        map_meta = yaml.safe_load(yaml_path.read_text())
        pgm_path = (yaml_path.parent / map_meta["image"]).resolve()
        if not pgm_path.exists():
            return JSONResponse({"success": False, "message": f"PGM não encontrado: {pgm_path}"}, status_code=400)

        resolution = float(map_meta["resolution"])
        origin = map_meta.get("origin", [0.0, 0.0, 0.0])
        negate = bool(map_meta.get("negate", 0))
        occupied_thresh = float(map_meta.get("occupied_thresh", 0.65))
        free_thresh = float(map_meta.get("free_thresh", 0.25))

        width, height, _maxval, pixels = _read_pgm(pgm_path)
        png_bytes = _pgm_to_occupancy_png(width, height, pixels, negate, occupied_thresh, free_thresh)
    except Exception as exc:
        return JSONResponse({"success": False, "message": f"Falha ao importar: {exc}"}, status_code=400)

    public_dir = Path(WORKSPACE) / "frontend" / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    prefix = _map_prefix(name)
    (public_dir / f"{prefix}.png").write_bytes(png_bytes)
    (public_dir / f"{prefix}.json").write_text(json.dumps({
        "resolution": resolution,
        "origin_x": float(origin[0]),
        "origin_y": float(origin[1]),
        "width": width,
        "height": height,
    }))

    return {"success": True, "message": f"Mapa '{name}' importado ({width}×{height} px, res={resolution:.3f} m/px)"}


@app.post("/api/start_record")
def start_record(robot_id: str = "", route_name: str = "r1"):
    robot_id = robot_id or ""
    if (err := _require_muut(robot_id)) is not None:
        return err
    ok, out = _run_ros2_service(
        "start_record", "fleet_msgs/srv/StartRecord",
        json.dumps({"robot_id": robot_id, "route_name": route_name}),
    )
    return {"success": ok, "message": out}


@app.post("/api/stop_record")
def stop_record(robot_id: str = ""):
    robot_id = robot_id or ""
    if (err := _require_muut(robot_id)) is not None:
        return err
    ok, out = _run_ros2_service(
        "stop_record", "fleet_msgs/srv/StopRecord",
        json.dumps({"robot_id": robot_id}),
    )
    return {"success": ok, "message": out}


@app.post("/api/play_route")
def play_route(robot_id: str = "", route_name: str = "r1"):
    robot_id = robot_id or ""
    if (err := _require_muut(robot_id)) is not None:
        return err
    ok, out = _run_ros2_service(
        "play_route", "fleet_msgs/srv/PlayRoute",
        json.dumps({"robot_id": robot_id, "route_name": route_name}),
    )
    return {"success": ok, "message": out}


@app.post("/api/go_to_point")
def go_to_point(robot_id: str = "", x: float = 0.0, y: float = 0.0, yaw: float = 0.0):
    robot_id = robot_id or ""
    if (err := _require_muut(robot_id)) is not None:
        return err
    ok, out = _run_ros2_service(
        "go_to_point", "fleet_msgs/srv/GoToPoint",
        json.dumps({"robot_id": robot_id, "x": x, "y": y, "yaw": yaw}),
    )
    return {"success": ok, "message": out}


@app.post("/api/cancel")
def cancel(robot_id: str = ""):
    robot_id = robot_id or ""
    ok, out = _run_ros2_service(
        "cancel", "fleet_msgs/srv/Cancel",
        json.dumps({"robot_id": robot_id}),
    )
    return {"success": ok, "message": out}


@app.get("/api/list_robots")
def list_robots():
    ok, out = _run_ros2_service("list_robots", "fleet_msgs/srv/ListRobots", "{}")
    if not ok:
        return JSONResponse(content={"robot_ids": []}, status_code=200)
    return {"robot_ids": _bridge.extract_list_field(out, "robot_ids")}


@app.get("/api/list_routes")
def list_routes(robot_id: str = ""):
    robot_id = robot_id or ""
    ok, out = _run_ros2_service(
        "list_routes", "fleet_msgs/srv/ListRoutes",
        json.dumps({"robot_id": robot_id}),
    )
    if not ok:
        return {"route_names": []}
    return {"route_names": _bridge.extract_list_field(out, "route_names")}


@app.post("/api/enable_collection")
def enable_collection(robot_id: str = "", topics: str = "scan,odom", output_mode: str = "rosbag2"):
    robot_id = robot_id or ""
    topic_list = [t.strip() for t in topics.split(",") if t.strip()] or ["scan", "odom"]
    ok, out = _run_ros2_service(
        "enable_collection", "fleet_msgs/srv/EnableCollection",
        json.dumps({"robot_id": robot_id, "topics": topic_list, "output_mode": output_mode}),
    )
    return {"success": ok, "message": out}


@app.post("/api/disable_collection")
def disable_collection(robot_id: str = ""):
    robot_id = robot_id or ""
    ok, out = _run_ros2_service(
        "disable_collection", "fleet_msgs/srv/DisableCollection",
        json.dumps({"robot_id": robot_id}),
    )
    return {"success": ok, "message": out}


@app.get("/api/discover_robots")
def discover_robots(subnet: str = ""):
    """
    Varre a subnet por hosts com porta 22 aberta e testa se têm ROS 2.
    subnet ex: '192.168.1' (varre .1–.254).
    Se omitido, detecta automaticamente a subnet local.
    """
    return _bridge.discover_robots(subnet)


@app.post("/api/test_ssh")
def test_ssh(body: SshTestRequest):
    """Testa SSH num host: verifica conexão e presença do ROS 2."""
    data = _model_dump(body)
    host = (data.get("host") or "").strip()
    user = (data.get("user") or "ubuntu").strip()
    port = int(data.get("port") or 22)
    if not host:
        return JSONResponse({"success": False, "message": "host vazio"}, status_code=400)
    return _bridge.test_ssh(host=host, user=user, port=port)


_agent_jobs: dict = {}  # job_id → {running, steps, final_text, error}
_fleet_jobs: dict = {}  # job_id → {running, robots: {robot_id → {running, steps, final_text, error}}}
_AGENT_RUNS_DIR = Path(ROS_WS) / "agent_runs"  # persistência em disco — ver _save_agent_run


def _agent_base_url() -> str:
    """URL pela qual o Executor do agente chama de volta esta própria API."""
    return os.environ.get("FLEET_UI_BASE_URL", "http://127.0.0.1:8000")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_agent_run(file_stem: str, data: dict) -> None:
    """Persiste um job de agente (single ou fleet) já concluído em disco, para
    sobreviver a um restart do backend — _agent_jobs/_fleet_jobs são só memória.
    Best-effort: uma falha ao salvar não deve derrubar o job em si."""
    try:
        _AGENT_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (_AGENT_RUNS_DIR / f"{file_stem}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str)
        )
    except Exception as exc:
        print(f"[fleet_ui] falha ao salvar agent_run {file_stem}: {exc}")


def _load_agent_run(file_stem: str) -> dict | None:
    path = _AGENT_RUNS_DIR / f"{file_stem}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


async def _execute_planner(state: dict, instruction: str, model: str, robot_id: str | None = None) -> None:
    """Roda um Planner até concluir, escrevendo o resultado em `state` (dict de job).
    `robot_id`, se informado, restringe o Planner a um único robô (ver Planner.robot_id)."""
    executor = Executor(base_url=_agent_base_url())
    try:
        planner = Planner(executor, Analyst(), model=model, robot_id=robot_id)
        result = await planner.run(instruction)
        state["steps"] = [
            {"tool_name": s.tool_name, "tool_input": s.tool_input, "result": s.result}
            for s in result.steps
        ]
        state["final_text"] = result.final_text
    except Exception as exc:
        state["error"] = str(exc)
    finally:
        state["running"] = False
        await executor.aclose()


@app.post("/api/agent/run")
async def agent_run(body: AgentRunRequest):
    """Dispara o Planner de IA numa instrução em linguagem natural.
    Assíncrono como /api/run_config: devolve job_id, consulte com /api/agent/job/{id}."""
    instruction = (body.instruction or "").strip()
    if not instruction:
        return JSONResponse({"success": False, "message": "instruction vazia"}, status_code=400)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return JSONResponse({"success": False, "message": "ANTHROPIC_API_KEY não configurada"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    _agent_jobs[job_id] = {
        "running": True, "steps": [], "final_text": None, "error": None,
        "instruction": instruction, "model": body.model, "started_at": _now_iso(), "finished_at": None,
    }

    async def _run_and_persist():
        await _execute_planner(_agent_jobs[job_id], instruction, body.model)
        _agent_jobs[job_id]["finished_at"] = _now_iso()
        _save_agent_run(f"single_{job_id}", {"kind": "single", "job_id": job_id, **_agent_jobs[job_id]})

    asyncio.create_task(_run_and_persist())
    return {"job_id": job_id}


@app.get("/api/agent/job/{job_id}")
async def agent_job(job_id: str):
    job = _agent_jobs.get(job_id) or _load_agent_run(f"single_{job_id}") or _load_agent_run(f"mission_{job_id}")
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return job


@app.post("/api/agent/run_fleet")
async def agent_run_fleet(body: AgentFleetRunRequest):
    """Dispara um Planner independente por robô, cada um restrito ao seu próprio
    robot_id, rodando em paralelo. `instructions` mapeia robot_id → instrução.
    Consulte com /api/agent/fleet_job/{id}."""
    instructions = {rid: instr.strip() for rid, instr in body.instructions.items() if instr and instr.strip()}
    if not instructions:
        return JSONResponse({"success": False, "message": "instructions vazio"}, status_code=400)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return JSONResponse({"success": False, "message": "ANTHROPIC_API_KEY não configurada"}, status_code=400)

    job_id = str(uuid.uuid4())[:8]
    robots_state = {
        rid: {"running": True, "steps": [], "final_text": None, "error": None, "instruction": instr}
        for rid, instr in instructions.items()
    }
    _fleet_jobs[job_id] = {
        "running": True, "robots": robots_state, "model": body.model,
        "started_at": _now_iso(), "finished_at": None,
    }

    async def _run_all():
        await asyncio.gather(*(
            _execute_planner(robots_state[rid], instr, body.model, robot_id=rid)
            for rid, instr in instructions.items()
        ))
        _fleet_jobs[job_id]["running"] = False
        _fleet_jobs[job_id]["finished_at"] = _now_iso()
        _save_agent_run(f"fleet_{job_id}", {"kind": "fleet", "job_id": job_id, **_fleet_jobs[job_id]})

    asyncio.create_task(_run_all())
    return {"job_id": job_id}


@app.get("/api/agent/fleet_job/{job_id}")
async def agent_fleet_job(job_id: str):
    job = _fleet_jobs.get(job_id) or _load_agent_run(f"fleet_{job_id}") or _load_agent_run(f"mission_fleet_{job_id}")
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return job


@app.post("/api/agent/run_mission")
async def agent_run_mission(body: AgentMissionRequest):
    """Piloto do 'Planner supervisor' do trabalho futuro (Cap. 9): recebe UMA
    instrução de missão, sem robot_id, decide via MissionRouter (TypeSafe)
    qual robô deve executá-la a partir do estado ao vivo da frota, e só
    então dispara o Planner de /api/agent/run pra esse robô. Escopo piloto:
    aloca 1 robô por missão, não divide em sub-tarefas multi-robô."""
    mission = (body.mission or "").strip()
    if not mission:
        return JSONResponse({"success": False, "message": "mission vazia"}, status_code=400)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return JSONResponse({"success": False, "message": "ANTHROPIC_API_KEY não configurada"}, status_code=400)
    if not os.environ.get("TYPESAFE_API_KEY"):
        return JSONResponse({"success": False, "message": "TYPESAFE_API_KEY não configurada"}, status_code=400)

    with _status_lock:
        known_robots = {r["robot_id"]: r for r in (_fleet_status.get("robots") or [])}
        poses = dict(_robot_poses)
    candidate_ids = body.candidates or list(known_robots.keys())
    candidates = [
        RobotCandidate(
            robot_id=rid,
            role=known_robots.get(rid, {}).get("role", "?"),
            nav_state=known_robots.get(rid, {}).get("nav_state", "?"),
            pose=poses.get(rid),
        )
        for rid in candidate_ids if rid in known_robots
    ]
    if not candidates:
        return JSONResponse(
            {"success": False, "message": "Nenhum robô candidato conhecido em _fleet_status."},
            status_code=409,
        )

    try:
        decision = await asyncio.to_thread(MissionRouter().route, mission, candidates)
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Falha no roteamento: {e}"}, status_code=502)

    job_id = str(uuid.uuid4())[:8]
    _agent_jobs[job_id] = {
        "running": True, "steps": [], "final_text": None, "error": None,
        "instruction": mission, "model": body.model, "started_at": _now_iso(), "finished_at": None,
        "routing": {
            "robot_id": decision.robot_id, "confidence": decision.confidence,
            "probabilities": decision.probabilities, "model": decision.model,
        },
    }

    async def _run_and_persist():
        await _execute_planner(_agent_jobs[job_id], mission, body.model, robot_id=decision.robot_id)
        _agent_jobs[job_id]["finished_at"] = _now_iso()
        _save_agent_run(f"mission_{job_id}", {"kind": "mission", "job_id": job_id, **_agent_jobs[job_id]})

    asyncio.create_task(_run_and_persist())
    return {"job_id": job_id, "routed_to": decision.robot_id, "confidence": decision.confidence}


@app.post("/api/agent/run_mission_fleet")
async def agent_run_mission_fleet(body: AgentMissionRequest):
    """Item 'mais ambicioso' do trabalho futuro (Cap. 9): recebe UMA missão,
    quebra em até N sub-tarefas (Claude) e roteia cada uma pro robô
    disponível mais adequado (TypeSafe/MissionRouter, um por sub-tarefa,
    sem repetir robô) — depois dispara um Planner independente por robô
    alocado, em paralelo, mesmo padrão de /api/agent/run_fleet. Ainda é
    decomposição + roteamento, não a negociação real entre agentes que o
    CLiMRS propõe (Cap. 9 já registra essa distinção)."""
    mission = (body.mission or "").strip()
    if not mission:
        return JSONResponse({"success": False, "message": "mission vazia"}, status_code=400)
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return JSONResponse({"success": False, "message": "ANTHROPIC_API_KEY não configurada"}, status_code=400)
    if not os.environ.get("TYPESAFE_API_KEY"):
        return JSONResponse({"success": False, "message": "TYPESAFE_API_KEY não configurada"}, status_code=400)

    with _status_lock:
        known_robots = {r["robot_id"]: r for r in (_fleet_status.get("robots") or [])}
        poses = dict(_robot_poses)
    candidate_ids = body.candidates or list(known_robots.keys())
    candidates = [
        RobotCandidate(
            robot_id=rid,
            role=known_robots.get(rid, {}).get("role", "?"),
            nav_state=known_robots.get(rid, {}).get("nav_state", "?"),
            pose=poses.get(rid),
        )
        for rid in candidate_ids if rid in known_robots
    ]
    if not candidates:
        return JSONResponse(
            {"success": False, "message": "Nenhum robô candidato conhecido em _fleet_status."},
            status_code=409,
        )

    try:
        allocation = await asyncio.to_thread(decompose_and_route, mission, candidates)
    except Exception as e:
        return JSONResponse({"success": False, "message": f"Falha na decomposição/roteamento: {e}"}, status_code=502)

    job_id = str(uuid.uuid4())[:8]
    robots_state = {
        rid: {"running": True, "steps": [], "final_text": None, "error": None, "instruction": instr}
        for rid, instr in allocation.items()
    }
    _fleet_jobs[job_id] = {
        "running": True, "robots": robots_state, "model": body.model,
        "started_at": _now_iso(), "finished_at": None, "mission": mission,
    }

    async def _run_all():
        await asyncio.gather(*(
            _execute_planner(robots_state[rid], instr, body.model, robot_id=rid)
            for rid, instr in allocation.items()
        ))
        _fleet_jobs[job_id]["running"] = False
        _fleet_jobs[job_id]["finished_at"] = _now_iso()
        _save_agent_run(f"mission_fleet_{job_id}", {"kind": "mission_fleet", "job_id": job_id, **_fleet_jobs[job_id]})

    asyncio.create_task(_run_all())
    return {"job_id": job_id, "allocation": allocation}


def _summarize_agent_run(data: dict) -> dict:
    base = {
        "kind": data.get("kind"),
        "job_id": data.get("job_id"),
        "model": data.get("model"),
        "started_at": data.get("started_at"),
        "finished_at": data.get("finished_at"),
    }
    if data.get("kind") in ("fleet", "mission_fleet"):
        base["robots"] = {
            rid: {"instruction": r.get("instruction"), "final_text": r.get("final_text"), "error": r.get("error")}
            for rid, r in (data.get("robots") or {}).items()
        }
    else:
        base["instruction"] = data.get("instruction")
        base["final_text"] = data.get("final_text")
        base["error"] = data.get("error")
    return base


@app.get("/api/agent/history")
async def agent_history(limit: int = 50):
    """Lista execuções passadas de agentes (persistidas em disco por _save_agent_run),
    mais recentes primeiro — sobrevive a um restart do backend."""
    if not _AGENT_RUNS_DIR.exists():
        return {"runs": []}
    files = sorted(_AGENT_RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    runs = []
    for f in files[:max(1, limit)]:
        try:
            runs.append(_summarize_agent_run(json.loads(f.read_text())))
        except Exception:
            continue
    return {"runs": runs}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
