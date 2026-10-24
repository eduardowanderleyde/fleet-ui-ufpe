#!/usr/bin/env python3
"""Publica a força de sinal (RSSI) de um dispositivo Bluetooth Low Energy (BLE)
como tópico ROS2, pra correlacionar com a posição do robô durante um replay —
mesmo padrão de record/replay do framework, aplicado a teste de conectividade
sem fio em vez de navegação (caso de uso: robô carrega um celular numa rota,
mede degradação do sinal até perder conexão com um dispositivo fixo).

Precisa de um adaptador Bluetooth real na máquina que roda este nó e da lib
`bleak` (BLE cross-platform via BlueZ no Linux). Sem adaptador ou sem
`target_address` configurado, o nó loga o erro e fica de pé sem publicar —
não derruba o resto da pilha.

`target_address` aceita `ros2 param set /ble_rssi_publisher target_address
<MAC>` em tempo real (via callback de parâmetro) — o scanner, que só começa
quando o endereço vira não-vazio, é o que permite o Fleet UI escolher o
dispositivo alvo por execução sem precisar reiniciar o nó.
"""
from __future__ import annotations

import asyncio
import threading

import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import SetParametersResult
from std_msgs.msg import Int32

try:
    from bleak import BleakScanner
except ImportError:  # biblioteca opcional — só necessária quando este nó roda de verdade
    BleakScanner = None


class BleRssiPublisher(Node):
    def __init__(self) -> None:
        super().__init__('ble_rssi_publisher')
        self.declare_parameter('target_address', '')
        self.declare_parameter('scan_interval_s', 1.0)
        self._target = self.get_parameter('target_address').value
        self._interval = float(self.get_parameter('scan_interval_s').value)
        self._loop_thread: threading.Thread | None = None

        self._pub = self.create_publisher(Int32, 'ble_rssi', 10)
        self.add_on_set_parameters_callback(self._on_param_change)

        if BleakScanner is None:
            self.get_logger().error(
                "bleak não instalado — rode 'pip install bleak'. Nó fica de pé sem publicar."
            )
            return
        if self._target:
            self._start_scanner_loop()
        else:
            self.get_logger().error(
                "parâmetro 'target_address' vazio — informe via launch ou "
                "'ros2 param set /ble_rssi_publisher target_address <MAC>'."
            )

    def _start_scanner_loop(self) -> None:
        if self._loop_thread is not None:
            return
        self._loop_thread = threading.Thread(target=self._run_scanner_loop, daemon=True)
        self._loop_thread.start()

    def _on_param_change(self, params) -> SetParametersResult:
        for p in params:
            if p.name == 'target_address':
                self._target = p.value
                if BleakScanner is not None and self._target:
                    self._start_scanner_loop()
        return SetParametersResult(successful=True)

    def _on_detection(self, device, advertisement_data) -> None:
        """Callback do BleakScanner — roda na thread do loop asyncio, não na
        de spin do rclpy; `create_publisher().publish()` é seguro de chamar
        de outra thread (rclpy só serializa internamente)."""
        if device.address.lower() != self._target.lower():
            return
        msg = Int32()
        msg.data = int(advertisement_data.rssi)
        self._pub.publish(msg)

    def _run_scanner_loop(self) -> None:
        asyncio.run(self._scan_forever())

    async def _scan_forever(self) -> None:
        async with BleakScanner(self._on_detection):
            while rclpy.ok():
                await asyncio.sleep(self._interval)


def main() -> None:
    rclpy.init()
    node = BleRssiPublisher()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
