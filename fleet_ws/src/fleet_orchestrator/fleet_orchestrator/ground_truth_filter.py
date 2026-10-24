#!/usr/bin/env python3
"""Extrai a pose do robô de /ground_truth_pose (TFMessage sem nome de entidade).

O bridge ros_gz_bridge pra gz.msgs.Pose_V -> tf2_msgs/msg/TFMessage não
preserva child_frame_id/frame_id (confirmado ao vivo, orquestracion.md
"Coleta de ground truth"). A ordem das entidades no array, porém, é estável
dentro de uma mesma simulação (definida pela ordem de spawn no mundo SDF) —
então filtramos por índice fixo em vez de nome.
"""
from __future__ import annotations

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from tf2_msgs.msg import TFMessage

# Confirmado ao vivo (gz topic -e) no mundo warehouse, modo single-robot:
# índice 0 = chair_0, 1 = chair_1, 2 = turtlebot4 (pose do modelo completo,
# o resto do array é por link de URDF e não interessa aqui). Ainda não
# verificado em modo multi-robô — nesse caso o índice provavelmente muda
# por robô e este nó precisa de um parâmetro por namespace.
ROBOT_INDEX = 2


class GroundTruthFilter(Node):
    def __init__(self) -> None:
        super().__init__('ground_truth_filter')
        self.declare_parameter('robot_index', ROBOT_INDEX)
        self.declare_parameter('frame_id', 'world')
        self._robot_index = self.get_parameter('robot_index').value
        self._frame_id = self.get_parameter('frame_id').value

        self._pub = self.create_publisher(PoseStamped, 'ground_truth_pose_clean', 10)
        self.create_subscription(TFMessage, 'ground_truth_pose', self._on_tf, 10)

    def _on_tf(self, msg: TFMessage) -> None:
        if self._robot_index >= len(msg.transforms):
            return
        tf = msg.transforms[self._robot_index]

        # tf.header.stamp vem sempre zerado do bridge ros_gz_bridge pra esse
        # tipo de mensagem (confirmado ao vivo) — usa o clock do próprio nó
        # (sim time, já que use_sim_time=True é passado no launch) em vez
        # do stamp da mensagem de origem.
        out = PoseStamped()
        out.header.stamp = self.get_clock().now().to_msg()
        out.header.frame_id = self._frame_id
        out.pose.position.x = tf.transform.translation.x
        out.pose.position.y = tf.transform.translation.y
        out.pose.position.z = tf.transform.translation.z
        out.pose.orientation = tf.transform.rotation
        self._pub.publish(out)


def main() -> None:
    rclpy.init()
    node = GroundTruthFilter()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
