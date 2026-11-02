"""Ligação com o TurtleBot4 real pela tela (modo robô, `make robot-up`).

O `make robot-up` sobe só o backend e a tela, já no domínio e middleware do
robô. O painel "Robô real" manda o IP, e o backend faz o que antes era do
terminal: confere se o IP responde, roda a checagem pré-voo
(robot_preflight.py) e, sem FALHA, sobe mapa + AMCL + Nav2
(turtlebot4_real.launch.py) e o orquestrador (fleet.launch.py) como processos
seus, como já faz com a simulação. Reconectar é desligar tudo e refazer.

O IP serve para a checagem de rede e para o comando do relógio (ssh); o ROS
continua achando o robô sozinho pelo DDS, como no `make robot-check`.
"""
from __future__ import annotations

import ipaddress
import os
import re
import shlex
import signal
import socket
import subprocess
import threading
import time
from typing import Callable, Optional

# Linha do relatório do robot_preflight.py: "  [OK   ] nome  detalhe".
_PREFLIGHT_LINE = re.compile(r"^\s*\[(OK|AVISO|FALHA)\s*\]\s+(.+?)\s{2,}(.*)$")
_PREFLIGHT_STATUS = {"OK": "ok", "AVISO": "warn", "FALHA": "fail"}

# Nós que o próprio backend cria: não contam como "robô descoberto".
BACKEND_NODES = ("fleet_ui_bridge",)

# Padrões dos processos que esta ligação sobe: rede de segurança no
# desligamento, para o que o killpg não alcançar (mesmo motivo de
# _SIM_PROCESS_PATTERNS em main.py).
_PROCESS_PATTERNS = (
    "turtlebot4_real.launch.py", "fleet.launch.py", "nav2_", "amcl", "map_server",
    "lifecycle_manager", "fleet_orchestrator", "sensor_collector",
)

PREFLIGHT_TIMEOUT_S = 60
REACH_TIMEOUT_S = 2.0
MAX_LINES = 300


def validate_ip(ip: str) -> str:
    """IP do robô, sem espaços. ValueError se não for um IPv4/IPv6 válido."""
    ip = (ip or "").strip()
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        raise ValueError(f"IP inválido: '{ip}' (ex.: 192.168.50.11)") from None


def check_reachable(ip: str, port: int = 22, timeout: float = REACH_TIMEOUT_S) -> tuple[bool, str]:
    """O IP responde na rede? Abre TCP na porta do ssh: aceitar ou recusar
    (RST) prova que o robô está lá; só o silêncio indica rede errada. Não usa
    ping porque o contêiner não tem permissão para ICMP."""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True, f"{ip} responde na rede"
    except ConnectionRefusedError:
        return True, f"{ip} responde na rede"
    except socket.timeout:
        return False, (f"{ip} não respondeu em {timeout:.0f} s: confira se o PC está na mesma "
                       "rede Wi-Fi do robô e se o IP é o do robô (não o do roteador)")
    except OSError as exc:
        return False, f"{ip} inacessível ({exc.strerror or exc}): confira a rede e o IP"


def parse_preflight(output: str) -> list[dict]:
    """Linhas OK/AVISO/FALHA do robot_preflight.py como lista de dicts."""
    checks = []
    for line in output.splitlines():
        m = _PREFLIGHT_LINE.match(line)
        if m:
            checks.append({
                "status": _PREFLIGHT_STATUS[m.group(1)],
                "name": m.group(2).strip(),
                "detail": m.group(3).strip(),
            })
    return checks


def clock_command(ip: str) -> str:
    """Comando do passo 8 do roteiro: acerta o relógio do robô pelo do PC."""
    return f"ssh ubuntu@{ip} \"sudo date -s '@$(date +%s.%N)'\""


def launch_commands(env: dict) -> list[tuple[str, list[str]]]:
    """Os dois launches do antigo `make robot-up`: lado do PC (mapa + AMCL +
    Nav2, ver docker/run-robot.sh) e o orquestrador (docker/run-fleet.sh)."""
    robot = ["ros2", "launch", "fleet_orchestrator", "turtlebot4_real.launch.py",
             f"map:={env.get('ROBOT_MAP') or 'hall_cin_v4'}",
             f"x_pose:={env.get('X_POSE') or '1.0216323137283325'}",
             f"y_pose:={env.get('Y_POSE') or '16.61626625061035'}",
             f"yaw:={env.get('YAW') or '0.0'}"]
    fleet = ["ros2", "launch", "fleet_orchestrator", "fleet.launch.py", "single_robot_sim:=true"]
    return [("robot", robot), ("fleet", fleet)]


def _idle_state() -> dict:
    return {"phase": "idle", "ip": None, "message": "", "checks": [], "lines": [],
            "clock_command": None, "started_at": None}


