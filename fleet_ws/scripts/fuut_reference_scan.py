#!/usr/bin/env python3
"""
Grava um scan de referência do LiDAR do robô FUUT, parado, antes do MUUT
entrar em cena — usado por `fuut_detection.detect_obstacle` como baseline
do ambiente vazio (ver design.md do change `fuut-pilot-experiment`).

Uso: python3 fuut_reference_scan.py --robot tb2 --out
     fleet_ws/runs/<run_id>/fuut_reference.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan


class _ReferenceScanNode(Node):
    def __init__(self, robot: str) -> None:
        super().__init__("fuut_reference_scan")
        self.scan: LaserScan | None = None
        topic = f"/{robot}/scan" if robot else "/scan"
        self.create_subscription(LaserScan, topic, self._cb, qos_profile_sensor_data)

    def _cb(self, msg: LaserScan) -> None:
        self.scan = msg


def capture_reference_scan(robot: str, timeout_sec: float = 10.0) -> dict:
    """Espera um scan do robô FUUT parado e devolve como dict serializável.
    Levanta TimeoutError se nenhum scan chegar dentro de timeout_sec —
    sintoma mais provável: robô errado, namespace errado, ou FUUT não
    publicando /scan (Nav2 ativo nele por engano bloquearia o papel)."""
    node = _ReferenceScanNode(robot)
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    try:
        deadline = node.get_clock().now().nanoseconds / 1e9 + timeout_sec
        while node.scan is None:
            executor.spin_once(timeout_sec=0.1)
            if node.get_clock().now().nanoseconds / 1e9 > deadline:
                raise TimeoutError(
                    f"nenhum /scan recebido de '{robot}' em {timeout_sec}s — "
                    "confirme que o FUUT está publicando sensores (sem Nav2 ativo)"
                )
        scan = node.scan
        return {
            "ranges": list(scan.ranges),
            "angle_min": scan.angle_min,
            "angle_increment": scan.angle_increment,
            "range_max": scan.range_max,
            "stamp_sec": scan.header.stamp.sec + scan.header.stamp.nanosec / 1e9,
        }
    finally:
        node.destroy_node()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robot", default="tb2", help="namespace do robô FUUT (vazio = sem namespace)")
    parser.add_argument("--out", required=True, help="caminho de saída do JSON")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    rclpy.init()
    try:
        data = capture_reference_scan(args.robot, args.timeout)
    except TimeoutError as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    finally:
        rclpy.shutdown()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data))
    print(f"scan de referência salvo: {out_path} ({len(data['ranges'])} pontos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
