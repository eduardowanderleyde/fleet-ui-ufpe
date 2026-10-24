#!/usr/bin/env python3
"""Extensão rápida de run_dual_nav_simultaneous.py: depois que tb1 E tb2
ativam SIMULTANEAMENTE sob uma dada RMW, manda um `go_to_point` real pros
dois AO MESMO TEMPO (não só ativação) e observa por N segundos se
"jump back in time" aparece durante a navegação de verdade (não só no
bringup) -- checagem de que o RMW swap resolve a causa, não só mascara o
sintoma na janela de ativação.

Uso:
  python3 scripts/check_dual_nav_drive.py --rmw rmw_cyclonedds_cpp --output-dir runs/dual_nav_drive_cyclone
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_dual_nav_simultaneous import (  # noqa: E402
    FLEET_WS, boot_multi_sim, activate_both_simultaneously, kill_proc_group,
    kill_all_sim_processes, count_jumps, launch_bash, CYCLONEDDS_URI_FIX,
)


def call_go_to_point(ns: str, x: float, y: float, log_path: Path, extra_env: dict):
    req = f"{{robot_id: '{ns}', x: {x}, y: {y}, yaw: 0.0}}"
    cmd = f"ros2 service call /go_to_point fleet_msgs/srv/GoToPoint \"{req}\""
    return launch_bash(cmd, log_path, extra_env)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", default="warehouse")
    ap.add_argument("--rmw", default="")
    ap.add_argument("--cyclonedds-fix", action="store_true")
    ap.add_argument("--drive-watch-sec", type=float, default=25.0)
    ap.add_argument("--output-dir", required=True)
    args = ap.parse_args()

    extra_env = {}
    if args.rmw:
        extra_env["RMW_IMPLEMENTATION"] = args.rmw
    if args.cyclonedds_fix:
        extra_env["CYCLONEDDS_URI"] = CYCLONEDDS_URI_FIX

    run_dir = FLEET_WS / args.output_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    sim_proc = fleet_proc = None
    result = {"rmw": args.rmw or "(default)", "cyclonedds_fix": args.cyclonedds_fix}
    try:
        sim_proc, fleet_proc = boot_multi_sim(args.world, run_dir, 1, extra_env)
        print("sim pronta, ativando tb1+tb2 simultaneamente...")
        act = activate_both_simultaneously(run_dir, 1, 120.0, extra_env)
        result["activation"] = act
        print(f"ativação: tb1={act['status_tb1']} tb2={act['status_tb2']}")
        if not act["both_ready"]:
            result["drive_skipped"] = "ativação não completou nos dois"
        else:
            print("disparando go_to_point em tb1 E tb2 simultaneamente (serviço real)...")
            log_tb1 = run_dir / "drive_tb1.log"
            log_tb2 = run_dir / "drive_tb2.log"
            # alvos: tb1 (spawn ~0,0) anda 1.5m em x; tb2 (spawn ~0,2) anda 1.5m em x também
            p1 = call_go_to_point("tb1", 1.5, 0.0, log_tb1, extra_env)
            p2 = call_go_to_point("tb2", 1.5, 2.0, log_tb2, extra_env)

            # monitora os logs dos NÓS de nav (tb1/tb2 controller_server etc.) por jump-back-in-time
            # durante a janela de drive -- usa os MESMOS logs de ativação, que continuam sendo
            # escritos pelos processos de ros2 launch ainda vivos.
            log_nav_tb1 = run_dir / "r01_activate_tb1.log"
            log_nav_tb2 = run_dir / "r01_activate_tb2.log"
            jumps_before_tb1 = count_jumps(log_nav_tb1)
            jumps_before_tb2 = count_jumps(log_nav_tb2)

            deadline = time.monotonic() + args.drive_watch_sec
            while time.monotonic() < deadline:
                time.sleep(2)
            kill_proc_group(p1)
            kill_proc_group(p2)

            jumps_after_tb1 = count_jumps(log_nav_tb1)
            jumps_after_tb2 = count_jumps(log_nav_tb2)
            result["drive_check"] = {
                "watch_sec": args.drive_watch_sec,
                "jumps_during_drive_tb1": jumps_after_tb1 - jumps_before_tb1,
                "jumps_during_drive_tb2": jumps_after_tb2 - jumps_before_tb2,
                "go_to_point_tb1_log": str(log_tb1),
                "go_to_point_tb2_log": str(log_tb2),
            }
            result["go_to_point_tb1_response"] = log_tb1.read_text(errors="ignore")[-600:] if log_tb1.exists() else None
            result["go_to_point_tb2_response"] = log_tb2.read_text(errors="ignore")[-600:] if log_tb2.exists() else None
            print(f"jumps durante drive: tb1={result['drive_check']['jumps_during_drive_tb1']} "
                  f"tb2={result['drive_check']['jumps_during_drive_tb2']}")
    finally:
        kill_proc_group(fleet_proc)
        kill_proc_group(sim_proc)
        kill_all_sim_processes()
        subprocess.run(["pkill", "-9", "-f", "activate_robot_nav"], capture_output=True)

    out_path = run_dir / "drive_check_result.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nresultado salvo em {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
