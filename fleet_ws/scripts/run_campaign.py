#!/usr/bin/env python3
"""Run a repeatability campaign and collect analysis artifacts.

Expected usage from fleet_ws with the ROS workspace sourced:

  source /opt/ros/jazzy/setup.bash && source install/setup.bash
  python3 scripts/run_campaign.py --single-robot --route percurso1 \
    --points "0.5,0,0;1.0,0,0;1.5,0.5,0" --replays 3
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROS_WS = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROS_WS / "scripts"


def _timestamp_id() -> str:
    return datetime.now(timezone.utc).strftime("campaign_%Y%m%d_%H%M%S")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _bag_path_from_export(export_data: dict[str, Any]) -> str:
    raw = export_data.get("rosbag_path") or ""
    if not raw:
        return ""
    path = Path(raw)
    if path.is_absolute():
        return str(path)
    return str((ROS_WS / path).resolve())


def _robot_args(args: argparse.Namespace) -> list[str]:
    if args.single_robot:
        return ["--single-robot"]
    return ["--robot", args.robot]


def _parse_pose_csv(raw: str) -> tuple[float, float, float]:
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 3:
        raise ValueError("pose deve estar no formato x,y,yaw")
    return float(parts[0]), float(parts[1]), float(parts[2])


def _gazebo_set_pose(
    *,
    world: str,
    model: str,
    pose: str,
    settle_sec: float,
) -> bool:
    x, y, yaw = _parse_pose_csv(pose)
    z = math.sin(yaw / 2.0)
    w = math.cos(yaw / 2.0)
    req = (
        f'name: "{model}" '
        f'position {{ x: {x} y: {y} z: 0.0 }} '
        f'orientation {{ x: 0.0 y: 0.0 z: {z} w: {w} }}'
    )
    command = [
        "gz",
        "service",
        "-s",
        f"/world/{world}/set_pose/blocking",
        "--reqtype",
        "gz.msgs.Pose",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        "3000",
        "--req",
        req,
    ]
    proc = subprocess.run(command, cwd=ROS_WS, capture_output=True, text=True)
    ok = proc.returncode == 0 and "data: true" in proc.stdout
    if ok and settle_sec > 0:
        time.sleep(settle_sec)
    if not ok:
        print(proc.stdout, end="")
        print(proc.stderr, end="", file=sys.stderr)
    return ok


def _common_experiment_args(args: argparse.Namespace) -> list[str]:
    out = [
        "--route", args.route,
        "--topics", *args.topics,
        "--wait-goal", str(args.wait_goal),
        "--protocol-id", args.protocol_id,
    ]
    if args.condition:
        out += ["--condition", "; ".join(args.condition)]
    if args.notes:
        out += ["--notes", args.notes]
    if args.skip_collection:
        out.append("--skip-collection")
    if args.no_use_sim_time:
        out.append("--no-use-sim-time")
    if args.require_motion:
        out += [
            "--require-motion",
            "--motion-min-dist", str(args.motion_min_dist),
            "--motion-timeout", str(args.motion_timeout),
        ]
    return out


def _run_step(label: str, command: list[str], *, continue_on_failure: bool) -> int:
    print(f"\n=== {label} ===")
    print("[CMD] " + " ".join(command))
    proc = subprocess.run(command, cwd=ROS_WS)
    if proc.returncode != 0:
        print(f"[FALHOU] {label}: exit {proc.returncode}", file=sys.stderr)
        if not continue_on_failure:
            return proc.returncode
    return proc.returncode


def _write_manifest(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Roda baseline + replays repetidos e consolida os resultados em uma pasta.",
    )
    parser.add_argument("--route", default="percurso1_tb1", help="Nome da rota YAML, sem .yaml")
    parser.add_argument(
        "--points",
        default="0.5,0,0;1.0,0,0;1.5,0.5,0;2.0,0.5,0",
        help="Waypoints x,y,yaw separados por ';' usados no baseline record",
    )
    parser.add_argument("--robot", default="tb1", help="robot_id para modo multi-robo")
    parser.add_argument("--single-robot", action="store_true", help="Usa robot_id vazio, pastas default")
    parser.add_argument("--replays", type=int, default=3, help="Quantidade de replays apos o baseline")
    parser.add_argument("--topics", nargs="+", default=["scan", "odom", "imu", "pose"])
    parser.add_argument("--output-dir", default="", help="Pasta da campanha; default runs/<protocol-id>")
    parser.add_argument("--protocol-id", default="", help="Identificador da campanha")
    parser.add_argument("--condition", action="append", default=[], help="Condição registrada no export JSON")
    parser.add_argument("--notes", default="", help="Notas registradas nos exports")
    parser.add_argument("--skip-record", action="store_true", help="Nao grava baseline; usa rota existente")
    parser.add_argument("--skip-analysis", action="store_true", help="Nao chama analyze_runs.py ao final")
    parser.add_argument("--skip-collection", action="store_true", help="Roda sem gravar rosbag2")
    parser.add_argument("--continue-on-failure", action="store_true", help="Continua mesmo se uma run falhar")
    parser.add_argument("--wait-goal", type=float, default=300.0)
    parser.add_argument("--initial-pose", default=None, metavar="x,y,yaw", help="Pose inicial antes do baseline")
    parser.add_argument("--return-to-start", default=None, metavar="x,y,yaw", help="Pose de retorno antes de cada replay")
    parser.add_argument("--gazebo-reset-pose", default=None, metavar="x,y,yaw", help="Teleporta o modelo Gazebo para esta pose antes de cada replay")
    parser.add_argument("--gazebo-world", default="warehouse", help="Nome do mundo Gazebo usado por --gazebo-reset-pose")
    parser.add_argument("--gazebo-model", default="turtlebot4", help="Nome do modelo Gazebo usado por --gazebo-reset-pose")
    parser.add_argument("--gazebo-reset-settle-sec", type=float, default=2.0, help="Espera apos reset Gazebo antes de iniciar replay")
    parser.add_argument("--no-use-sim-time", action="store_true")
    parser.add_argument("--require-motion", action="store_true")
    parser.add_argument("--motion-min-dist", type=float, default=0.10)
    parser.add_argument("--motion-timeout", type=float, default=10.0)
    parser.add_argument("--trajectory-topic", choices=("auto", "amcl_pose", "odom"), default="auto")
    parser.add_argument("--resample-mode", choices=("time", "index"), default="time")
    parser.add_argument("--resample-samples", type=int, default=100)
    parser.add_argument("--no-plot", action="store_true", help="Repassa --no-plot para analyze_runs.py")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.replays < 1:
        parser.error("--replays deve ser >= 1")
    if args.resample_samples < 2:
        parser.error("--resample-samples deve ser >= 2")

    args.protocol_id = args.protocol_id or _timestamp_id()
    output_dir = Path(args.output_dir) if args.output_dir else ROS_WS / "runs" / args.protocol_id
    if not output_dir.is_absolute():
        output_dir = (ROS_WS / output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "protocol_id": args.protocol_id,
        "route": args.route,
        "robot": "" if args.single_robot else args.robot,
        "single_robot": args.single_robot,
        "topics": args.topics,
        "conditions": args.condition,
        "notes": args.notes,
        "gazebo_reset": {
            "pose": args.gazebo_reset_pose,
            "world": args.gazebo_world,
            "model": args.gazebo_model,
            "settle_sec": args.gazebo_reset_settle_sec,
        } if args.gazebo_reset_pose else None,
        "output_dir": str(output_dir),
        "runs": [],
        "analysis": None,
    }
    manifest_path = output_dir / "campaign_manifest.json"

    experiment = [sys.executable, str(SCRIPTS_DIR / "experiment_repeatability.py")]
    common = _robot_args(args) + _common_experiment_args(args)

    if not args.skip_record:
        export = output_dir / "baseline_record.json"
        cmd = experiment + ["record", *common, "--points", args.points, "--export", str(export)]
        if args.initial_pose:
            cmd += ["--initial-pose", args.initial_pose]
        code = _run_step("baseline record", cmd, continue_on_failure=args.continue_on_failure)
        data = _load_json(export)
        manifest["runs"].append({
            "label": "baseline",
            "phase": "record",
            "exit_code": code,
            "export": str(export),
            "bag_path": _bag_path_from_export(data),
            "success": data.get("success", code == 0),
        })
        _write_manifest(manifest_path, manifest)
        if code != 0 and not args.continue_on_failure:
            return code

    for index in range(1, args.replays + 1):
        label = f"replay_{index:02d}"
        export = output_dir / f"{label}.json"
        if args.gazebo_reset_pose:
            print(f"\n=== {label}: gazebo reset ===")
            print(
                "[TRACE] set_pose/blocking "
                f"world={args.gazebo_world!r} model={args.gazebo_model!r} pose={args.gazebo_reset_pose!r}"
            )
            try:
                reset_ok = _gazebo_set_pose(
                    world=args.gazebo_world,
                    model=args.gazebo_model,
                    pose=args.gazebo_reset_pose,
                    settle_sec=args.gazebo_reset_settle_sec,
                )
            except ValueError as exc:
                print(f"[FALHOU] {label}: {exc}", file=sys.stderr)
                return 2
            print(("[OK]" if reset_ok else "[FALHOU]") + " gazebo reset")
            if not reset_ok and not args.continue_on_failure:
                return 1
        cmd = experiment + [
            "replay", *common,
            "--replicate-id", str(index),
            "--replicate-total", str(args.replays),
            "--export", str(export),
        ]
        if args.initial_pose:
            cmd += ["--initial-pose", args.initial_pose]
        if args.return_to_start:
            cmd += ["--return-to-start", args.return_to_start]
        code = _run_step(label, cmd, continue_on_failure=args.continue_on_failure)
        data = _load_json(export)
        manifest["runs"].append({
            "label": label,
            "phase": "replay",
            "exit_code": code,
            "export": str(export),
            "bag_path": _bag_path_from_export(data),
            "success": data.get("success", code == 0),
        })
        _write_manifest(manifest_path, manifest)
        if code != 0 and not args.continue_on_failure:
            return code

    bag_runs = [run for run in manifest["runs"] if run.get("bag_path")]
    if not args.skip_analysis and bag_runs:
        analysis_dir = output_dir / "analysis"
        labels = [run["label"] for run in bag_runs]
        bags = [run["bag_path"] for run in bag_runs]
        cmd = [
            sys.executable, str(SCRIPTS_DIR / "analyze_runs.py"),
            *bags,
            "--output-dir", str(analysis_dir),
            "--labels", *labels,
            "--trajectory-topic", args.trajectory_topic,
            "--resample-mode", args.resample_mode,
            "--resample-samples", str(args.resample_samples),
        ]
        if args.no_plot:
            cmd.append("--no-plot")
        code = _run_step("analysis", cmd, continue_on_failure=args.continue_on_failure)
        manifest["analysis"] = {
            "exit_code": code,
            "output_dir": str(analysis_dir),
            "summary": str(analysis_dir / "summary.json"),
            "labels": labels,
            "bags": bags,
        }
        _write_manifest(manifest_path, manifest)
        if code != 0 and not args.continue_on_failure:
            return code
    elif not args.skip_analysis:
        print("[INFO] Nenhum rosbag_path encontrado nos exports; análise não executada.")

    print(f"\n[OK] Campanha finalizada. Manifesto: {manifest_path}")
    if manifest["analysis"]:
        print(f"[OK] Resultados: {manifest['analysis']['output_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
