"""Descoberta do DDS por unicast com o TurtleBot4 real (diagnóstico de 19/11/2026)."""
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fleet_ws" / "scripts"))

import cyclone_unicast as cu  # noqa: E402


def _robot_link():
    # robot_link não depende do main.py (que puxa SDKs que nem todo PC tem).
    sys.path.insert(0, str(ROOT / "backend"))
    import robot_link
    return robot_link


class BuildXmlTests(unittest.TestCase):
    def test_same_shape_as_the_config_that_worked_on_19_11(self):
        root = ET.fromstring(cu.build_xml("192.168.50.11", "192.168.50.102"))
        domain = root.find("Domain")
        self.assertEqual(domain.find("General/Interfaces/NetworkInterface").get("address"),
                         "192.168.50.102")
        self.assertEqual(domain.find("Discovery/Peers/Peer").get("address"), "192.168.50.11")
        self.assertEqual(domain.find("Discovery/ParticipantIndex").text, "auto")
        self.assertEqual(domain.find("Discovery/MaxAutoParticipantIndex").text, "100")

    def test_without_local_ip_lets_cyclone_pick_the_interface(self):
        root = ET.fromstring(cu.build_xml("192.168.50.11", None))
        self.assertIsNone(root.find("Domain/General"))
        self.assertEqual(root.find("Domain/Discovery/Peers/Peer").get("address"), "192.168.50.11")

    def test_invalid_ip_is_rejected(self):
        with self.assertRaises(ValueError):
            cu.build_xml("192.168.50", None)
        self.assertEqual(cu.main(["nao-e-ip"]), 2)

    def test_local_ip_for_loopback_is_none(self):
        self.assertIsNone(cu.local_ip_for("127.0.0.1"))

    def test_cli_writes_the_file_and_prints_its_path(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "c.xml")
            r = subprocess.run([sys.executable, str(ROOT / "fleet_ws/scripts/cyclone_unicast.py"),
                                "192.168.50.11", "--out", out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), out)
            self.assertIn('Peer address="192.168.50.11"', Path(out).read_text())


class EntrypointTests(unittest.TestCase):
    """O entrypoint gera o XML só quando deve (sem ROS: o source é trocado por um stub)."""

    def run_entrypoint(self, env):
        with tempfile.TemporaryDirectory() as d:
            ros = Path(d, "opt/ros/humble")
            ros.mkdir(parents=True)
            (ros / "setup.bash").write_text("")
            script = (ROOT / "docker/entrypoint.sh").read_text().replace(
                '"/opt/ros/', f'"{d}/opt/ros/')
            ep = Path(d, "entrypoint.sh")
            ep.write_text(script)
            full = {"PATH": os.environ["PATH"], "ROS_DISTRO": "humble",
                    "FLEET_ROOT": str(ROOT), **env}
            r = subprocess.run(["bash", str(ep), "bash", "-c", 'echo "URI=${CYCLONEDDS_URI:-}"'],
                               capture_output=True, text=True, env=full)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout.strip().split("URI=", 1)[1]

    def test_generates_with_robot_ip_and_cyclone(self):
        uri = self.run_entrypoint({"ROBOT_IP": "192.168.50.11",
                                   "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"})
        self.assertEqual(uri, "file://" + cu.DEFAULT_OUT)

    def test_keeps_a_hand_made_uri(self):
        uri = self.run_entrypoint({"ROBOT_IP": "192.168.50.11", "CYCLONEDDS_URI": "file:///meu.xml",
                                   "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"})
        self.assertEqual(uri, "file:///meu.xml")

    def test_off_without_robot_ip_or_when_disabled_or_with_fastdds(self):
        self.assertEqual(self.run_entrypoint({"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"}), "")
        self.assertEqual(self.run_entrypoint({"ROBOT_IP": "192.168.50.11", "ROBOT_DDS_UNICAST": "false",
                                              "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"}), "")
        self.assertEqual(self.run_entrypoint({"ROBOT_IP": "192.168.50.11",
                                              "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp"}), "")


class RobotLinkDdsEnvTests(unittest.TestCase):
    def setUp(self):
        self.rl = _robot_link()
        self.ws = str(ROOT / "fleet_ws")

    def test_ip_from_the_screen_gets_its_own_xml(self):
        env = {"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
               "CYCLONEDDS_URI": "file://" + cu.DEFAULT_OUT}
        with patch.object(cu, "local_ip_for", return_value="192.168.50.102"):
            extra = self.rl.dds_env("192.168.50.12", env, self.ws)
        path = extra["CYCLONEDDS_URI"].removeprefix("file://")
        self.assertIn('Peer address="192.168.50.12"', Path(path).read_text())

    def test_respects_off_switch_hand_made_uri_and_fastdds(self):
        self.assertEqual(self.rl.dds_env("192.168.50.11", {"RMW_IMPLEMENTATION": "rmw_fastrtps_cpp"},
                                         self.ws), {})
        self.assertEqual(self.rl.dds_env("192.168.50.11", {"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
                                                           "ROBOT_DDS_UNICAST": "false"}, self.ws), {})
        self.assertEqual(self.rl.dds_env("192.168.50.11", {"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp",
                                                           "CYCLONEDDS_URI": "file:///meu.xml"},
                                         self.ws), {})


if __name__ == "__main__":
    unittest.main()
