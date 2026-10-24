"""Testa a lógica pura de fleet_orchestrator/ble_rssi_publisher.py: o
callback de detecção BLE (filtro por endereço + conversão pra Int32). Não
sobe scanner de verdade (precisa de adaptador Bluetooth real) — só constrói
o node real e chama o callback diretamente com um device/advertisement_data
falsos, como tests/test_fleet_orchestrator_logic.py já faz pra outros nós.
"""
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]

try:
    import rclpy
    sys.path.insert(0, str(ROOT / "fleet_ws" / "src" / "fleet_orchestrator"))
    from fleet_orchestrator.ble_rssi_publisher import BleRssiPublisher  # noqa: E402
    HAS_ROS = True
except ImportError:
    HAS_ROS = False


@dataclass
class FakeDevice:
    address: str


@dataclass
class FakeAdvertisementData:
    rssi: int


@unittest.skipUnless(HAS_ROS, "requer rclpy (source /opt/ros/jazzy/setup.bash && fleet_ws/install/setup.bash)")
class BleRssiDetectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        rclpy.shutdown()

    def _make_node(self, target="AA:BB:CC:DD:EE:FF"):
        node = BleRssiPublisher.__new__(BleRssiPublisher)
        rclpy.node.Node.__init__(node, "ble_rssi_publisher_test")
        node._target = target
        node._pub = MagicMock()
        return node

    def test_matching_address_publishes_rssi(self):
        node = self._make_node(target="AA:BB:CC:DD:EE:FF")
        node._on_detection(FakeDevice("AA:BB:CC:DD:EE:FF"), FakeAdvertisementData(rssi=-62))
        node._pub.publish.assert_called_once()
        published = node._pub.publish.call_args[0][0]
        self.assertEqual(published.data, -62)

    def test_address_match_is_case_insensitive(self):
        node = self._make_node(target="aa:bb:cc:dd:ee:ff")
        node._on_detection(FakeDevice("AA:BB:CC:DD:EE:FF"), FakeAdvertisementData(rssi=-70))
        node._pub.publish.assert_called_once()

    def test_non_matching_address_is_ignored(self):
        node = self._make_node(target="AA:BB:CC:DD:EE:FF")
        node._on_detection(FakeDevice("11:22:33:44:55:66"), FakeAdvertisementData(rssi=-50))
        node._pub.publish.assert_not_called()

    def test_rssi_is_cast_to_int(self):
        # bleak/BlueZ às vezes entrega rssi como float dependendo do backend;
        # Int32.data exige int exato, senão rclpy levanta erro de serialização.
        node = self._make_node(target="AA:BB:CC:DD:EE:FF")
        node._on_detection(FakeDevice("AA:BB:CC:DD:EE:FF"), FakeAdvertisementData(rssi=-55.0))
        published = node._pub.publish.call_args[0][0]
        self.assertIsInstance(published.data, int)


if __name__ == "__main__":
    unittest.main()
