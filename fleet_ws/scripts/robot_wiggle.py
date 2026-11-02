#!/usr/bin/env python3
"""Sinal de "conectado": o robô gira um pouquinho para um lado e volta.

Só rotação no lugar (linear = 0), devagar e curta: com os padrões, ~10° para
a esquerda e ~10° de volta, em 0,8 s. Publica /cmd_vel (Twist, sem horário,
como o TurtleBot4 no Humble espera) a 20 Hz, porque a base Create3 para
sozinha se os comandos param de chegar, e termina com alguns zeros.

Chamado pelo backend (robot_link.py) quando o painel "Robô real" conecta.
Uso manual:  python3 scripts/robot_wiggle.py [--speed 0.4] [--seconds 0.4]
"""
from __future__ import annotations

import argparse
import sys
import time

RATE_HZ = 20.0
MAX_SPEED = 0.6      # rad/s: teto de segurança, mesmo se pedirem mais
MAX_SECONDS = 1.0    # por lado


def phases(speed: float, seconds: float) -> list[tuple[float, float]]:
    """[(velocidade angular, duração)]: esquerda, direita, parado."""
    speed = max(0.0, min(abs(speed), MAX_SPEED))
    seconds = max(0.0, min(seconds, MAX_SECONDS))
    return [(speed, seconds), (-speed, seconds), (0.0, 0.25)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--speed", type=float, default=0.4, help="rad/s (máx. 0,6)")
    ap.add_argument("--seconds", type=float, default=0.4, help="duração de cada lado (máx. 1 s)")
    ap.add_argument("--topic", default="/cmd_vel")
    args = ap.parse_args()

    import rclpy
    from geometry_msgs.msg import Twist

    rclpy.init()
    node = rclpy.create_node("fleet_connect_signal")
    pub = node.create_publisher(Twist, args.topic, 10)
    # Dá tempo de a base descobrir este publicador antes do primeiro comando.
    deadline = time.time() + 3.0
    while pub.get_subscription_count() == 0 and time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    if pub.get_subscription_count() == 0:
        print(f"ninguém assina {args.topic}: sinal não enviado", file=sys.stderr)
        node.destroy_node()
        rclpy.shutdown()
        return 1

    msg = Twist()
    period = 1.0 / RATE_HZ
    try:
        for angular, duration in phases(args.speed, args.seconds):
            msg.angular.z = angular
            end = time.time() + duration
            while time.time() < end:
                pub.publish(msg)
                time.sleep(period)
    finally:
        msg.angular.z = 0.0
        for _ in range(3):
            pub.publish(msg)
            time.sleep(period)
        node.destroy_node()
        rclpy.shutdown()
    print("sinal enviado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
