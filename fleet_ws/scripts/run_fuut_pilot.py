#!/usr/bin/env python3
"""
Piloto FUUT: tb1 (MUUT) faz replay normal de uma rota já gravada enquanto
tb2 (FUUT) fica parado, sem Nav2, só observando via LiDAR. Cruza a pose que
o tb1 reivindica (via /pose, SLAM) contra o que o tb2 detectou (subtração
de scan de referência) no FuutVerifier já existente.

Fecha a lacuna "papel FUUT nunca exercitado" (Cap. 9, Limitações) — ver
openspec/changes/fuut-pilot-experiment/ pra proposta, specs e design
completos. N pequeno (3-5): é piloto, não campanha com poder amostral.

Pré-requisitos (exportar antes de rodar):
  export ANTHROPIC_API_KEY=...   # não usado aqui diretamente, mas
                                  # compartilha env com outros scripts
  export TYPESAFE_API_KEY=...    # obrigatório — FuutVerifier chama TypeSafe

Uso:
  cd fleet_ws
  source /opt/ros/jazzy/setup.bash && source install/setup.bash
  python3 scripts/run_fuut_pilot.py --repeat 3 --route fleet_pilot_tb1_v3 \\
    --output-dir runs/fuut_pilot01
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import rclpy
import yaml
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan

FLEET_WS = Path(__file__).resolve().parents[1]
REPO_ROOT = FLEET_WS.parent
ROLES_PATH = FLEET_WS / "src" / "fleet_orchestrator" / "config" / "roles.yaml"

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from fuut_detection import detect_obstacle  # noqa: E402
from fuut_reference_scan import capture_reference_scan  # noqa: E402
from agents.fuut_verify import FuutVerifier, FuutPose, FuutObservation, MuutClaim  # noqa: E402
import analyze_runs  # noqa: E402

# Spawn default de tb2 em turtlebot4_multi_sim.launch.py (DEFAULT_POSES):
# x=0.0, y=2.0, yaw=0.0. yaw=0 significa que o eixo local do LiDAR do FUUT
# coincide com o eixo x do mundo — sem essa coincidência, bearing_deg (local)
# precisaria ser rotacionado pelo yaw do FUUT antes de ir pro FuutVerifier,
# o que este piloto não implementa (ver design.md, Risco de geometria).
FUUT_SPAWN_POSE = FuutPose(x=0.0, y=2.0)

# Offset de montagem do LiDAR do FUUT relativo ao eixo frontal do base_link,
# medido empiricamente (não lido do URDF): piloto real de 3 réplicas
# (runs/fuut_pilot01/, antes desta correção) mostrou distância detectada
# correta (~2,0-2,15m, batendo com a geometria real) mas bearing sempre
# ~87-90° fora do esperado, de forma consistente — assinatura de rotação
# fixa de montagem, não ruído. 90° é a hipótese mais simples compatível
# com os 3 valores medidos (87,2° / 88,5° / 89,7°); não foi confirmado
# contra o transform lidar_link→base_link do URDF (trabalho futuro).
FUUT_LIDAR_YAW_OFFSET_DEG = 90.0

SIM_PROCESS_PATTERNS = [
    "gz sim -r -s", "nav2_", "slam_toolbox", "fleet_orchestrator",
    "sensor_collector", "ros_gz_bridge/parameter_bridge",
    "ros_gz_image/image_bridge", "robot_state_publisher", "rviz2",
    "opennav_docking", "ground_truth_filter", "ros2 launch fleet_orchestrator",
]
SIM_READY = "fleet_orchestrator ready"
ACTIVATE_READY = "Managed nodes are active"
FAIL_MARKERS = ("Aborting bringup", "Failed to bring up all requested nodes")


def _ros_prefix() -> str:
    return "source /opt/ros/jazzy/setup.bash && source install/setup.bash && "


def kill_all_sim_processes() -> None:
    for pattern in SIM_PROCESS_PATTERNS:
        subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)
    time.sleep(2)


def launch_bash(cmd: str, log_path: Path, extra_env: dict | None = None) -> subprocess.Popen:
    env = {**os.environ, "PYTHONUNBUFFERED": "1", **(extra_env or {})}
    full = _ros_prefix() + cmd
    log_f = open(log_path, "w")
    return subprocess.Popen(
        ["bash", "-c", full], stdout=log_f, stderr=subprocess.STDOUT,
        cwd=FLEET_WS, env=env, preexec_fn=os.setsid,
    )


def kill_proc_group(proc: subprocess.Popen | None) -> None:
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


def wait_for_log(log_path: Path, ready_all: tuple, fail_any: tuple, timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if log_path.exists():
            text = log_path.read_text(errors="ignore")
            if any(pat in text for pat in fail_any):
                return "fail"
            if all(pat in text for pat in ready_all):
                return "ready"
        time.sleep(1)
    return "timeout"


class _RolesOverride:
    """Troca roles.yaml pra tb1=MUUT/tb2=FUUT durante o `with`, restaura o
    conteúdo original ao saber (mesmo em exceção) — design.md Decisão 1."""

    def __enter__(self):
        self._original = ROLES_PATH.read_text()
        data = yaml.safe_load(self._original) or {}
        roles = dict(data.get("roles") or {})
        roles["tb1"] = "MUUT"
        roles["tb2"] = "FUUT"
        ROLES_PATH.write_text(yaml.safe_dump({"roles": roles}, sort_keys=False))
        return self

    def __exit__(self, *exc):
        ROLES_PATH.write_text(self._original)
        return False


def boot_multi_sim(world: str, run_dir: Path) -> tuple[subprocess.Popen, subprocess.Popen]:
    kill_all_sim_processes()
    sim_log = run_dir / "sim.log"
    fleet_log = run_dir / "fleet.log"
    sim_cmd = (
        "ros2 launch fleet_orchestrator turtlebot4_multi_sim.launch.py "
        f"world:={world} headless:=true bringup_nav:=false"
    )
    sim_proc = launch_bash(sim_cmd, sim_log, extra_env={"FLEET_ROBOTS": "tb1,tb2"})
    status = wait_for_log(fleet_log, (), FAIL_MARKERS, 5.0)  # só drena erro cedo, não bloqueia
    fleet_cmd = "ros2 launch fleet_orchestrator fleet.launch.py"
    fleet_proc = launch_bash(fleet_cmd, fleet_log, extra_env={"FLEET_ROBOTS": "tb1,tb2"})
    status = wait_for_log(fleet_log, (SIM_READY,), FAIL_MARKERS, 60.0)
    if status != "ready":
        kill_proc_group(sim_proc)
        kill_proc_group(fleet_proc)
        raise RuntimeError(f"bringup multi-robô não ficou pronto (status={status}) — ver {fleet_log}")
    return sim_proc, fleet_proc


def activate_tb1_nav(run_dir: Path, max_retries: int = 3) -> subprocess.Popen:
    """Ativação sequencial falha espontaneamente em parte das tentativas —
    já documentado na dissertação (Cap. 9, Limitações: 70% de sucesso em
    10 tentativas, sem padrão ligado à ordem). Retry mata e tenta de novo,
    mesmo padrão de run_ground_truth_campaign.py::boot_stack."""
    cmd = "ros2 launch fleet_orchestrator activate_robot_nav.launch.py namespace:=tb1"
    for attempt in range(max_retries + 1):
        log = run_dir / f"activate_tb1_attempt{attempt}.log"
        proc = launch_bash(cmd, log)
        status = wait_for_log(log, (ACTIVATE_READY,), FAIL_MARKERS, 45.0)
        if status == "ready":
            return proc
        print(f"  [tentativa {attempt}] ativação de tb1 = {status}, matando e tentando de novo")
        kill_proc_group(proc)
        subprocess.run(["pkill", "-9", "-f", "activate_robot_nav"], capture_output=True)
        time.sleep(3)
    raise RuntimeError(f"Nav2 de tb1 não ativou após {max_retries + 1} tentativas — ver {run_dir}/activate_tb1_attempt*.log")


class _FuutScanSampler(Node):
    """Amostra /tb2/scan continuamente enquanto tb1 faz replay, guardando
    (timestamp_absoluto, ranges) — comparado contra a referência depois."""

    def __init__(self) -> None:
        super().__init__("fuut_scan_sampler")
        self.samples: list[tuple[float, list[float], float, float]] = []
        self.create_subscription(LaserScan, "/tb2/scan", self._cb, qos_profile_sensor_data)

    def _cb(self, msg: LaserScan) -> None:
        t = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
        self.samples.append((t, list(msg.ranges), msg.angle_min, msg.angle_increment))


def run_replica(route: str, replicate_id: int, run_dir: Path) -> dict:
    """Roda uma réplica: dispara replay de tb1 em subprocesso, amostra o
    scan de tb2 concorrentemente, devolve os dados crus (sem verificação
    ainda — isso é feito depois, fora da janela de tempo real)."""
    sampler = _FuutScanSampler()
    executor = SingleThreadedExecutor()
    executor.add_node(sampler)
    stop = threading.Event()

    def spin():
        while not stop.is_set():
            executor.spin_once(timeout_sec=0.1)

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()

    export_path = run_dir / f"replay_r{replicate_id:02d}.json"
    cmd = [
        "python3", "scripts/experiment_repeatability.py", "replay",
        "--robot", "tb1", "--route", route, "--export", str(export_path),
    ]
    shell_cmd = _ros_prefix() + " ".join(shlex.quote(c) for c in cmd)
    result = subprocess.run(
        ["bash", "-c", shell_cmd], cwd=FLEET_WS, capture_output=True, text=True,
    )
    (run_dir / f"replay_r{replicate_id:02d}.log").write_text(result.stdout + result.stderr)

    stop.set()
    thread.join(timeout=2.0)
    sampler.destroy_node()

    rosbag_path = None
    if export_path.exists():
        rosbag_path = json.loads(export_path.read_text()).get("rosbag_path")

    # Persiste as amostras cruas do FUUT em disco — sem isso, o único
    # registro do que o FUUT observou vivia na memória do processo,
    # perdido ao final da réplica (achado ao escrever este script: a spec
    # fuut-pilot-campaign exige que a observação fique recuperável por
    # réplica, não só o resultado já derivado).
    samples_path = run_dir / f"fuut_samples_r{replicate_id:02d}.json"
    samples_path.write_text(json.dumps(sampler.samples))

    return {
        "replicate_id": replicate_id,
        "replay_ok": result.returncode == 0,
        "rosbag_path": rosbag_path,
        "fuut_samples_path": str(samples_path),
        "fuut_samples": sampler.samples,
    }


def build_report_entry(reference: dict, replica: dict, verifier: FuutVerifier) -> dict:
    ref_ranges = reference["ranges"]
    detections = []
    for t, ranges, angle_min, angle_inc in replica["fuut_samples"]:
        if len(ranges) != len(ref_ranges):
            continue
        obs = detect_obstacle(ref_ranges, ranges, angle_min, angle_inc)
        if obs is not None:
            detections.append((t, obs))

    if not detections or not replica["rosbag_path"]:
        return {
            "replicate_id": replica["replicate_id"],
            "status": "sem_correspondencia",
            "reason": "nenhuma detecção do FUUT" if not detections else "sem rosbag do MUUT",
        }

    bag_dir = Path(replica["rosbag_path"])
    _, t_abs, x_arr, y_arr, _ = analyze_runs._read_traj_xy(
        bag_dir, "/tb1/pose", use_header_stamp=True, rebase=False,
    )

    best_pair = None
    for t_fuut, obs in detections:
        idx = min(range(len(t_abs)), key=lambda i: abs(t_abs[i] - t_fuut))
        dt = abs(t_abs[idx] - t_fuut)
        if dt <= 0.2 and (best_pair is None or dt < best_pair[0]):
            best_pair = (dt, idx, obs, t_fuut)

    if best_pair is None:
        return {
            "replicate_id": replica["replicate_id"],
            "status": "sem_correspondencia",
            "reason": "nenhuma detecção do FUUT dentro de 200ms de uma pose do MUUT",
        }

    _, idx, obs, t_fuut = best_pair
    claim = MuutClaim(x=float(x_arr[idx]), y=float(y_arr[idx]), timestamp_s=float(t_abs[idx]))
    corrected_bearing_deg = obs.bearing_deg + FUUT_LIDAR_YAW_OFFSET_DEG
    observation = FuutObservation(
        distance_m=obs.distance_m, bearing_deg=corrected_bearing_deg, timestamp_s=t_fuut,
    )
    result = verifier.verify(FUUT_SPAWN_POSE, observation, claim)
    return {
        "replicate_id": replica["replicate_id"],
        "status": "verificado",
        "muut_claim": {"x": claim.x, "y": claim.y, "timestamp_s": claim.timestamp_s},
        "fuut_observation": {
            "distance_m": observation.distance_m,
            "bearing_deg": observation.bearing_deg,
            "timestamp_s": observation.timestamp_s,
        },
        "level": result.level,
        "label": result.label,
        "confidence": result.confidence,
        "geometric_discrepancy_m": result.geometric_discrepancy_m,
        "time_discrepancy_s": result.time_discrepancy_s,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--world", default="warehouse")
    p.add_argument("--route", default="fleet_pilot_tb1_v3")
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()

    if not os.environ.get("TYPESAFE_API_KEY"):
        print("erro: TYPESAFE_API_KEY não exportada — FuutVerifier precisa dela", file=sys.stderr)
        return 1

    run_dir = Path(args.output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    report: list[dict] = []
    sim_proc = fleet_proc = activate_proc = None
    try:
        with _RolesOverride():
            sim_proc, fleet_proc = boot_multi_sim(args.world, run_dir)
            activate_proc = activate_tb1_nav(run_dir)

            rclpy.init()
            try:
                reference = capture_reference_scan("tb2", timeout_sec=15.0)
                (run_dir / "fuut_reference.json").write_text(json.dumps(reference))

                verifier = FuutVerifier()
                for i in range(1, args.repeat + 1):
                    print(f"[réplica {i}/{args.repeat}] rodando replay de tb1...")
                    replica = run_replica(args.route, i, run_dir)
                    entry = build_report_entry(reference, replica, verifier)
                    print(f"[réplica {i}/{args.repeat}] {entry['status']}")
                    report.append(entry)
            finally:
                rclpy.shutdown()
    finally:
        kill_proc_group(activate_proc)
        kill_proc_group(fleet_proc)
        kill_proc_group(sim_proc)
        kill_all_sim_processes()

    report_path = run_dir / "fuut_verification_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nrelatório salvo em {report_path}")
    verified = [e for e in report if e["status"] == "verificado"]
    print(f"{len(verified)}/{len(report)} réplicas com correspondência FUUT-MUUT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
