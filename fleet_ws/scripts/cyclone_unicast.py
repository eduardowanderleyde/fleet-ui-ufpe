#!/usr/bin/env python3
"""Gera a configuração do CycloneDDS com o robô como peer unicast.

Na rede do TurtleBot4 do CIn, a descoberta do DDS por multicast não chega do
robô ao PC (diagnóstico de 19/11/2026: ping e `ros2 multicast` funcionam, mas
`ros2 topic list` no PC só mostra /parameter_events e /rosout). Com unicast
configurado nos dois lados, o PC recebe os tópicos /tb1/...

Este script cuida do lado do PC. A partir do ROBOT_IP, ele descobre o IP do
PC na rede do robô, escreve um XML com esse IP como interface e o robô como
peer, e imprime o caminho do arquivo. O docker/entrypoint.sh o chama quando
ROBOT_IP está definido e o middleware é o CycloneDDS.

O lado do robô é manual: o IP do PC tem de estar em <Peers> no
/etc/turtlebot4/cyclonedds_rpi.xml (ver docs/ufpe/robo_real.md).

Uso:
  python3 cyclone_unicast.py 192.168.50.11            # escreve e imprime o caminho
  python3 cyclone_unicast.py 192.168.50.11 --print    # só mostra o XML
"""
from __future__ import annotations

import argparse
import ipaddress
import socket
import sys
from pathlib import Path
from typing import Optional

DEFAULT_OUT = "/tmp/fleet_cyclonedds_robot.xml"
# Cyclone escuta a descoberta unicast em 7410 + 2 × índice; com "auto", cada
# processo pega o primeiro índice livre até este limite (o Nav2 no PC abre
# vários processos).
MAX_PARTICIPANT_INDEX = 100


def local_ip_for(robot_ip: str) -> Optional[str]:
    """IP deste PC na rota até o robô (sem mandar pacote: UDP connect só escolhe a rota)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((robot_ip, 7400))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith("127.") or ip == "0.0.0.0" else ip


def build_xml(robot_ip: str, local_ip: Optional[str]) -> str:
    """XML do Cyclone: interface do PC (se conhecida), robô como peer, índice automático.

    O multicast continua ligado (padrão do Cyclone), então os processos do
    próprio PC continuam se achando como antes.
    """
    robot_ip = str(ipaddress.ip_address(robot_ip.strip()))
    interfaces = ""
    if local_ip:
        local_ip = str(ipaddress.ip_address(local_ip))
        interfaces = (f'<General><Interfaces><NetworkInterface address="{local_ip}"/>'
                      f'</Interfaces></General>')
    return (
        "<CycloneDDS><Domain>"
        f"{interfaces}"
        "<Discovery>"
        f'<Peers><Peer address="{robot_ip}"/></Peers>'
        "<ParticipantIndex>auto</ParticipantIndex>"
        f"<MaxAutoParticipantIndex>{MAX_PARTICIPANT_INDEX}</MaxAutoParticipantIndex>"
        "</Discovery>"
        "</Domain></CycloneDDS>\n"
    )


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("robot_ip")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--print", action="store_true", help="só mostra o XML, sem gravar")
    args = ap.parse_args(argv)

    try:
        ipaddress.ip_address(args.robot_ip.strip())
    except ValueError:
        print(f"[cyclone_unicast] ROBOT_IP inválido: '{args.robot_ip}'", file=sys.stderr)
        return 2

    local_ip = local_ip_for(args.robot_ip.strip())
    xml = build_xml(args.robot_ip, local_ip)
    if args.print:
        sys.stdout.write(xml)
        return 0

    Path(args.out).write_text(xml, encoding="utf-8")
    where = local_ip or "interface escolhida pelo Cyclone (PC ainda sem rota até o robô)"
    print(f"[cyclone_unicast] peer {args.robot_ip.strip()}, PC {where}", file=sys.stderr)
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
