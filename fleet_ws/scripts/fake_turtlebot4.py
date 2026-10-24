#!/usr/bin/env python3
"""Robô falso para testar `make robot-up` sem o TurtleBot4.

Publica o que o TurtleBot4 real publica para o Nav2 do PC, com o relógio do
sistema (sem /clock): /odom e TF odom -> base_link a 20 Hz, TF estático
base_link -> rplidar_link e /scan a 10 Hz. Integra o /cmd_vel recebido
(geometry_msgs/Twist, como o Create3 do Humble espera), então o robô "anda"
quando o Nav2 manda. Não serve para medir localização: o laser vê sempre um
círculo de 4 m.

Uso (num domínio de teste, nunca no do robô real):
  ROS_DOMAIN_ID=77 python3 scripts/fake_turtlebot4.py --x 1.02 --y 16.62
"""
import argparse
import math

import rclpy
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster


def _quat_z(yaw):
    return math.sin(yaw / 2.0), math.cos(yaw / 2.0)


class FakeTurtlebot4(Node):
    def __init__(self, x0, y0, yaw0):
        super().__init__("fake_turtlebot4")
        # A pose de odometria começa em zero, como no robô real; x0/y0/yaw0 só
        # dizem ao operador onde colocar a pose inicial do AMCL.
        self.x = self.y = self.yaw = 0.0
        self.v = self.w = 0.0
        self.cmd_count = 0
        self.odom_pub = self.create_publisher(Odometry, "odom", 10)
        self.scan_pub = self.create_publisher(LaserScan, "scan", 10)
        self.tf = TransformBroadcaster(self)
        self.static_tf = StaticTransformBroadcaster(self)
        self.create_subscription(Twist, "cmd_vel", self._on_cmd, 10)
        self._publish_static()
        self.last = self.get_clock().now()
        self.create_timer(0.05, self._tick)
        self.create_timer(0.1, self._scan)
        self.create_timer(5.0, self._report)
        self.get_logger().info(f"robô falso no ar (AMCL deve começar em x={x0}, y={y0}, yaw={yaw0})")

    def _on_cmd(self, msg):
        self.v, self.w = msg.linear.x, msg.angular.z
        self.cmd_count += 1

    def _publish_static(self):
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id, t.child_frame_id = "base_link", "rplidar_link"
        t.transform.translation.z = 0.2
        t.transform.rotation.w = 1.0
        self.static_tf.sendTransform(t)

    def _tick(self):
        now = self.get_clock().now()
        dt = (now - self.last).nanoseconds * 1e-9
        self.last = now
        self.yaw += self.w * dt
        self.x += self.v * math.cos(self.yaw) * dt
        self.y += self.v * math.sin(self.yaw) * dt
        qz, qw = _quat_z(self.yaw)
        stamp = now.to_msg()

        odom = Odometry()
        odom.header.stamp, odom.header.frame_id, odom.child_frame_id = stamp, "odom", "base_link"
        odom.pose.pose.position.x, odom.pose.pose.position.y = self.x, self.y
        odom.pose.pose.orientation.z, odom.pose.pose.orientation.w = qz, qw
        odom.twist.twist.linear.x, odom.twist.twist.angular.z = self.v, self.w
        self.odom_pub.publish(odom)

        t = TransformStamped()
        t.header.stamp, t.header.frame_id, t.child_frame_id = stamp, "odom", "base_link"
        t.transform.translation.x, t.transform.translation.y = self.x, self.y
        t.transform.rotation.z, t.transform.rotation.w = qz, qw
        self.tf.sendTransform(t)

    def _scan(self):
        s = LaserScan()
        s.header.stamp = self.get_clock().now().to_msg()
        s.header.frame_id = "rplidar_link"
        s.angle_min, s.angle_max = -math.pi, math.pi
        s.angle_increment = 2 * math.pi / 360
        s.scan_time, s.range_min, s.range_max = 0.1, 0.164, 12.0
        s.ranges = [4.0] * 360
        self.scan_pub.publish(s)

    def _report(self):
        self.get_logger().info(
            f"odom x={self.x:.2f} y={self.y:.2f} yaw={self.yaw:.2f}  cmd_vel recebidos={self.cmd_count}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--x", type=float, default=1.0216323137283325)
    ap.add_argument("--y", type=float, default=16.61626625061035)
    ap.add_argument("--yaw", type=float, default=0.0)
    args = ap.parse_args()
    rclpy.init()
    node = FakeTurtlebot4(args.x, args.y, args.yaw)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
