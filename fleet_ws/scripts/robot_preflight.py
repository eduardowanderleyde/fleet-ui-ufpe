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

Suporta ROBOT_NAMESPACE para TurtleBot4 com tópicos prefixados (ex.: /tb1/scan).
Se ROBOT_IP estiver definido e CYCLONEDDS_URI apontar para um XML gerado,
mostra que está usando peers unicast (multicast bloqueado na rede).

Uso (dentro da imagem do fleet-ui):
  make robot-check [ROBOT_DOMAIN=0]
  make robot-check ROBOT_NAMESPACE=tb1 ROBOT_IP=192.168.50.11
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


def _get_namespace() -> str:
    """Retorna o namespace do robô (ROBOT_NAMESPACE), sem barras."""
    return os.environ.get("ROBOT_NAMESPACE", "").strip().strip("/")


def _topic_with_ns(topic: str, namespace: str = "") -> str:
    """Adiciona namespace ao tópico se definido."""
    ns = namespace or _get_namespace()
    base = topic.lstrip("/")
    if ns:
        return f"/{ns}/{base}"
    return f"/{base}"


def _expected_topics_with_ns(namespace: str = "") -> Dict[str, str]:
    """Retorna EXPECTED_TOPICS com namespace aplicado."""
    ns = namespace or _get_namespace()
    base = {
        "scan": "sensor_msgs/msg/LaserScan",
        "odom": "nav_msgs/msg/Odometry",
        "tf": "tf2_msgs/msg/TFMessage",
        "tf_static": "tf2_msgs/msg/TFMessage",
    }
    return {_topic_with_ns(t, ns): typ for t, typ in base.items()}


# Tópicos que o Nav2 do fleet-ui consome do robô, com o tipo esperado.
# Nota: agora gerado dinamicamente por _expected_topics_with_ns() para suportar namespace.
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


def evaluate_types(advertised: Dict[str, List[str]], namespace: str = "") -> List[Check]:
    expected_topics = _expected_topics_with_ns(namespace)
    checks = []
    for topic, expected in expected_topics.items():
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


def robot_nodes(names, ignore_nodes=()) -> List[str]:
    """Nós que podem ser do robô: tira este script, os nós que o chamador
    disse serem do PC e os auxiliares do `ros2` CLI (_ros2cli_daemon_*,
    _ros2cli_requester_*), que o backend da tela cria ao chamar serviços."""
    ignored = {"fleet_robot_preflight", *ignore_nodes}
    return sorted(n for n in names if n not in ignored and not n.startswith("_ros2cli"))


