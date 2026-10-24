#!/usr/bin/env python3
"""Run repeatability replays by relaunching the simulator for every run.

This is slower than `run_campaign.py`, but gives each replay a fresh Gazebo,
Nav2, collector, and odometry state.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROS_WS = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROS_WS / "scripts"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _bag_path_from_export(export_data: dict[str, Any]) -> str:
    raw = export_data.get("rosbag_path") or ""
    if not raw:
        return ""
    path = Path(raw)
    return str(path if path.is_absolute() else (ROS_WS / path).resolve())


def _parse_pose(raw: str) -> tuple[float, float, float]:
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 3:
        raise ValueError("pose deve estar no formato x,y,yaw")
    return float(parts[0]), float(parts[1]), float(parts[2])


def _run(command: list[str], *, timeout: float | None = None, check: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=ROS_WS,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=check,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "timeout",
        )


def _start(label: str, command: list[str], log_dir: Path) -> subprocess.Popen[str]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{label}.log"
    handle = log_path.open("w", encoding="utf-8")
    print(f"[TRACE] start {label}: {' '.join(command)}")
    return subprocess.Popen(
        command,
        cwd=ROS_WS,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def _stop(processes: list[subprocess.Popen[str]]) -> None:
    for proc in reversed(processes):
        if proc.poll() is not None:
            continue
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
    deadline = time.time() + 8.0
    for proc in reversed(processes):
        while proc.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _wait_until(label: str, predicate, timeout_sec: float, interval_sec: float = 1.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        if predicate():
            return True
        time.sleep(interval_sec)
    print(f"[FALHOU] timeout esperando {label}", file=sys.stderr)
    return False


def _has_turtlebot() -> bool:
    proc = _run(["gz", "model", "--list"], timeout=8.0)
    return proc.returncode == 0 and "turtlebot4" in proc.stdout


def _nav2_ready() -> bool:
    proc = _run(["ros2", "action", "list"], timeout=8.0)
    if proc.returncode != 0 or "/navigate_to_pose" not in proc.stdout:
        return False
    for node in ("/bt_navigator", "/controller_server", "/planner_server", "/waypoint_follower"):
        state = _run(
            ["ros2", "service", "call", f"{node}/get_state", "lifecycle_msgs/srv/GetState", "{}"],
            timeout=8.0,
        )
        if state.returncode != 0 or "label='active'" not in state.stdout:
            return False
    return True


def _fleet_ready() -> bool:
    proc = _run(["ros2", "service", "list"], timeout=8.0)
    return proc.returncode == 0 and "/play_route" in proc.stdout and "/enable_collection" in proc.stdout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Campanha controlada com relaunch completo por replay.")
    parser.add_argument("--route", required=True)
    parser.add_argument("--replays", type=int, default=10)
    parser.add_argument("--sim-initial-pose", default=None, metavar="x,y,yaw", help="Pose usada no launch da simulação em cada replay")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--protocol-id", required=True)
    parser.add_argument("--condition", action="append", default=[])
    parser.add_argument("--notes", default="")
    parser.add_argument("--wait-goal", type=float, default=90.0)
    parser.add_argument("--topics", nargs="+", default=["scan", "odom", "imu", "pose"])
    parser.add_argument("--trajectory-topic", choices=("auto", "amcl_pose", "odom"), default="odom")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (ROS_WS / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir = output_dir / "logs"
    manifest_path = output_dir / "campaign_manifest.json"

    manifest: dict[str, Any] = {
        "protocol_id": args.protocol_id,
        "route": args.route,
        "single_robot": True,
        "topics": args.topics,
        "conditions": args.condition,
        "notes": args.notes,
        "sim_initial_pose": args.sim_initial_pose,
        "control_method": "full_simulation_relaunch_per_replay",
        "output_dir": str(output_dir),
        "runs": [],
        "analysis": None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(manifest_path, manifest)

    for index in range(1, args.replays + 1):
        label = f"replay_{index:02d}"
        print(f"\n=== {label}: relaunch completo ===")
        processes: list[subprocess.Popen[str]] = []
        try:
            sim_cmd = ["ros2", "launch", "fleet_orchestrator", "turtlebot4_sim.launch.py"]
            if args.sim_initial_pose:
                try:
                    sx, sy, syaw = [str(v) for v in _parse_pose(args.sim_initial_pose)]
                except ValueError as exc:
                    print(f"[FALHOU] {label}: {exc}", file=sys.stderr)
                    return 2
                sim_cmd.extend([f"x_pose:={sx}", f"y_pose:={sy}", f"yaw:={syaw}"])
            processes.append(_start(f"{label}_sim", sim_cmd, log_dir))
            if not _wait_until("turtlebot4 no Gazebo", _has_turtlebot, 35.0):
                return 1
            if not _wait_until("Nav2 pronto", _nav2_ready, 55.0):
                return 1

            params = "src/fleet_orchestrator/config/single_robot_sim.yaml"
            processes.append(_start(
                f"{label}_orchestrator",
                ["ros2", "run", "fleet_orchestrator", "fleet_orchestrator", "--ros-args", "--params-file", params, "-p", "use_sim_time:=false"],
                log_dir,
            ))
            processes.append(_start(
                f"{label}_collector",
                ["ros2", "run", "fleet_data_collector", "sensor_collector", "--ros-args", "--params-file", params, "-p", "use_sim_time:=false"],
                log_dir,
            ))
            processes.append(_start(f"{label}_cmd_vel_relay", ["ros2", "run", "topic_tools", "relay", "/cmd_vel_smoothed", "/cmd_vel"], log_dir))
            if not _wait_until("serviços fleet", _fleet_ready, 15.0):
                return 1

            export = output_dir / f"{label}.json"
            cmd = [
                sys.executable,
                str(SCRIPTS_DIR / "experiment_repeatability.py"),
                "replay",
                "--single-robot",
                "--route",
                args.route,
                "--topics",
                *args.topics,
                "--wait-goal",
                str(args.wait_goal),
                "--protocol-id",
                args.protocol_id,
                "--condition",
                "; ".join(args.condition),
                "--notes",
                args.notes,
                "--no-use-sim-time",
                "--replicate-id",
                str(index),
                "--replicate-total",
                str(args.replays),
                "--export",
                str(export),
            ]
            print(f"[CMD] {' '.join(cmd)}")
            proc = subprocess.run(cmd, cwd=ROS_WS)
            data = _load_json(export)
            manifest["runs"].append({
                "label": label,
                "phase": "replay",
                "exit_code": proc.returncode,
                "export": str(export),
                "bag_path": _bag_path_from_export(data),
                "success": data.get("success", proc.returncode == 0),
            })
            _write_json(manifest_path, manifest)
            if proc.returncode != 0:
                return proc.returncode
        finally:
            _stop(processes)
            time.sleep(3.0)

    bag_runs = [run for run in manifest["runs"] if run.get("bag_path")]
    analysis_dir = output_dir / "analysis"
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "analyze_runs.py"),
        *[run["bag_path"] for run in bag_runs],
        "--output-dir",
        str(analysis_dir),
        "--labels",
        *[run["label"] for run in bag_runs],
        "--trajectory-topic",
        args.trajectory_topic,
    ]
    print("\n=== analysis ===")
    print(f"[CMD] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROS_WS)
    manifest["analysis"] = {
        "exit_code": proc.returncode,
        "output_dir": str(analysis_dir),
        "summary": str(analysis_dir / "summary.json"),
    }
    _write_json(manifest_path, manifest)
    if proc.returncode != 0:
        return proc.returncode

    print(f"\n[OK] Campanha finalizada. Manifesto: {manifest_path}")
    print(f"[OK] Resultados: {analysis_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
