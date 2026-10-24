#!/usr/bin/env python3
"""Campanha /odom vs /pose vs ground truth: N réplicas por rota, relançando a
simulação inteira (Gazebo+Nav2+SLAM+fleet_orchestrator) antes de cada
réplica, com confirmação de processo limpo e timeout+retry no bringup.

Por que isso existe (ver conhecimento/dds_tuning.md e implementacao.md,
2026-10-02): rodando o piloto desta campanha, confirmei ao vivo dois
problemas reais que uma campanha de várias réplicas sem cuidado pode
atropelar silenciosamente:

1. Processos órfãos de uma réplica anterior podem sobreviver a um `kill`
   simples e competir por CPU com a réplica seguinte, contaminando os
   dados (load average chegou a 14 numa sessão real desta máquina).
2. A ativação sequencial do Nav2/SLAM Toolbox falha espontaneamente em
   parte das tentativas (~70% de taxa de sucesso já documentado) — sem
   retry, uma campanha de N réplicas tem chance real de incluir réplicas
   que nunca ficaram prontas, sem nenhum aviso no resultado final.

Este script mata agressivamente por padrão de processo antes de CADA
réplica (não confia em PID rastreado sozinho), e tenta de novo até
--max-retries vezes se o bringup não sinalizar pronto a tempo.

Uso:
  cd fleet_ws
  source /opt/ros/jazzy/setup.bash && source install/setup.bash
  python3 scripts/run_ground_truth_campaign.py \\
    --route dissertation_clean01 --repeat 10 \\
    --protocol-id dissertation_gt01 \\
    --output-dir runs/dissertation_gt01
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

FLEET_WS = Path(__file__).resolve().parents[1]

# Mesmos padrões de segurança do backend (backend/main.py::_SIM_PROCESS_PATTERNS),
# com alguns extras (rviz2, image_bridge, opennav_docking, ground_truth_filter)
# achados ao vivo nesta sessão como também precisando de limpeza explícita.
SIM_PROCESS_PATTERNS = [
    "gz sim -r -s",
    "nav2_",
    "slam_toolbox",
    "fleet_orchestrator",
    "sensor_collector",
    "ros_gz_bridge/parameter_bridge",
    "ros_gz_image/image_bridge",
    "robot_state_publisher",
    "rviz2",
    "opennav_docking",
    "ground_truth_filter",
    "ros2 launch fleet_orchestrator",
]

SIM_READY = "Managed nodes are active"
SIM_FAIL = ("Aborting bringup", "Failed to bring up all requested nodes")
FLEET_READY = ("fleet_orchestrator ready", "sensor_collector ready")


def _ros_prefix() -> str:
    return "source /opt/ros/jazzy/setup.bash && source install/setup.bash && "


def kill_all_sim_processes(verbose: bool = True) -> None:
    """Mata por padrão de nome, confirma que nada sobrou. Rede de segurança
    deliberadamente agressiva (kill -9 direto) -- esta campanha relança a
    stack inteira dezenas de vezes, não dá pra confiar em "provavelmente já
    morreu"."""
    for pattern in SIM_PROCESS_PATTERNS:
        subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)
    time.sleep(2)
    survivors = processes_alive()
    if survivors:
        if verbose:
            print(f"[AVISO] processos sobreviveram ao kill, tentando de novo: {survivors}")
        for pattern in SIM_PROCESS_PATTERNS:
            subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)
        time.sleep(2)
        survivors = processes_alive()
        if survivors and verbose:
            print(f"[AVISO] ainda sobreviveram depois da 2a tentativa: {survivors}")


def processes_alive() -> list[str]:
    lines: list[str] = []
    for pattern in SIM_PROCESS_PATTERNS:
        out = subprocess.run(["pgrep", "-fa", pattern], capture_output=True, text=True)
        lines += [l for l in out.stdout.splitlines() if l.strip()]
    return lines


def launch_bash(cmd: str, log_path: Path) -> subprocess.Popen:
    full = _ros_prefix() + cmd
    log_f = open(log_path, "w")
    return subprocess.Popen(
        ["bash", "-c", full],
        stdout=log_f, stderr=subprocess.STDOUT,
        cwd=FLEET_WS, preexec_fn=os.setsid,
    )


def kill_proc_group(proc: Optional[subprocess.Popen]) -> None:
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
    """Retorna "ready", "fail" ou "timeout". ready_all: todas as substrings
    precisam aparecer (em qualquer ordem) pro status "ready"."""
    deadline = time.monotonic() + timeout_s
    pending = set(ready_all)
    while time.monotonic() < deadline:
        if log_path.exists():
            text = log_path.read_text(errors="ignore")
            for pat in fail_any:
                if pat in text:
                    return "fail"
            pending = {p for p in ready_all if p not in text}
            if not pending:
                return "ready"
        time.sleep(1)
    return "timeout"


