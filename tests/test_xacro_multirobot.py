"""Regressão para o bug real desta sessão: o xacro do TurtleBot4 publicava
7 tópicos gz-transport absolutos e fixos (cmd_vel, odom, tf, joint_states,
imu, scan, rgbd_camera), ignorando namespace — confirmado empiricamente
(spawnar um 2º robô fazia um único /cmd_vel mover os dois). O fork em
fleet_ws/src/fleet_orchestrator/urdf/tb4/ corrige isso; este teste garante
que ninguém reintroduz o problema sem perceber.

Roda o processador `xacro` de verdade (sem Gazebo) e inspeciona o SDF/URDF
resultante — não precisa de rclpy, só do binário `xacro` e do pacote
fleet_orchestrator instalado (fleet_ws/install sourceado).
"""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
XACRO_ROOT = ROOT / "fleet_ws" / "src" / "fleet_orchestrator" / "urdf" / "tb4" / "standard" / "turtlebot4.urdf.xacro"


def _workspace_sourced() -> bool:
    """`xacro` no PATH não basta: em máquinas onde o ROS base já vem
    pré-sourceado no perfil do shell (mas não este workspace), o binário
    existe e ainda assim falha por não achar o pacote fleet_orchestrator
    (precisa de `source fleet_ws/install/setup.bash`). Checa a condição
    real em vez de um proxy que pode dar falso positivo."""
    if shutil.which("xacro") is None:
        return False
    try:
        from ament_index_python.packages import get_package_share_directory
        get_package_share_directory("fleet_orchestrator")
        return True
    except Exception:
        return False


HAS_XACRO = _workspace_sourced()

EXPECTED_TAGS = ["topic", "odom_topic", "tf_topic"]  # <topic>, <odom_topic>, <tf_topic> — os 7 tópicos vivem em 4 tags distintas


def _run_xacro(namespace: str) -> str:
    args = ["xacro", str(XACRO_ROOT)]
    if namespace:
        args.append(f"namespace:={namespace}")
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"xacro falhou (namespace={namespace!r}): {result.stderr}")
    return result.stdout


def _extract_topics(sdf_text: str) -> list[str]:
    """Todo conteúdo de <topic>...</topic>, <odom_topic>...</odom_topic>,
    <tf_topic>...</tf_topic> no documento processado, na ordem em que aparecem."""
    return re.findall(r"<(?:topic|odom_topic|tf_topic)>([^<]+)</(?:topic|odom_topic|tf_topic)>", sdf_text)


@unittest.skipUnless(HAS_XACRO, "requer `xacro` (source /opt/ros/jazzy/setup.bash && fleet_ws/install/setup.bash)")
class XacroMultiRobotTopicsTests(unittest.TestCase):
    def test_empty_namespace_matches_stock_single_robot_topics(self):
        """namespace="" tem que ser idêntico ao comportamento do pacote
        original (nav2_minimal_tb4_description) — sem isso, o caso de
        1 robô (o mais usado) regride."""
        topics = _extract_topics(_run_xacro(""))

        self.assertGreaterEqual(len(topics), 7)
        for t in topics:
            self.assertFalse(t.startswith("/tb"), f"tópico {t!r} não deveria ter prefixo de robô com namespace vazio")
        self.assertIn("/cmd_vel", topics)
        self.assertIn("/odom", topics)
        self.assertIn("/tf", topics)

    def test_namespace_prefixes_every_gz_topic(self):
        """O bug de verdade: com namespace:=tb1, TODOS os tópicos gz-transport
        (não só cmd_vel/odom) precisam vir prefixados com /tb1."""
        topics = _extract_topics(_run_xacro("tb1"))

        self.assertGreaterEqual(len(topics), 7)
        for t in topics:
            self.assertTrue(t.startswith("/tb1/"), f"tópico {t!r} deveria estar prefixado com /tb1/")
        self.assertIn("/tb1/cmd_vel", topics)
        self.assertIn("/tb1/odom", topics)
        self.assertIn("/tb1/tf", topics)
        self.assertIn("/tb1/joint_states", topics)
        self.assertIn("/tb1/imu", topics)
        self.assertIn("/tb1/scan", topics)
        self.assertIn("/tb1/rgbd_camera", topics)

    def test_two_different_namespaces_never_collide(self):
        """A prova direta do porquê disso existir: tb1 e tb2 não podem
        compartilhar nenhum tópico gz-transport."""
        topics_tb1 = set(_extract_topics(_run_xacro("tb1")))
        topics_tb2 = set(_extract_topics(_run_xacro("tb2")))

        self.assertEqual(topics_tb1 & topics_tb2, set())


if __name__ == "__main__":
    unittest.main()