def run(listen_s: float, discovery_s: float, ignore_nodes: tuple = (), namespace: str = "") -> List[Check]:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.time import Time
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import LaserScan
    import tf2_ros

    ns = namespace or _get_namespace()
    
    checks = [
        Check("domínio ROS", True, os.environ.get("ROS_DOMAIN_ID", "0")),
        evaluate_rmw(os.environ.get("RMW_IMPLEMENTATION", "")),
    ]
    
    if ns:
        checks.append(Check("namespace do robô", True, f"/{ns} (tópicos: /{ns}/scan, /{ns}/odom, ...)"))
    else:
        checks.append(Check("namespace do robô", True, "(sem namespace — tópicos globais)"))

    rclpy.init()
    node = Node("fleet_robot_preflight")
    
    scan_topic = _topic_with_ns("scan", ns)
    odom_topic = _topic_with_ns("odom", ns)
    tf_topic = _topic_with_ns("tf", ns)
    tf_static_topic = _topic_with_ns("tf_static", ns)
    
    stats = {scan_topic: TopicStats(), odom_topic: TopicStats()}

    def _cb(topic):
        def inner(msg):
            now = time.time()
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            stats[topic].stamps_wall.append(now)
            if stamp > 0:
                stats[topic].skews.append(now - stamp)
        return inner

    node.create_subscription(LaserScan, scan_topic, _cb(scan_topic), qos_profile_sensor_data)
    node.create_subscription(Odometry, odom_topic, _cb(odom_topic), qos_profile_sensor_data)
    
    from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy, ReliabilityPolicy
    from tf2_msgs.msg import TFMessage
    
    tf_buffer = tf2_ros.Buffer()
    
    def _tf_cb(msg):
        for t in msg.transforms:
            tf_buffer.set_transform(t, "preflight")
    
    def _tf_static_cb(msg):
        for t in msg.transforms:
            tf_buffer.set_transform_static(t, "preflight")
    
    node.create_subscription(
        TFMessage, tf_topic, _tf_cb,
        QoSProfile(depth=100, durability=DurabilityPolicy.VOLATILE, history=HistoryPolicy.KEEP_LAST),
    )
    node.create_subscription(
        TFMessage, tf_static_topic, _tf_static_cb,
        QoSProfile(depth=100, durability=DurabilityPolicy.TRANSIENT_LOCAL, history=HistoryPolicy.KEEP_LAST),
    )

    deadline = time.time() + discovery_s
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    # Só tópicos com quem publique: rodando ao lado do backend da tela, as
    # assinaturas dele (/tf, /amcl_pose, status das actions) também aparecem
    # na lista e dariam OK sem robô nenhum na rede.
    advertised = {name: types for name, types in node.get_topic_names_and_types()
                  if node.count_publishers(name) > 0}
    nodes = robot_nodes((n for n, _ in node.get_node_names_and_namespaces()), ignore_nodes)
    
    # Dica quando só o próprio nó do fleet-ui aparece
    only_self = len(nodes) == 0 or (len(nodes) == 1 and "fleet" in nodes[0].lower())
    if only_self:
        detail = ("nenhum nó do robô descoberto — possíveis causas:\n"
                  "  • Humble (robô) ↔ Jazzy (PC): versões incompatíveis do DDS\n"
                  "  • namespace errado: robô publica em /tb1/* mas ROBOT_NAMESPACE não está definido\n"
                  "  • domínio ROS diferente (ROBOT_DOMAIN)\n"
                  "  • robô desligado ou em outra rede\n"
                  "  • multicast bloqueado (raro; use ROBOT_IP para unicast)")
        checks.append(Check("nós descobertos", False, detail))
    else:
        checks.append(Check("nós descobertos", True,
                            f"{len(nodes)}: {', '.join(nodes[:8])}{' …' if len(nodes) > 8 else ''}"))
    
    checks += evaluate_types(advertised, ns)
    checks.append(evaluate_nav2(advertised))

    deadline = time.time() + listen_s
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)

    for topic in (scan_topic, odom_topic):
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
    ap.add_argument("--ignore-nodes", nargs="*", default=[],
                    help="nós deste PC que não contam como robô (ex.: o do backend da tela)")
    ap.add_argument("--namespace", default="",
                    help="namespace do robô (ex.: tb1 para /tb1/scan); usa ROBOT_NAMESPACE se omitido")
    args = ap.parse_args()
    
    ns = args.namespace or _get_namespace()
    domain = os.environ.get('ROS_DOMAIN_ID', '0')
    cyclone_uri = os.environ.get("CYCLONEDDS_URI", "")
    robot_ip = os.environ.get("ROBOT_IP", "")
    
    print(f"Checagem pré-voo (só leitura) — domínio {domain}")
    if ns:
        print(f"  namespace: /{ns} (tópicos: /{ns}/scan, /{ns}/odom, ...)")
    if cyclone_uri:
        print(f"  CYCLONEDDS_URI: {cyclone_uri[:60]}...")
    if robot_ip:
        print(f"  ROBOT_IP: {robot_ip}")
    print()
    
    print("⚠️  AVISO: Humble (robô) ↔ Jazzy (PC) não é oficialmente compatível.")
    print("   Se a checagem falhar, considere usar a imagem Humble no PC.")
    print("   Ver docs/ufpe/robo_real.md para fallback e checklist.\n")
    
    return report(run(args.listen_sec, args.discovery_sec, tuple(args.ignore_nodes), ns))


if __name__ == "__main__":
    sys.exit(main())
