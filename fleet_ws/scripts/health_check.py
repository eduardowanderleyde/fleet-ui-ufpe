#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
ROS_WS = ROOT / "fleet_ws"


def ok(label: str, detail: str = "") -> bool:
    print(f"[OK] {label}{': ' + detail if detail else ''}")
    return True


def fail(label: str, detail: str = "") -> bool:
    print(f"[FALHOU] {label}{': ' + detail if detail else ''}")
    return False


def run_shell(cmd: str, timeout: int = 5) -> tuple[int, str]:
    result = subprocess.run(
        ["bash", "-lc", cmd],
        cwd=ROS_WS,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def check_file(path: Path, label: str) -> bool:
    return ok(label, str(path)) if path.exists() else fail(label, f"não encontrado: {path}")


def check_command(command: str) -> bool:
    return ok(f"comando {command}", shutil.which(command) or "") if shutil.which(command) else fail(f"comando {command}", "não está no PATH")


def check_http(url: str, label: str, *, expect_json: bool = True) -> bool:
    try:
        with urlopen(url, timeout=2) as response:
            body = response.read().decode("utf-8", errors="replace")
        if expect_json:
            json.loads(body)
        return ok(label, url)
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        return fail(label, str(exc))


def check_ros_graph() -> list[bool]:
    if not shutil.which("ros2"):
        return [fail("ROS graph", "ros2 não está no PATH")]

    source_prefix = "source /opt/ros/${ROS_DISTRO:-jazzy}/setup.bash 2>/dev/null; "
    if (ROS_WS / "install" / "setup.bash").exists():
        source_prefix += "source install/setup.bash 2>/dev/null; "

    checks = []
    code, out = run_shell(source_prefix + "ros2 service list", timeout=6)
    if code != 0:
        checks.append(fail("ros2 service list", out.strip() or f"exit {code}"))
    else:
        for service in ("start_record", "stop_record", "play_route", "go_to_point", "list_routes"):
            checks.append(ok(f"serviço {service}") if service in out else fail(f"serviço {service}", "ausente"))

    code, out = run_shell(source_prefix + "ros2 topic list", timeout=6)
    if code != 0:
        checks.append(fail("ros2 topic list", out.strip() or f"exit {code}"))
    else:
        for topic in ("fleet/status", "map"):
            checks.append(ok(f"tópico {topic}") if topic in out else fail(f"tópico {topic}", "ausente"))

    code, out = run_shell(source_prefix + "ros2 action list", timeout=6)
    if code != 0:
        checks.append(fail("ros2 action list", out.strip() or f"exit {code}"))
    else:
        checks.append(ok("Nav2 action /navigate_to_pose") if "/navigate_to_pose" in out else fail("Nav2 action /navigate_to_pose", "ausente"))

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Healthcheck do Fleet UI.")
    parser.add_argument("--backend-url", default="http://localhost:8000", help="URL base do backend FastAPI")
    parser.add_argument("--frontend-url", default="http://localhost:5173", help="URL base do frontend Vite")
    parser.add_argument("--skip-ros", action="store_true", help="Não verifica tópicos/serviços ROS ativos")
    parser.add_argument("--skip-http", action="store_true", help="Não verifica frontend/backend HTTP")
    args = parser.parse_args()

    checks = [
        check_file(ROOT / "README.md", "README"),
        check_file(ROS_WS / "src" / "fleet_orchestrator", "pacote fleet_orchestrator"),
        check_file(ROS_WS / "src" / "fleet_data_collector", "pacote fleet_data_collector"),
        check_file(ROS_WS / "src" / "fleet_msgs", "pacote fleet_msgs"),
        check_command("python3"),
        check_command("npm"),
    ]

    if not args.skip_ros:
        checks.append(check_command("ros2"))

    if not args.skip_http:
        checks.append(check_http(f"{args.backend_url.rstrip('/')}/api/status", "backend /api/status"))
        checks.append(check_http(args.frontend_url, "frontend Vite", expect_json=False))

    if not args.skip_ros:
        checks.extend(check_ros_graph())

    failed = len([item for item in checks if not item])
    if failed:
        print(f"\nResumo: {failed} checagem(ns) falharam.")
        return 1
    print("\nResumo: ambiente saudável.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