class RobotLink:
    """Estado e processos da ligação com o robô real. Uma conexão por vez.

    Fases: idle → checking (rede + pré-voo) → starting (launches subindo)
    → ready (Nav2 ativo e orquestrador no ar); qualquer falha → error.
    """

    def __init__(self, ros_ws: str, ros_env: Callable[[], dict], setup_prefix: Callable[[], str],
                 nav_ready: Callable[[float], bool]):
        self._ros_ws = ros_ws
        self._ros_env = ros_env
        self._setup_prefix = setup_prefix
        # nav_ready(started_at): o backend viu o Nav2 ativo depois desse instante.
        self._nav_ready = nav_ready
        self._lock = threading.Lock()
        self._state = _idle_state()
        self._procs: list[tuple[str, subprocess.Popen]] = []
        self._fleet_ready = False
        self._worker: Optional[threading.Thread] = None

    # ── estado ────────────────────────────────────────────────────────────
    def status(self) -> dict:
        with self._lock:
            state = dict(self._state)
            state["lines"] = list(state["lines"][-40:])
            state["checks"] = list(state["checks"])
            if (state["phase"] == "starting" and self._fleet_ready
                    and self._nav_ready(state["started_at"])):
                self._state["phase"] = state["phase"] = "ready"
                self._state["message"] = state["message"] = "Robô conectado: Nav2 ativo."
            if state["phase"] in ("starting", "ready") and any(p.poll() is not None for _, p in self._procs):
                self._state["phase"] = state["phase"] = "error"
                self._state["message"] = state["message"] = (
                    "Um dos processos do robô parou: veja as últimas linhas abaixo e reconecte.")
        return state

    def busy(self) -> bool:
        with self._lock:
            return self._state["phase"] in ("checking", "starting")

    def _set(self, **fields) -> None:
        with self._lock:
            self._state.update(fields)

    def _append(self, tag: str, line: str) -> None:
        with self._lock:
            self._state["lines"].append(f"[{tag}] {line}")
            if len(self._state["lines"]) > MAX_LINES:
                del self._state["lines"][: len(self._state["lines"]) - MAX_LINES]
            if tag == "fleet" and "fleet_orchestrator ready" in line:
                self._fleet_ready = True

    # ── conectar ──────────────────────────────────────────────────────────
    def connect(self, ip: str) -> dict:
        """Começa (ou recomeça) a ligação com o robô no IP dado. Volta na hora;
        o progresso aparece em status()."""
        ip = validate_ip(ip)
        with self._lock:
            if self._state["phase"] in ("checking", "starting"):
                raise RuntimeError("Já há uma conexão em andamento: espere ela terminar ou desconecte.")
            self._state = {**_idle_state(), "phase": "checking", "ip": ip,
                           "message": f"Procurando o robô em {ip}…", "clock_command": clock_command(ip)}
        self._worker = threading.Thread(target=self._run_connect, args=(ip,), daemon=True)
        self._worker.start()
        return self.status()

    def _run_connect(self, ip: str) -> None:
        self._stop_processes()
        ok, detail = check_reachable(ip)
        self._set(checks=[{"status": "ok" if ok else "fail", "name": "rede", "detail": detail}])
        if not ok:
            self._set(phase="error", message=detail)
            return

        self._set(message="Rede OK. Checagem pré-voo (só escuta o robô, ~15 s)…")
        try:
            output, code = self._run_preflight()
        except subprocess.TimeoutExpired:
            self._set(phase="error", message="A checagem pré-voo não terminou a tempo.")
            return
        checks = parse_preflight(output)
        with self._lock:
            self._state["checks"] = self._state["checks"] + checks
        failed = [c for c in checks if c["status"] == "fail"]
        if code != 0 or failed or not checks:
            reason = (f"{len(failed)} item(ns) com FALHA: resolver antes de mover o robô."
                      if failed else "A checagem pré-voo não rodou: veja as últimas linhas abaixo.")
            if not checks:
                for line in output.splitlines()[-15:]:
                    self._append("pré-voo", line)
            self._set(phase="error", message=reason)
            return

        self._set(phase="starting", started_at=time.monotonic(),
                  message="Checagem OK. Ligando mapa, AMCL e Nav2 no PC (~1 min)…")
        self._start_processes()

    def _run_preflight(self) -> tuple[str, int]:
        script = os.path.join(self._ros_ws, "scripts", "robot_preflight.py")
        cmd = " ".join(shlex.quote(c) for c in
                       ["python3", script, "--ignore-nodes", *BACKEND_NODES])
        result = subprocess.run(
            ["bash", "-c", self._setup_prefix() + cmd],
            capture_output=True, text=True, timeout=PREFLIGHT_TIMEOUT_S,
            cwd=self._ros_ws, env={**self._ros_env(), "PYTHONUNBUFFERED": "1"},
        )
        return (result.stdout or "") + (result.stderr or ""), result.returncode

    def _start_processes(self) -> None:
        env = {**self._ros_env(), "PYTHONUNBUFFERED": "1", "FLEET_USE_SIM_TIME": "false"}
        self._fleet_ready = False
        for tag, cmd in launch_commands(env):
            shell_cmd = self._setup_prefix() + " ".join(shlex.quote(c) for c in cmd)
            proc = subprocess.Popen(
                ["bash", "-c", shell_cmd],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=self._ros_ws, env=env,
                preexec_fn=os.setsid,
            )
            with self._lock:
                self._procs.append((tag, proc))
            threading.Thread(target=self._reader, args=(tag, proc), daemon=True).start()

    def _reader(self, tag: str, proc: subprocess.Popen) -> None:
        for raw in proc.stdout:
            line = raw.rstrip()
            if line:
                self._append(tag, line)

    # ── desconectar ───────────────────────────────────────────────────────
    def disconnect(self) -> None:
        self._stop_processes()
        with self._lock:
            self._state = _idle_state()

    def _stop_processes(self) -> None:
        with self._lock:
            procs = list(self._procs)
            self._procs.clear()
            self._fleet_ready = False
        if not procs:
            return
        for _tag, proc in procs:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGINT)
            except ProcessLookupError:
                continue
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and any(p.poll() is None for _, p in procs):
            time.sleep(0.2)
        for _tag, proc in procs:
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for pattern in _PROCESS_PATTERNS:
            subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)
