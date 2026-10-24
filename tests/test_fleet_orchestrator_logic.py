"""Testa a lógica pura de fleet_orchestrator/main.py: matemática de ângulo,
gate de movimento por papel, e o isolamento de TF por robô que substituiu
tf2_ros.TransformListener (ver _setup_robot_tf). Não sobe Gazebo/Nav2 — só
constrói o node real (precisa de rclpy.init(), mas não de nenhum outro nó
no grafo) e chama os métodos diretamente.
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Um try/except só em "import rclpy" não basta: rclpy pode estar no PYTHONPATH
# (ROS base sourceado) mesmo sem o workspace deste projeto buildado/sourceado
# — nesse caso `import rclpy` passa, mas `from fleet_orchestrator.main import
# ...` falha (fleet_msgs é um pacote de mensagens custom, só existe depois de
# `source fleet_ws/install/setup.bash`). Um único try/except ao redor de
# ambos garante que qualquer um dos dois faltando vira skip, não erro de
# coleta do unittest.
try:
    import rclpy
    sys.path.insert(0, str(ROOT / "fleet_ws" / "src" / "fleet_orchestrator"))
    from fleet_orchestrator.main import FleetOrchestrator, quat_to_yaw, wrap_angle, yaw_to_quat  # noqa: E402
    HAS_ROS = True
except ImportError:
    HAS_ROS = False


@unittest.skipUnless(HAS_ROS, "requer rclpy (source /opt/ros/jazzy/setup.bash && fleet_ws/install/setup.bash)")
class AngleMathTests(unittest.TestCase):
    """Puras, sem node — mas moram no mesmo arquivo pra não duplicar o skip guard."""

    def test_yaw_to_quat_and_back_roundtrips(self):
        for yaw in (0.0, math.pi / 4, math.pi / 2, math.pi - 0.01, -math.pi / 3):
            q = yaw_to_quat(yaw)
            self.assertAlmostEqual(quat_to_yaw(q), yaw, places=6)

    def test_wrap_angle_brings_large_values_into_range(self):
        # wrap_angle normaliza para (-pi, pi] — 3*pi cai exatamente na borda
        # superior (pi), -3*pi cai exatamente na borda inferior (-pi).
        self.assertAlmostEqual(wrap_angle(3 * math.pi), math.pi, places=6)
        self.assertAlmostEqual(wrap_angle(-3 * math.pi), -math.pi, places=6)
        self.assertAlmostEqual(wrap_angle(0.5), 0.5, places=6)


@unittest.skipUnless(HAS_ROS, "requer rclpy (source /opt/ros/jazzy/setup.bash && fleet_ws/install/setup.bash)")
class FleetOrchestratorLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = FleetOrchestrator()
        # roles.yaml no repo está temporariamente com tudo MUUT (ver
        # orquestracion.md) — sobrescreve aqui pra testar o gate de papel de
        # verdade, sem depender desse estado transitório do arquivo.
        cls.node._roles = {"tb1": "MUUT", "tb2": "FUUT", "tb3": "SU"}

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    def test_empty_robot_id_is_always_muut(self):
        self.assertEqual(self.node._role(""), "MUUT")
        self.assertTrue(self.node._motion_allowed(""))

    def test_motion_gate_follows_roles_yaml(self):
        self.assertTrue(self.node._motion_allowed("tb1"))
        self.assertFalse(self.node._motion_allowed("tb2"))
        self.assertFalse(self.node._motion_allowed("tb3"))

    def test_unknown_robot_defaults_to_muut(self):
        # _role() cai pra MUUT se o robô não está em roles.yaml — não trava
        # por engano um robô que simplesmente não foi catalogado.
        self.assertEqual(self.node._role("tb_desconhecido"), "MUUT")

    def test_map_base_is_always_unprefixed(self):
        """Isolamento é por buffer/tópico (ver _setup_robot_tf), não por
        frame_id — SLAM/Nav2 (turtlebot4_navigation, intocado) publicam
        sempre map/base_link, com ou sem robô especificado."""
        self.assertEqual(self.node._map_base(""), ("map", "base_link"))
        self.assertEqual(self.node._map_base("tb1"), ("map", "base_link"))
        self.assertEqual(self.node._map_base("tb7"), ("map", "base_link"))

    def test_action_name_prefixes_only_for_named_robots(self):
        self.assertEqual(self.node._action_name(""), "/navigate_through_poses")
        self.assertEqual(self.node._action_name("tb1"), "/tb1/navigate_through_poses")

    def test_subdir_and_route_dir(self):
        self.assertEqual(self.node._subdir(""), "default")
        self.assertEqual(self.node._subdir("tb1"), "tb1")
        self.assertEqual(self.node._robot_route_dir("tb1"), self.node._routes_dir + "/tb1")

    def test_setup_robot_tf_creates_independent_buffers_per_robot(self):
        self.node._setup_robot_tf("test_tb_a")
        self.node._setup_robot_tf("test_tb_b")

        self.assertIn("test_tb_a", self.node._tf_buffers)
        self.assertIn("test_tb_b", self.node._tf_buffers)
        self.assertIsNot(
            self.node._tf_buffers["test_tb_a"], self.node._tf_buffers["test_tb_b"],
            "cada robô precisa do próprio Buffer — um só compartilhado reintroduziria "
            "o bug de TF misturado entre robôs que motivou essa mudança",
        )

    def test_setup_robot_tf_is_idempotent(self):
        """Chamar 2x pro mesmo robot_id não pode duplicar subscriptions (isso
        já aconteceria hoje em _known_robot() se _setup_robot_tf não fosse
        idempotente para o robot_id "")."""
        self.node._setup_robot_tf("test_tb_idempotent")
        buf_first = self.node._tf_buffers["test_tb_idempotent"]
        subs_count_first = len(self.node._tf_subs["test_tb_idempotent"])

        self.node._setup_robot_tf("test_tb_idempotent")

        self.assertIs(self.node._tf_buffers["test_tb_idempotent"], buf_first)
        self.assertEqual(len(self.node._tf_subs["test_tb_idempotent"]), subs_count_first)


if __name__ == "__main__":
    unittest.main()
