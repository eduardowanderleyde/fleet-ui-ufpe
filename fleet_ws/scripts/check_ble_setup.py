#!/usr/bin/env python3
"""Diagnóstico de pré-requisitos pra rodar ble_rssi_publisher.py (Linux, macOS
ou Windows) — confere, nessa ordem, o que dá pra confirmar sem precisar do
dispositivo BLE alvo de verdade: (1) a lib `bleak` está instalada; (2) o
sistema operacional tem um backend BLE que o bleak reconhece; (3) existe pelo
menos um adaptador Bluetooth utilizável; (4) um scan curto (3s) consegue ver
QUALQUER dispositivo BLE por perto — não precisa ser o alvo do experimento,
só prova que o scan físico funciona nesta máquina.

Não precisa de rclpy nem do workspace ROS2 — roda isolado, antes de tentar o
nó de verdade. Saída não-zero em qualquer etapa que falhar.

Uso:
  python3 fleet_ws/scripts/check_ble_setup.py
"""
from __future__ import annotations

import asyncio
import platform
import sys


def _print_step(ok: bool, label: str, detail: str = "") -> None:
    mark = "[OK]" if ok else "[FALHOU]"
    line = f"{mark} {label}"
    if detail:
        line += f" — {detail}"
    print(line)


async def _run() -> int:
    system = platform.system()
    print(f"Sistema operacional detectado: {system} ({platform.platform()})")

    try:
        from bleak import BleakScanner
        from importlib.metadata import version as _pkg_version
    except ImportError as e:
        _print_step(False, "lib 'bleak' instalada", f"{e} — rode: pip install bleak")
        return 1
    try:
        bleak_version = _pkg_version("bleak")
    except Exception:
        bleak_version = "desconhecida"
    _print_step(True, "lib 'bleak' instalada", f"versão {bleak_version}")

    if system == "Linux":
        hint = "precisa do BlueZ rodando (systemctl status bluetooth) e do pacote dbus-fast"
    elif system == "Darwin":
        hint = "precisa autorizar acesso a Bluetooth pro terminal/Python em Preferências do Sistema"
    elif system == "Windows":
        hint = "precisa do adaptador habilitado no Gerenciador de Dispositivos; sem Docker — bleak usa WinRT nativo"
    else:
        hint = "sistema não testado por este script"
    print(f"  Backend BLE esperado pro bleak nesse SO: {hint}")

    try:
        devices = await asyncio.wait_for(BleakScanner.discover(timeout=3.0), timeout=8.0)
    except asyncio.TimeoutError:
        _print_step(False, "scan BLE de 3s", "travou sem resposta (timeout de segurança de 8s)")
        return 1
    except Exception as e:  # noqa: BLE001 — qualquer falha de backend (sem adaptador, sem permissão, D-Bus fora)
        _print_step(False, "scan BLE de 3s", f"{type(e).__name__}: {e}")
        print("\n  Isso normalmente significa: sem adaptador Bluetooth físico, adaptador")
        print("  desligado, ou sem permissão de acesso (Linux: usuário fora do grupo")
        print("  'bluetooth'; BlueZ não roda nem como container Docker sem --net=host e")
        print("  acesso ao D-Bus do host).")
        return 1

    if not devices:
        _print_step(
            False, "scan BLE de 3s", "rodou sem erro, mas não viu nenhum dispositivo BLE por perto"
        )
        print("\n  Adaptador parece funcionar, mas nenhum dispositivo BLE respondeu em 3s.")
        print("  Pode ser só falta de dispositivo por perto — tente de novo com um celular")
        print("  ou fone Bluetooth ligado ao lado.")
        return 1

    _print_step(True, "scan BLE de 3s", f"{len(devices)} dispositivo(s) visto(s)")
    for d in devices[:5]:
        print(f"    {d.address}  {d.name or '(sem nome)'}")
    if len(devices) > 5:
        print(f"    ... e mais {len(devices) - 5}")
    print("\nAmbiente pronto pra rodar ble_rssi_publisher.py com um target_address real.")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
