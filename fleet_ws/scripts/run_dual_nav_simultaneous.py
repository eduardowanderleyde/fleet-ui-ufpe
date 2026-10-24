#!/usr/bin/env python3
"""Mede taxa de sucesso de ativação SIMULTÂNEA (não sequencial) de Nav2+SLAM
completos em tb1 E tb2 ao mesmo tempo, com RMW parametrizável.

Pergunta de pesquisa: a troca de RMW (Fast DDS -> Cyclone DDS, hipótese 1 de
conhecimento/dds_tuning.md) muda a taxa de sucesso quando os DOIS robôs são
ativados DE VERDADE ao mesmo tempo (dois `ros2 launch activate_robot_nav`
disparados sem stagger nenhum), não só a ativação SEQUENCIAL já medida
(70%/10 no Cap. 9 da dissertação, que é o workaround atual: só 1 robô por
vez tem Nav2 completo ativo).

Reaproveita o padrão de boot+retry de run_fuut_pilot.py / run_ground_truth_
campaign.py (boot_multi_sim, kill_all_sim_processes, wait_for_log), mas SEM
retry dentro da réplica -- aqui queremos medir a taxa de sucesso bruta de
"dois de uma vez", não mascarar com retry.

Uso:
  cd fleet_ws
  source /opt/ros/jazzy/setup.bash && source install/setup.bash
  python3 scripts/run_dual_nav_simultaneous.py --repeat 5 \\
    --rmw rmw_fastrtps_cpp --output-dir runs/dual_nav_fastdds
  python3 scripts/run_dual_nav_simultaneous.py --repeat 5 \\
    --rmw rmw_cyclonedds_cpp --cyclonedds-fix --output-dir runs/dual_nav_cyclone
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

FLEET_WS = Path(__file__).resolve().parents[1]

SIM_PROCESS_PATTERNS = [
    "gz sim -r -s", "nav2_", "slam_toolbox", "fleet_orchestrator",
    "sensor_collector", "ros_gz_bridge/parameter_bridge",
    "ros_gz_image/image_bridge", "robot_state_publisher", "rviz2",
    "opennav_docking", "ground_truth_filter", "ros2 launch fleet_orchestrator",
    "activate_robot_nav",
]
SIM_READY = "fleet_orchestrator ready"
ACTIVATE_READY = "Managed nodes are active"
FAIL_MARKERS = ("Aborting bringup", "Failed to bring up all requested nodes")

# Fix conhecido pro bug "Failed to find a free participant index" do Cyclone
# DDS sob bringup concorrente (ros2/rmw_cyclonedds#458), já documentado em
# conhecimento/dds_tuning.md (achado de 2026-10-05) -- nunca testado ao vivo
# até esta sessão.
CYCLONEDDS_URI_FIX = (
    "<CycloneDDS><Domain><Discovery>"
    "<ParticipantIndex>auto</ParticipantIndex>"
    "<MaxAutoParticipantIndex>100</MaxAutoParticipantIndex>"
    "</Discovery></Domain></CycloneDDS>"
)


def _ros_prefix() -> str:
    return "source /opt/ros/jazzy/setup.bash && source install/setup.bash && "


def kill_all_sim_processes() -> None:
    for pattern in SIM_PROCESS_PATTERNS:
        subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)
    time.sleep(2)


def processes_alive() -> list[str]:
    lines: list[str] = []
    for pattern in SIM_PROCESS_PATTERNS:
        out = subprocess.run(["pgrep", "-fa", pattern], capture_output=True, text=True)
        lines += [l for l in out.stdout.splitlines() if l.strip()]
    return lines


def launch_bash(cmd: str, log_path: Path, extra_env: dict) -> subprocess.Popen:
    env = {**os.environ, "PYTHONUNBUFFERED": "1", **extra_env}
    full = _ros_prefix() + cmd
    log_f = open(log_path, "w")
    return subprocess.Popen(
        ["bash", "-c", full], stdout=log_f, stderr=subprocess.STDOUT,
        cwd=FLEET_WS, env=env, preexec_fn=os.setsid,
    )


def kill_proc_group(proc) -> None:
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


def wait_for_log(log_path: Path, needle: str, fail_any: tuple, timeout_s: float) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if log_path.exists():
            text = log_path.read_text(errors="ignore")
            if any(pat in text for pat in fail_any):
                return "fail"
            if needle in text:
                return "ready"
        time.sleep(1)
    return "timeout"


def count_jumps(log_path: Path) -> int:
    if not log_path.exists():
        return 0
    text = log_path.read_text(errors="ignore")
    return len(re.findall(r"Detected jump back in time", text))


def boot_multi_sim(world: str, run_dir: Path, replicate_id: int, extra_env: dict) -> tuple:
    kill_all_sim_processes()
    sim_log = run_dir / f"r{replicate_id:02d}_sim.log"
    fleet_log = run_dir / f"r{replicate_id:02d}_fleet.log"
    sim_cmd = (
        "ros2 launch fleet_orchestrator turtlebot4_multi_sim.launch.py "
        f"world:={world} headless:=true bringup_nav:=false"
    )
    sim_proc = launch_bash(sim_cmd, sim_log, {**extra_env, "FLEET_ROBOTS": "tb1,tb2"})
    fleet_cmd = "ros2 launch fleet_orchestrator fleet.launch.py"
    fleet_proc = launch_bash(fleet_cmd, fleet_log, {**extra_env, "FLEET_ROBOTS": "tb1,tb2"})
    status = wait_for_log(fleet_log, SIM_READY, FAIL_MARKERS, 60.0)
    if status != "ready":
        kill_proc_group(sim_proc)
        kill_proc_group(fleet_proc)
        raise RuntimeError(f"bringup multi-robo nao ficou pronto (status={status}) -- ver {fleet_log}")
    return sim_proc, fleet_proc


def activate_both_simultaneously(run_dir: Path, replicate_id: int, timeout_s: float, extra_env: dict) -> dict:
    """Dispara tb1 E tb2 SEM stagger (back-to-back, mesma chamada de
    subprocess.Popen uma depois da outra, sem esperar nenhum sinal do
    primeiro antes de lançar o segundo) -- isso É o teste: ativação
    genuinamente simultânea, não sequencial com pausa."""
    log_tb1 = run_dir / f"r{replicate_id:02d}_activate_tb1.log"
    log_tb2 = run_dir / f"r{replicate_id:02d}_activate_tb2.log"
    t0 = time.monotonic()
    proc_tb1 = launch_bash(
        "ros2 launch fleet_orchestrator activate_robot_nav.launch.py namespace:=tb1",
        log_tb1, extra_env,
    )
    proc_tb2 = launch_bash(
        "ros2 launch fleet_orchestrator activate_robot_nav.launch.py namespace:=tb2",
        log_tb2, extra_env,
    )

    deadline = t0 + timeout_s
    status_tb1 = status_tb2 = None
    while time.monotonic() < deadline and (status_tb1 is None or status_tb2 is None):
        if status_tb1 is None:
            text1 = log_tb1.read_text(errors="ignore") if log_tb1.exists() else ""
            if any(p in text1 for p in FAIL_MARKERS):
                status_tb1 = "fail"
            elif ACTIVATE_READY in text1:
                status_tb1 = "ready"
        if status_tb2 is None:
            text2 = log_tb2.read_text(errors="ignore") if log_tb2.exists() else ""
            if any(p in text2 for p in FAIL_MARKERS):
                status_tb2 = "fail"
            elif ACTIVATE_READY in text2:
                status_tb2 = "ready"
        if status_tb1 is None or status_tb2 is None:
            time.sleep(1)
    elapsed = time.monotonic() - t0
    status_tb1 = status_tb1 or "timeout"
    status_tb2 = status_tb2 or "timeout"

    kill_proc_group(proc_tb1)
    kill_proc_group(proc_tb2)
    subprocess.run(["pkill", "-9", "-f", "activate_robot_nav"], capture_output=True)

    return {
        "status_tb1": status_tb1,
        "status_tb2": status_tb2,
        "both_ready": status_tb1 == "ready" and status_tb2 == "ready",
        "elapsed_sec": round(elapsed, 1),
        "jumps_tb1": count_jumps(log_tb1),
        "jumps_tb2": count_jumps(log_tb2),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--world", default="warehouse")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--rmw", default="", help="RMW_IMPLEMENTATION a usar (vazio = default do ambiente, Fast DDS)")
    ap.add_argument("--cyclonedds-fix", action="store_true", help="Aplica CYCLONEDDS_URI com ParticipantIndex=auto (fix pro bug ros2/rmw_cyclonedds#458)")
    ap.add_argument("--activate-timeout", type=float, default=120.0)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    extra_env = {}
    if args.rmw:
        extra_env["RMW_IMPLEMENTATION"] = args.rmw
    if args.cyclonedds_fix:
        extra_env["CYCLONEDDS_URI"] = CYCLONEDDS_URI_FIX

    run_dir = FLEET_WS / args.output_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "rmw": args.rmw or "(default/fastrtps)",
        "cyclonedds_fix": args.cyclonedds_fix,
        "repeat": args.repeat,
        "activate_timeout_s": args.activate_timeout,
        "replicas": [],
    }

    for rid in range(1, args.repeat + 1):
        print(f"=== Réplica {rid}/{args.repeat} (rmw={manifest['rmw']}) ===")
        sim_proc = fleet_proc = None
        entry = {"replicate_id": rid}
        try:
            sim_proc, fleet_proc = boot_multi_sim(args.world, run_dir, rid, extra_env)
            print(f"  [réplica {rid}] sim pronta, disparando tb1+tb2 simultaneamente...")
            result = activate_both_simultaneously(run_dir, rid, args.activate_timeout, extra_env)
            entry.update(result)
            entry["boot_ok"] = True
            print(f"  [réplica {rid}] tb1={result['status_tb1']} tb2={result['status_tb2']} "
                  f"jumps_tb1={result['jumps_tb1']} jumps_tb2={result['jumps_tb2']} "
                  f"elapsed={result['elapsed_sec']}s")
        except RuntimeError as exc:
            entry["boot_ok"] = False
            entry["error"] = str(exc)
            entry["both_ready"] = False
            print(f"  [réplica {rid}] FALHA DE BOOT: {exc}")
        finally:
            kill_proc_group(fleet_proc)
            kill_proc_group(sim_proc)
            kill_all_sim_processes()
            survivors = processes_alive()
            if survivors:
                print(f"  [AVISO] processos sobreviveram ao cleanup: {survivors}")
        manifest["replicas"].append(entry)

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    n_ok = sum(1 for r in manifest["replicas"] if r.get("both_ready"))
    manifest["summary"] = {
        "both_ready_count": n_ok,
        "total": args.repeat,
        "success_rate": round(n_ok / args.repeat, 3) if args.repeat else None,
    }
    manifest_path = run_dir / "dual_nav_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"\n=== {n_ok}/{args.repeat} réplicas com tb1 E tb2 simultaneamente ativos ===")
    print(f"Manifesto: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
