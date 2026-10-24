import sys
import threading
import time
import unittest
from pathlib import Path

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fleet_ws" / "scripts"))

from fuut_reference_scan import capture_reference_scan  # noqa: E402


class _FakeScanPublisher(Node):
    """Simula o LiDAR do FUUT publicando em /tb_test/scan — prova
    capture_reference_scan contra rclpy real, sem precisar de Gazebo."""

    def __init__(self, ranges: list[float]) -> None:
        super().__init__("fuut_fake_scan_publisher")
        self._ranges = ranges
        self._pub = self.create_publisher(LaserScan, "/tb_test/scan", qos_profile_sensor_data)
        self._timer = self.create_timer(0.05, self._publish)

    def _publish(self) -> None:
        msg = LaserScan()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.angle_min = -3.14159
        msg.angle_increment = 2 * 3.14159 / len(self._ranges)
        msg.range_max = 10.0
        msg.ranges = self._ranges
        self._pub.publish(msg)


class FuutReferenceScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rclpy.init()

    @classmethod
    def tearDownClass(cls) -> None:
        rclpy.shutdown()

    def test_captures_ranges_from_live_topic(self):
        expected_ranges = [5.0] * 360
        publisher = _FakeScanPublisher(expected_ranges)
        publisher_executor = SingleThreadedExecutor()
        publisher_executor.add_node(publisher)

        stop = threading.Event()

        def spin_publisher():
            while not stop.is_set():
                publisher_executor.spin_once(timeout_sec=0.05)

        thread = threading.Thread(target=spin_publisher, daemon=True)
        thread.start()
        try:
            data = capture_reference_scan("tb_test", timeout_sec=5.0)
        finally:
            stop.set()
            thread.join(timeout=2.0)
            publisher.destroy_node()

        self.assertEqual(len(data["ranges"]), 360)
        self.assertEqual(data["ranges"], expected_ranges)
        self.assertAlmostEqual(data["angle_min"], -3.14159, places=3)

    def test_timeout_when_nothing_publishes(self):
        with self.assertRaises(TimeoutError):
            capture_reference_scan("tb_sem_ninguem_publicando", timeout_sec=0.5)


if __name__ == "__main__":
    unittest.main()
