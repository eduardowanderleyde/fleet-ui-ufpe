import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ros_bridge import RosBridge  # noqa: E402


class RosBridgeCommandTests(unittest.TestCase):
    def setUp(self):
        self.bridge = RosBridge(str(ROOT / "fleet_ws"))

    def test_record_command_uses_single_robot_and_points(self):
        cmd = self.bridge.build_experiment_cmd({
            "command": "record",
            "robot": "default",
            "route": "rota_a",
            "collect": True,
            "topics": ["scan", "odom"],
            "initial_pose": [0, 0, 0],
            "points": [[1, 2, 0], [3, 4, 1.57]],
        })

        self.assertIn("record", cmd)
        self.assertIn("--single-robot", cmd)
        self.assertIn("--route", cmd)
        self.assertIn("rota_a", cmd)
        self.assertIn("--topics", cmd)
        self.assertIn("scan", cmd)
        self.assertIn("odom", cmd)
        self.assertIn("--points=1,2,0;3,4,1.57", cmd)

    def test_real_robot_keeps_selected_topics(self):
        # Com o robô real (relógio do sistema), a gravação ainda precisa dos
        # tópicos da tela: sem amcl_pose, o cbsoft-csv não tem posição.
        with patch.dict("os.environ", {"FLEET_USE_SIM_TIME": "false"}):
            cmd = self.bridge.build_experiment_cmd({
                "command": "replay",
                "robot": "default",
                "route": "percurso_cbsoft",
                "collect": True,
                "topics": ["scan", "odom", "amcl_pose"],
            })

        self.assertIn("--no-use-sim-time", cmd)
        self.assertIn("--topics", cmd)
        self.assertIn("amcl_pose", cmd)

    def test_replay_command_keeps_robot_and_return_to_start(self):
        cmd = self.bridge.build_experiment_cmd({
            "command": "replay",
            "robot": "tb1",
            "route": "rota_b",
            "collect": False,
            "return_to_start": [0.1, -0.2, 0.3],
        })

        self.assertIn("replay", cmd)
        self.assertIn("--robot", cmd)
        self.assertIn("tb1", cmd)
        self.assertIn("--skip-collection", cmd)
        self.assertIn("--return-to-start=0.1,-0.2,0.3", cmd)

    def test_replay_wait_goal_scales_with_route_length(self):
        with tempfile.TemporaryDirectory() as ws:
            routes = Path(ws) / "routes" / "default"
            routes.mkdir(parents=True)
            (routes / "longa.yaml").write_text(
                "poses:\n- {x: 0, y: 0, yaw: 0}\n- {x: 0, y: -64, yaw: 0}\n- {x: -31, y: -64, yaw: 0}\n"
            )
            (routes / "curta.yaml").write_text("poses:\n- {x: 0, y: 0, yaw: 0}\n- {x: 1, y: 0, yaw: 0}\n")
            bridge = RosBridge(ws)

            longa = bridge.build_experiment_cmd({"command": "replay", "robot": "default", "route": "longa"})
            curta = bridge.build_experiment_cmd({"command": "replay", "robot": "default", "route": "curta"})
            ausente = bridge.build_experiment_cmd({"command": "replay", "robot": "default", "route": "nao_existe"})

        self.assertIn("--wait-goal=693", longa)
        self.assertIn("--wait-goal=300", curta)
        self.assertIn("--wait-goal=300", ausente)

    def test_return_to_route_start_retraces_route_backwards(self):
        with tempfile.TemporaryDirectory() as ws:
            routes = Path(ws) / "routes" / "default"
            routes.mkdir(parents=True)
            (routes / "l.yaml").write_text(
                "poses:\n- {x: 1, y: 16, yaw: 0}\n- {x: -2, y: -47, yaw: 0}\n- {x: -33, y: -47, yaw: 0}\n"
            )
            bridge = RosBridge(ws)
            base = {"command": "replay", "robot": "default", "route": "l"}

            at_end = bridge.build_experiment_cmd({**base, "return_to_start": [1, 16, 0], "current_pose": [-33, -47]})
            at_start = bridge.build_experiment_cmd({**base, "return_to_start": [1, 16, 0], "current_pose": [1.1, 16.0]})
            no_pose = bridge.build_experiment_cmd({**base, "return_to_start": [1, 16, 0]})
            manual = bridge.build_experiment_cmd({**base, "return_to_start": [5, 5, 0], "current_pose": [-33, -47]})

        # Cada meta da volta aponta para a próxima (de (-2,-47) para (1,16)), e a
        # última usa a orientação pedida — não a da ida, que faria o robô girar.
        self.assertIn(f"--return-to-start=-2.0,-47.0,{math.atan2(63, 3)};1.0,16.0,0.0", at_end)
        self.assertIn("--return-to-start=1.0,16.0,0.0", at_start)
        self.assertIn("--return-to-start=1.0,16.0,0.0", no_pose)
        self.assertIn("--return-to-start=5.0,5.0,0.0", manual)

    def test_invalid_discovery_subnet_returns_error(self):
        result = self.bridge.discover_robots("999.bad")

        self.assertEqual(result["found"], [])
        self.assertIn("Subnet inválida", result["error"])

    def test_analyze_bags_builds_expected_command(self):
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="ok", stderr="")

        with patch("ros_bridge.subprocess.run", side_effect=fake_run):
            ok, out = self.bridge.analyze_bags(
                ["collections/default/baseline", "collections/default/replay_01"],
                ["baseline", "replay_01"],
                "fleet_ws/runs/rota_a_abc123/analysis",
            )

        self.assertTrue(ok)
        self.assertEqual(out, "ok")
        shell_cmd = captured["cmd"][-1]  # ["bash", "-c", <shell_cmd>]
        self.assertIn("analyze_runs.py", shell_cmd)
        self.assertIn("collections/default/baseline", shell_cmd)
        self.assertIn("collections/default/replay_01", shell_cmd)
        self.assertIn("--output-dir fleet_ws/runs/rota_a_abc123/analysis", shell_cmd)
        self.assertIn("--labels baseline replay_01", shell_cmd)

    def test_analyze_bags_reports_failure_on_nonzero_exit(self):
        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="boom")

        with patch("ros_bridge.subprocess.run", side_effect=fake_run):
            ok, out = self.bridge.analyze_bags(["b1"], ["baseline"], "out")

        self.assertFalse(ok)
        self.assertIn("boom", out)

    def test_extract_list_field_parses_real_ros2_service_call_output(self):
        """Saída real capturada de `ros2 service call list_robots
        fleet_msgs/srv/ListRobots '{}'` contra uma frota tb1+tb2 de verdade —
        yaml.safe_load(out) lançava ScannerError nisso (não é YAML válido,
        nunca foi: é prosa + repr() do Python). list_robots/list_routes
        voltavam [] mesmo com robôs configurados até essa correção."""
        raw_stdout = (
            "waiting for service to become available...\n"
            "requester: making request: fleet_msgs.srv.ListRobots_Request()\n"
            "\n"
            "response:\n"
            "fleet_msgs.srv.ListRobots_Response(robot_ids=['tb1', 'tb2'])"
        )
        raw_stderr = (
            "[WARN] [rcl]: ROS_LOCALHOST_ONLY is deprecated but still honored if it is enabled. "
            "Use ROS_AUTOMATIC_DISCOVERY_RANGE and ROS_STATIC_PEERS instead.\n"
            "[WARN] [rcl]: 'localhost_only' is enabled, 'automatic_discovery_range' and 'static_peers' will be ignored."
        )
        # Mesma concatenação que RosBridge.run_service produz de verdade.
        out = raw_stdout.strip() + raw_stderr.strip()

        self.assertEqual(RosBridge.extract_list_field(out, "robot_ids"), ["tb1", "tb2"])

    def test_extract_list_field_handles_empty_list(self):
        out = "response:\nfleet_msgs.srv.ListRoutes_Response(route_names=[])"
        self.assertEqual(RosBridge.extract_list_field(out, "route_names"), [])

    def test_extract_list_field_returns_empty_on_unparseable_output(self):
        self.assertEqual(RosBridge.extract_list_field("qualquer coisa sem o campo", "robot_ids"), [])


if __name__ == "__main__":
    unittest.main()
