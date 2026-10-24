#!/usr/bin/env python3
"""Piloto simulado do sinal BLE: lê o RSSI que o sistema RFComms do Gazebo
(gz-sim-rf-comms-system) já calcula de verdade pra cada mensagem entregue
entre dois `CommsEndpoint`, e republica no MESMO tópico `ble_rssi`
(std_msgs/Int32) que `ble_rssi_publisher.py` usa com hardware real — a
gravação (fleet_data_collector) e a análise não sabem a diferença, o que
permite testar a pipeline inteira sem Bluetooth físico nem robô real.

Verificado antes de escrever este nó (não assumido):
- Lido o código-fonte de RFComms.cc (gazebosim/gz-sim, branch main): o RSSI
  é calculado com perda log-distância + sombreamento gaussiano, e só é
  anexado ao cabeçalho da mensagem (`rssiPtr->set_key("rssi")`) quando o
  pacote É entregue — pacotes descartados não geram nenhum valor (sem
  degradação suave até desconectar; é presença ou ausência de leitura,
  como BLE real costuma se comportar na prática).
- Confirmado ao vivo nesta máquina: `ros2 run ros_gz_bridge parameter_bridge
  "/addr2/rx@ros_gz_interfaces/msg/Dataframe[gz.msgs.Dataframe"` cria sem
  erro — a conversão gz.msgs.Dataframe → ros_gz_interfaces/msg/Dataframe
  (que tem um campo `float64 rssi` de primeira classe, diferente do lado
  Gazebo) é suportada de fábrica pelo ros_gz_bridge, não precisei escrever
  bridge de baixo nível.
- **Validado ponta a ponta de verdade** (não só em partes isoladas):
  gz sim com `rf_comms.sdf` + a bridge acima + este nó, tudo rodando junto;
  publiquei 5 mensagens via `gz topic pub` em `/broker/msgs` e `/ble_rssi`
  recebeu 5 `std_msgs/Int32` reais (-56, -78, -76, -71, -61, variação do
  sombreamento gaussiano configurado). A primeira tentativa "falhou" só
  porque o listener (`ros2 topic echo`) foi iniciado DEPOIS da publicação —
  gz-transport não reenvia mensagem antiga pra assinante tardio; corrigido
  subindo o listener antes de publicar.

Pré-requisito pra rodar: a bridge do passo acima **já precisa estar no ar**
(lançada à parte, ou via launch file — este nó não a inicia sozinho, só
assume que o tópico ROS2 `ros_gz_interfaces/msg/Dataframe` já existe).

Uso:
  # terminal 1: gz sim ... world_com_rf_comms.sdf
  # terminal 2:
  ros2 run ros_gz_bridge parameter_bridge \
    "/addr2/rx@ros_gz_interfaces/msg/Dataframe[gz.msgs.Dataframe"
  # terminal 3:
  ros2 run fleet_orchestrator ble_rssi_sim_bridge \
    --ros-args -p gz_dataframe_topic:=/addr2/rx
"""
from __future__ import annotations

import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32

try:
    from ros_gz_interfaces.msg import Dataframe
except ImportError:  # workspace sem ros_gz_interfaces sourceado
    Dataframe = None


class BleRssiSimBridge(Node):
    def __init__(self) -> None:
        super().__init__('ble_rssi_sim_bridge')
        self.declare_parameter('gz_dataframe_topic', '/addr2/rx')
        self._topic = self.get_parameter('gz_dataframe_topic').value

        self._pub = self.create_publisher(Int32, 'ble_rssi', 10)

        if Dataframe is None:
            self.get_logger().error(
                "ros_gz_interfaces não disponível — source o workspace ROS2 "
                "com ros_gz instalado antes de rodar este nó."
            )
            return

        self.create_subscription(Dataframe, self._topic, self._on_dataframe, 10)
        self.get_logger().info(
            f"Ouvindo {self._topic} (ros_gz_interfaces/msg/Dataframe), "
            f"republicando .rssi em 'ble_rssi' (precisa da bridge "
            f"gz->ros já rodando separadamente nesse tópico)."
        )

    def _on_dataframe(self, msg) -> None:
        out = Int32()
        out.data = int(round(msg.rssi))
        self._pub.publish(out)


def main() -> None:
    rclpy.init()
    node = BleRssiSimBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