def boot_stack(world: str, timeout_s: float, max_retries: int, run_dir: Path, replicate_id: int) -> tuple:
    """Retorna (sim_proc, fleet_proc, retries_usados) ou (None, None, retries_usados)
    se esgotar as tentativas sem ficar pronto."""
    for attempt in range(max_retries + 1):
        kill_all_sim_processes()
        # replicate_id no nome do log -- sem isso, a replica 2 sobrescreve o
        # log da replica 1 (mesmo "attempt0"), perdendo o diagnostico de
        # qual replica especifica teve problema (achado ao vivo nesta sessao).
        sim_log = run_dir / f"r{replicate_id:02d}_sim_attempt{attempt}.log"
        fleet_log = run_dir / f"r{replicate_id:02d}_fleet_attempt{attempt}.log"
        sim_cmd = f"ros2 launch fleet_orchestrator turtlebot4_sim.launch.py world:={world} headless:=True"
        sim_proc = launch_bash(sim_cmd, sim_log)
        status = wait_for_log(sim_log, (SIM_READY,), SIM_FAIL, timeout_s)
        if status != "ready":
            print(f"  [tentativa {attempt}] sim bringup = {status}, matando e tentando de novo")
            kill_proc_group(sim_proc)
            continue

        fleet_cmd = "ros2 launch fleet_orchestrator fleet.launch.py single_robot_sim:=true"
        fleet_proc = launch_bash(fleet_cmd, fleet_log)
        status2 = wait_for_log(fleet_log, FLEET_READY, (), 20.0)
        if status2 != "ready":
            print(f"  [tentativa {attempt}] fleet bringup = {status2}, matando e tentando de novo")
            kill_proc_group(sim_proc)
            kill_proc_group(fleet_proc)
            continue

        return sim_proc, fleet_proc, attempt

    return None, None, max_retries + 1


def record_replica(
    route: str, topics: list[str], protocol_id: str,
    replicate_id: int, replicate_total: int, export_path: Path,
) -> bool:
    cmd = [
        "python3", "scripts/experiment_repeatability.py", "replay",
        "--single-robot", "--route", route,
        "--topics", *topics,
        "--protocol-id", protocol_id,
        "--replicate-id", str(replicate_id),
        "--replicate-total", str(replicate_total),
        "--export", str(export_path),
    ]
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    shell_cmd = _ros_prefix() + " ".join(shlex.quote(c) for c in cmd)
    result = subprocess.run(
        ["bash", "-c", shell_cmd],
        cwd=FLEET_WS, capture_output=True, text=True, env=env,
    )
    (export_path.parent / f"replay_r{replicate_id:02d}.log").write_text(result.stdout + result.stderr)
    return result.returncode == 0 and "Resumo: sem falhas" in result.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--route", required=True)
    ap.add_argument("--world", default="warehouse")
    ap.add_argument("--repeat", type=int, default=10)
    ap.add_argument("--protocol-id", required=True)
    ap.add_argument("--topics", nargs="+", default=["odom", "pose", "ground_truth_pose_clean", "scan", "imu"])
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--boot-timeout", type=float, default=40.0, help="Segundos pra esperar 'Managed nodes are active' antes de desistir dessa tentativa")
    ap.add_argument("--max-retries", type=int, default=3, help="Tentativas extras de boot por réplica antes de marcar como falha")
    args = ap.parse_args()

    run_dir = FLEET_WS / args.output_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "protocol_id": args.protocol_id,
        "route": args.route,
        "world": args.world,
        "repeat": args.repeat,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "replicas": [],
    }

    for rid in range(1, args.repeat + 1):
        print(f"=== Réplica {rid}/{args.repeat} ===")
        t0 = time.monotonic()
        sim_proc, fleet_proc, retries = boot_stack(args.world, args.boot_timeout, args.max_retries, run_dir, rid)
        boot_elapsed = time.monotonic() - t0

        entry = {
            "replicate_id": rid, "retries_used": retries,
            "boot_elapsed_sec": round(boot_elapsed, 1),
            "boot_success": sim_proc is not None,
            "record_success": False,
            "export_path": None,
        }

        if sim_proc is None:
            print(f"  FALHA: esgotou {args.max_retries} tentativas de boot, pulando esta réplica")
            manifest["replicas"].append(entry)
            kill_all_sim_processes()
            continue

        print(f"  boot ok (retries={retries}, {boot_elapsed:.1f}s) -- gravando réplica {rid}")
        export_path = run_dir / f"replay_r{rid:02d}.json"
        ok = record_replica(args.route, args.topics, args.protocol_id, rid, args.repeat, export_path)
        entry["record_success"] = ok
        entry["export_path"] = str(export_path)
        if not ok:
            print(f"  [AVISO] gravação da réplica {rid} não terminou 'sem falhas' -- ver {export_path.parent}/replay_r{rid:02d}.log")

        kill_proc_group(sim_proc)
        kill_proc_group(fleet_proc)
        kill_all_sim_processes()
        manifest["replicas"].append(entry)

    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    n_ok = sum(1 for r in manifest["replicas"] if r["boot_success"] and r["record_success"])
    n_retry = sum(r["retries_used"] for r in manifest["replicas"])
    manifest["summary"] = {
        "replicas_ok": n_ok, "replicas_total": args.repeat,
        "success_rate": round(n_ok / args.repeat, 3) if args.repeat else None,
        "total_retries_used": n_retry,
    }
    manifest_path = run_dir / "campaign_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    print(f"\n=== Campanha concluída: {n_ok}/{args.repeat} réplicas ok, {n_retry} retries no total ===")
    print(f"Manifesto: {manifest_path}")
    return 0 if n_ok == args.repeat else 1


if __name__ == "__main__":
    sys.exit(main())
