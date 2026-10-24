#!/usr/bin/env python3
"""Checagem pré-voo, só de leitura, entre o fleet-ui e um TurtleBot4 real.

Não publica nada (nem /cmd_vel): só escuta. Confere o que já deu problema no
setup do CIn-UFPE (docs/troubleshoot.md do repositório mobile-robotics):
middleware diferente entre PC e robô, árvore TF odom -> base_link quebrada e
relógio dessincronizado entre PC, Raspberry Pi e Create3.

Também avisa se já existe um Nav2 no domínio: as actions do Nav2 mudaram entre
Humble e Jazzy (FollowWaypoints, NavigateToPose), então o fleet-ui (Jazzy) tem
de rodar o próprio Nav2 e trocar com o robô (Humble) só sensores e /cmd_vel,
cujas mensagens são iguais nas duas versões.

Uso (dentro da imagem do fleet-ui):  make robot-check [ROBOT_DOMAIN=0]
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Tópicos que o Nav2 do fleet-ui consome do robô, com o tipo esperado.
EXPECTED_TOPICS = {
    "/scan": "sensor_msgs/msg/LaserScan",
    "/odom": "nav_msgs/msg/Odometry",
    "/tf": "tf2_msgs/msg/TFMessage",
    "/tf_static": "tf2_msgs/msg/TFMessage",
}
# Taxas mínimas aceitáveis (Hz) para quem tem cabeçalho com horário.
MIN_RATE_HZ = {"/scan": 5.0, "/odom": 10.0}
# Acima disso o TF começa a descartar dados "do passado" (erro 2 do guia delas).
MAX_CLOCK_SKEW_S = 0.5
NAV2_ACTIONS = ("/navigate_to_pose", "/follow_waypoints")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    warn_only: bool = False


@dataclass
class TopicStats:
    stamps_wall: List[float] = field(default_factory=list)
    skews: List[float] = field(default_factory=list)

    def rate_hz(self) -> Optional[float]:
        if len(self.stamps_wall) < 2:
            return None
        span = self.stamps_wall[-1] - self.stamps_wall[0]
        return (len(self.stamps_wall) - 1) / span if span > 0 else None

    def median_skew(self) -> Optional[float]:
        return statistics.median(self.skews) if self.skews else None


def evaluate_rmw(rmw: str) -> Check:
    if rmw == "rmw_cyclonedds_cpp":
        return Check("middleware", True, rmw)
    return Check("middleware", False,
                 f"{rmw or '(padrão: Fast DDS)'} — o TurtleBot4 do CIn usa rmw_cyclonedds_cpp")


def evaluate_rate(topic: str, rate: Optional[float]) -> Check:
    minimum = MIN_RATE_HZ.get(topic)
    if rate is None:
        return Check(f"taxa {topic}", False, "nenhuma mensagem recebida")
    if minimum is not None and rate < minimum:
        return Check(f"taxa {topic}", False, f"{rate:.1f} Hz (mínimo {minimum:.0f} Hz)")
    return Check(f"taxa {topic}", True, f"{rate:.1f} Hz")


def evaluate_skew(topic: str, skew: Optional[float]) -> Check:
    if skew is None:
        return Check(f"relógio {topic}", False, "sem mensagens com horário")
    if abs(skew) > MAX_CLOCK_SKEW_S:
        return Check(f"relógio {topic}", False,
                     f"defasagem mediana {skew:+.2f} s (limite ±{MAX_CLOCK_SKEW_S} s); "
                     "sincronizar o relógio do robô com o PC")
    return Check(f"relógio {topic}", True, f"defasagem mediana {skew:+.3f} s")


def evaluate_types(advertised: Dict[str, List[str]]) -> List[Check]:
    checks = []
    for topic, expected in EXPECTED_TOPICS.items():
        types = advertised.get(topic)
        if not types:
            checks.append(Check(f"tópico {topic}", False, "não anunciado no domínio"))
        elif expected not in types:
            checks.append(Check(f"tópico {topic}", False, f"tipo {types}, esperado {expected}"))
        else:
            checks.append(Check(f"tópico {topic}", True, expected))
    return checks


def evaluate_nav2(advertised: Dict[str, List[str]]) -> Check:
    found = [a for a in NAV2_ACTIONS if f"{a}/_action/status" in advertised]
    if found:
        return Check("Nav2 já rodando", False,
                     f"{', '.join(found)} no domínio. Se for o Nav2 Humble, ele não conversa com o "
                     "fleet-ui (Jazzy): desligar antes de subir o do fleet-ui", warn_only=True)
    return Check("Nav2 já rodando", True, "nenhum (o fleet-ui sobe o próprio)")


def run(listen_s: float, discovery_s: float) -> List[Check]:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.time import Time
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import LaserScan
    import tf2_ros

    checks = [
        Check("domínio ROS", True, os.environ.get("ROS_DOMAIN_ID", "0")),
        evaluate_rmw(os.environ.get("RMW_IMPLEMENTATION", "")),
    ]

    rclpy.init()
    node = Node("fleet_robot_preflight")
    stats = {"/scan": TopicStats(), "/odom": TopicStats()}

    def _cb(topic):
        def inner(msg):
            now = time.time()
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            stats[topic].stamps_wall.append(now)
            if stamp > 0:
                stats[topic].skews.append(now - stamp)
        return inner

    node.create_subscription(LaserScan, "/scan", _cb("/scan"), qos_profile_sensor_data)
    node.create_subscription(Odometry, "/odom", _cb("/odom"), qos_profile_sensor_data)
    tf_buffer = tf2_ros.Buffer()
    tf2_ros.TransformListener(tf_buffer, node)

    deadline = time.time() + discovery_s
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    advertised = {name: types for name, types in node.get_topic_names_and_types()}
    nodes = sorted(n for n, _ in node.get_node_names_and_namespaces() if n != "fleet_robot_preflight")
    checks.append(Check("nós descobertos", bool(nodes),
                        f"{len(nodes)}: {', '.join(nodes[:8])}{' …' if len(nodes) > 8 else ''}"
                        if nodes else "nenhum — conferir rede, domínio e middleware"))
    checks += evaluate_types(advertised)
    checks.append(evaluate_nav2(advertised))

    deadline = time.time() + listen_s
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)

    for topic in ("/scan", "/odom"):
        checks.append(evaluate_rate(topic, stats[topic].rate_hz()))
        checks.append(evaluate_skew(topic, stats[topic].median_skew()))

    try:
        tf_buffer.lookup_transform("odom", "base_link", Time())
        checks.append(Check("TF odom → base_link", True, "disponível"))
    except Exception as exc:  # tf2 levanta tipos diferentes por versão
        checks.append(Check("TF odom → base_link", False, f"indisponível ({type(exc).__name__})"))

    node.destroy_node()
    rclpy.shutdown()
    return checks


def report(checks: List[Check]) -> int:
    width = max(len(c.name) for c in checks)
    failed = 0
    for c in checks:
        mark = "OK " if c.ok else ("AVISO" if c.warn_only else "FALHA")
        failed += 0 if c.ok or c.warn_only else 1
        print(f"  [{mark:5}] {c.name:<{width}}  {c.detail}")
    print()
    print("Tudo certo: pode subir o fleet-ui contra o robô." if not failed
          else f"{failed} item(ns) com falha: resolver antes de mover o robô.")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--discovery-sec", type=float, default=5.0, help="espera pela descoberta DDS")
    ap.add_argument("--listen-sec", type=float, default=5.0, help="janela para medir taxa e relógio")
    args = ap.parse_args()
    print(f"Checagem pré-voo (só leitura) — domínio {os.environ.get('ROS_DOMAIN_ID', '0')}\n")
    return report(run(args.listen_sec, args.discovery_sec))


if __name__ == "__main__":
    sys.exit(main())
