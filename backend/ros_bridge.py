from __future__ import annotations

import ast
import concurrent.futures
import json
import math
import os
import re
import shlex
import socket
import subprocess
from pathlib import Path

import yaml


class RosBridge:
    """Boundary for shell/ROS integration used by the FastAPI layer."""

    def __init__(self, ros_ws: str, *, ros_distro: str = "jazzy") -> None:
        self.ros_ws = str(Path(ros_ws))
        self.ros_distro = ros_distro

    def ros_env(self) -> dict:
        return {
            **os.environ,
            "ROS_DOMAIN_ID": os.environ.get("ROS_DOMAIN_ID", "0"),
        }

    # Pacotes ament_python deste workspace (setup.py, não ament_cmake) — o
    # colcon-core instalado nesta máquina (0.20.1) não gera hook de
    # AMENT_PREFIX_PATH pra esse tipo de pacote (só pythonpath.dsv), então
    # install/setup.bash sozinho nunca inclui esses diretórios no path,
    # mesmo depois de `colcon build` — `ros2 launch fleet_orchestrator ...`
    # falha com "Package not found" apesar do pacote existir e estar
    # buildado. fleet_msgs (ament_cmake, gera mensagem) não tem esse
    # problema, só os pacotes 100% Python. Achado ao vivo reconstruindo o
    # workspace pra testar um launch file novo — sem isso, a simulação
    # inteira (não só a novidade) para de subir.
    _AMENT_PYTHON_PACKAGES = ["fleet_orchestrator", "fleet_data_collector"]

    def ros_setup_prefix(self) -> str:
        extra_ament_path = ":".join(
            f"{shlex.quote(self.ros_ws)}/install/{pkg}" for pkg in self._AMENT_PYTHON_PACKAGES
        )
        return (
            f"source /opt/ros/{shlex.quote(self.ros_distro)}/setup.bash 2>/dev/null; "
            f"source {shlex.quote(self.ros_ws)}/install/setup.bash 2>/dev/null; "
            f"export AMENT_PREFIX_PATH=\"{extra_ament_path}:$AMENT_PREFIX_PATH\"; "
        )

    def run_service(self, service: str, service_type: str, request: dict | str, timeout: int = 10) -> tuple[bool, str]:
        request_json = request if isinstance(request, str) else json.dumps(request)
        cmd = f"{self.ros_setup_prefix()}ros2 service call {shlex.quote(service)} {shlex.quote(service_type)} {shlex.quote(request_json)}"
        try:
            result = subprocess.run(
                ["bash", "-c", cmd],
                env=self.ros_env(),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.ros_ws,
            )
            out = (result.stdout or "").strip() + (result.stderr or "").strip()
            if result.returncode != 0:
                return False, out or "ros2 service call failed"
            return True, out
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as exc:
            return False, str(exc)

    def run_param_set(self, node: str, param: str, value: str, timeout: int = 10) -> tuple[bool, str]:
        cmd = f"{self.ros_setup_prefix()}ros2 param set {shlex.quote(node)} {shlex.quote(param)} {shlex.quote(value)}"
        try:
            result = subprocess.run(
                ["bash", "-c", cmd],
                env=self.ros_env(),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.ros_ws,
            )
            out = (result.stdout or "").strip() + (result.stderr or "").strip()
            if result.returncode != 0:
                return False, out or "ros2 param set failed"
            return True, out
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def extract_list_field(out: str, field: str) -> list:
        """Extrai um campo de lista do texto que `ros2 service call` imprime.

        A saída do CLI NUNCA foi YAML válido — é prosa solta ("waiting for
        service...", "requester: making request: ...") seguida de
        "response:\\n" e o repr() do Python da mensagem de resposta, ex.:
        `fleet_msgs.srv.ListRobots_Response(robot_ids=['tb1', 'tb2'])`.
        Tentar `yaml.safe_load(out)` nisso sempre lançou ScannerError
        (confirmado ao vivo contra uma frota real de 2 robôs — list_robots
        voltava `[]` mesmo com tb1/tb2 configurados). Em vez de tentar
        casar esse texto num parser genérico, extrai só o campo pedido via
        regex + `ast.literal_eval` (é um literal Python de verdade, não
        precisa de um parser mais esperto que isso)."""
        idx = out.rfind("response:")
        tail = out[idx + len("response:"):] if idx != -1 else out
        match = re.search(rf"{re.escape(field)}=(\[[^\]]*\])", tail)
        if not match:
            return []
        try:
            value = ast.literal_eval(match.group(1))
            return list(value) if isinstance(value, (list, tuple)) else []
        except (ValueError, SyntaxError):
            return []

    def build_experiment_cmd(self, cfg: dict) -> list[str]:
        command = cfg.get("command", "record")
        robot = cfg.get("robot", "")
        single = not robot or robot == "default"
        route = cfg.get("route", "percurso1")
        collect = cfg.get("collect", True)
        topics = cfg.get("topics", ["scan", "odom", "imu", "pose"])
        initial_pose = cfg.get("initial_pose")
        args = [
            "python3", str(Path(self.ros_ws) / "scripts" / "experiment_repeatability.py"),
            command, "--route", route,
        ]
        if single:
            args += ["--single-robot"]
        else:
            args += ["--robot", robot]
        if not collect:
            args += ["--skip-collection"]
        if os.environ.get("FLEET_USE_SIM_TIME", "true").strip().lower() in ("false", "0", "no"):
            args += ["--no-use-sim-time"]
        elif topics:
            args += ["--topics"] + topics
        if initial_pose is not None and any(v != 0 for v in initial_pose):
            args += [f"--initial-pose={initial_pose[0]},{initial_pose[1]},{initial_pose[2]}"]
        if command == "record":
            points = cfg.get("points", [])
            if points:
                joined = ";".join(f"{p[0]},{p[1]},{p[2] if len(p) > 2 else 0}" for p in points)
                args += [f"--points={joined}"]
        elif command == "replay":
            route_robot = robot if not single else ""
            return_to_start = cfg.get("return_to_start")
            if return_to_start and any(v != 0 for v in return_to_start):
                legs = self._return_legs(route, route_robot, return_to_start, cfg.get("current_pose"))
                joined = ";".join(f"{x},{y},{yaw}" for x, y, yaw in legs)
                args += [f"--return-to-start={joined}"]
            args += [f"--wait-goal={self._replay_wait_sec(route, route_robot)}"]
        return args

    def _route_poses(self, route: str, robot_id: str) -> list[tuple[float, float, float]] | None:
        path = Path(self.ros_ws) / "routes" / (robot_id or "default") / f"{route}.yaml"
        try:
            poses = (yaml.safe_load(path.read_text()) or {}).get("poses") or []
            return [(float(p["x"]), float(p["y"]), float(p.get("yaw", 0.0))) for p in poses]
        except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError):
            return None

    def _return_legs(self, route: str, robot_id: str, target, current=None) -> list[tuple[float, float, float]]:
        """Volta ao início pelo percurso ao contrário quando o alvo é o 1º ponto da rota.

        Um goal único direto até o início (diagonal de ~75 m no percurso do
        CBSoft) abortava no Nav2; refazendo os trechos da ida a partir do ponto
        da rota mais próximo do robô, chega. Sem pose atual, ou com alvo
        digitado à mão (≠ 1º ponto), segue direto como antes."""
        target = (float(target[0]), float(target[1]), float(target[2]))
        poses = self._route_poses(route, robot_id)
        if not poses or current is None or math.hypot(poses[0][0] - target[0], poses[0][1] - target[1]) > 0.05:
            return [target]
        nearest = min(range(len(poses)), key=lambda i: math.hypot(poses[i][0] - current[0], poses[i][1] - current[1]))
        if nearest == 0:
            return [target]
        # Na volta, cada meta aponta para a próxima (sentido da volta), não para
        # a orientação gravada na ida, que faria o robô girar ~180° a cada
        # trecho; a última usa a orientação pedida em return_to_start.
        points = [(p[0], p[1]) for p in reversed(poses[:nearest])]
        legs = [
            (x, y, math.atan2(ny - y, nx - x))
            for (x, y), (nx, ny) in zip(points, points[1:])
        ]
        legs.append((points[-1][0], points[-1][1], target[2]))
        return legs

    # Velocidade bem abaixo do limite de 0,26 m/s do velocity_smoother, pra
    # sobrar folga pra curvas e replanejamento.
    _REPLAY_SPEED_FLOOR_MPS = 0.15

    def _replay_wait_sec(self, route: str, robot_id: str) -> int:
        """Timeout do replay proporcional ao tamanho da rota.

        O padrão fixo de 300 s do experiment_repeatability.py corta rotas
        longas no meio (o percurso do CBSoft leva ~390 s): o script desiste,
        marca falha e desliga a coleta com o robô ainda andando."""
        poses = self._route_poses(route, robot_id)
        if not poses:
            return 300
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(poses, poses[1:]))
        return max(300, int(length / self._REPLAY_SPEED_FLOOR_MPS) + 60)

    def run_experiment_step(
        self, cmd: list[str], export_path: str, line_callback=None, on_start=None,
    ) -> dict:
        """Roda um record/replay do experiment_repeatability.py até o fim (bloqueante).
        Usado tanto por /api/run_config (1 passo) quanto por uma campanha (N passos em
        sequência) — ver /api/run_campaign. `line_callback`, se dado, recebe cada linha
        de saída assim que chega (para streaming de progresso). `on_start`, se dado,
        recebe o Popen logo depois de criado: o processo roda no próprio grupo
        (setsid), para /api/job/<id>/stop poder encerrá-lo inteiro."""
        env = {**self.ros_env(), "PYTHONUNBUFFERED": "1"}
        shell_cmd = self.ros_setup_prefix() + " ".join(shlex.quote(c) for c in cmd)
        lines: list[str] = []
        out: dict = {"lines": lines, "result": None, "error": None, "exit_code": None}
        noise = ("TF_OLD_DATA", "RTPS_TRANSPORT_SHM", "Possible reasons", "ros.org/tf")
        try:
            proc = subprocess.Popen(
                ["bash", "-c", shell_cmd],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=self.ros_ws, env=env,
                preexec_fn=os.setsid,
            )
            if on_start:
                on_start(proc)
            for line in proc.stdout:
                l = line.rstrip()
                if any(n in l for n in noise):
                    continue
                lines.append(l)
                if line_callback:
                    line_callback(l)
            proc.wait()
            out["exit_code"] = proc.returncode
            ep = Path(export_path)
            if ep.exists():
                out["result"] = json.loads(ep.read_text())
                ep.unlink(missing_ok=True)
        except Exception as exc:
            out["error"] = str(exc)
        return out

    def analyze_bags(self, bag_paths: list[str], labels: list[str], output_dir: str, timeout: int = 180) -> tuple[bool, str]:
        """Roda analyze_runs.py sobre os bags de uma campanha, produzindo
        <output_dir>/summary.json (formato que Analyst.load_summary espera)."""
        script = str(Path(self.ros_ws) / "scripts" / "analyze_runs.py")
        cmd = (
            self.ros_setup_prefix()
            + "python3 " + shlex.quote(script) + " "
            + " ".join(shlex.quote(p) for p in bag_paths)
            + " --output-dir " + shlex.quote(output_dir)
            + " --labels " + " ".join(shlex.quote(l) for l in labels)
        )
        try:
            result = subprocess.run(
                ["bash", "-c", cmd], env=self.ros_env(), capture_output=True,
                text=True, timeout=timeout, cwd=self.ros_ws,
            )
            out = (result.stdout or "") + (result.stderr or "")
            return result.returncode == 0, out
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as exc:
            return False, str(exc)

    def discover_robots(self, subnet: str = "") -> dict:
        subnet = subnet.strip()
        if not subnet:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.connect(("8.8.8.8", 80))
                local_ip = sock.getsockname()[0]
                sock.close()
                subnet = ".".join(local_ip.split(".")[:3])
            except Exception:
                return {
                    "found": [],
                    "subnet_scanned": "",
                    "error": "Não foi possível detectar subnet local. Informe manualmente (ex: 192.168.1)",
                }

        parts = subnet.split(".")
        if len(parts) != 3 or not all(part.isdigit() and 0 <= int(part) <= 255 for part in parts):
            return {
                "found": [],
                "subnet_scanned": subnet,
                "error": f"Subnet inválida: {subnet}. Use formato X.X.X (ex: 192.168.1)",
            }

        targets = [f"{subnet}.{i}" for i in range(1, 255)]

        def check(ip: str) -> dict | None:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.3)
                result = sock.connect_ex((ip, 22))
                sock.close()
                if result != 0:
                    return None
                try:
                    hostname = socket.gethostbyaddr(ip)[0]
                except Exception:
                    hostname = ip
                is_robot = any(kw in hostname.lower() for kw in ("tb", "turtle", "robot", "pi", "nano", "jetson", "ros"))
                return {"ip": ip, "hostname": hostname, "ssh": True, "likely_robot": is_robot}
            except Exception:
                return None

        found = []
        max_workers = int(os.environ.get("FLEET_DISCOVERY_WORKERS", "32"))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            for result in executor.map(check, targets):
                if result:
                    found.append(result)

        found.sort(key=lambda item: (not item["likely_robot"], item["ip"]))
        return {"found": found, "subnet_scanned": subnet}

    def test_ssh(self, host: str, user: str = "ubuntu", port: int = 22) -> dict:
        if not host:
            return {"success": False, "message": "host vazio"}

        strict = os.environ.get("FLEET_SSH_STRICT_HOST_KEY_CHECKING", "accept-new")
        known_hosts = os.environ.get("FLEET_SSH_KNOWN_HOSTS")
        options = [
            "-o", "ConnectTimeout=4",
            "-o", f"StrictHostKeyChecking={strict}",
            "-o", "BatchMode=yes",
        ]
        if known_hosts:
            options += ["-o", f"UserKnownHostsFile={known_hosts}"]

        remote = f"{user}@{host}"
        cmd = [
            "ssh",
            *options,
            "-p", str(port),
            remote,
            "which ros2 && ros2 --version 2>/dev/null || echo NO_ROS2",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            out = (result.stdout or "").strip()
            err = (result.stderr or "").strip()
            if result.returncode != 0:
                return {"success": False, "message": err or f"SSH falhou (exit {result.returncode})"}
            has_ros = "NO_ROS2" not in out and bool(out)
            return {
                "success": True,
                "has_ros2": has_ros,
                "ros2_version": out if has_ros else None,
                "message": f"ROS 2 encontrado: {out}" if has_ros else "SSH OK mas ROS 2 não encontrado",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "message": "Timeout ao conectar via SSH"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}
