"""Testa a estrutura de turtlebot4_multi_sim.launch.py sem subir Gazebo: só
chama generate_launch_description() e inspeciona as ações resultantes.

Guarda de regressão pro tuning que custou caro (ver orquestracion.md):
- ROBOTS lido de FLEET_ROBOTS (default caiu de 3 pra 2 robôs porque rodar
  3 sem GPU deixava o Nav2 instável sob carga).
- O stagger de 12s entre SLAM de robôs consecutivos existe porque um
  stagger de 8s já causou 1 timeout real de lifecycle (change_state) —
  ver commit c31b364. Não deixar alguém "otimizar" isso de volta sem querer.
"""
import importlib.util
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _workspace_sourced() -> bool:
    """`import launch` sozinho não basta: em máquinas onde o ROS base já
    vem pré-sourceado no perfil do shell (mas não este workspace), esse
    import passa e ainda assim generate_launch_description() falha por não
    achar o pacote fleet_orchestrator (precisa de
    `source fleet_ws/install/setup.bash`). Checa a condição real."""
    try:
        from ament_index_python.packages import get_package_share_directory
        get_package_share_directory("fleet_orchestrator")
        return True
    except Exception:
        return False


try:
    import launch  # noqa: F401
    from launch.actions import IncludeLaunchDescription, TimerAction
    HAS_LAUNCH = _workspace_sourced()
except ImportError:
    HAS_LAUNCH = False

# Convenção do ROS 2: launch files usam extensão dupla `.launch.py` — não são
# pensados pra `import nome_do_modulo` normal (ros2 launch os carrega via
# caminho de arquivo, não import), então este teste faz o mesmo.
LAUNCH_FILE = ROOT / "fleet_ws" / "src" / "fleet_orchestrator" / "launch" / "turtlebot4_multi_sim.launch.py"


def _import_multi_sim_launch():
    """Recarrega do zero a cada chamada: ROBOTS é lido de FLEET_ROBOTS no
    import (não dá pra reavaliar só chamando generate_launch_description de
    novo), então testar com FLEET_ROBOTS diferentes precisa de reimport."""
    spec = importlib.util.spec_from_file_location("turtlebot4_multi_sim_under_test", LAUNCH_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _timer_actions(entities) -> list:
    return [a for a in entities if isinstance(a, TimerAction)]


@unittest.skipUnless(HAS_LAUNCH, "requer os pacotes launch/launch_ros do ROS 2 (source /opt/ros/jazzy/setup.bash)")
class MultiSimLaunchStructureTests(unittest.TestCase):
    def setUp(self):
        self._orig_fleet_robots = os.environ.get("FLEET_ROBOTS")

    def tearDown(self):
        if self._orig_fleet_robots is None:
            os.environ.pop("FLEET_ROBOTS", None)
        else:
            os.environ["FLEET_ROBOTS"] = self._orig_fleet_robots

    def test_default_robot_count_is_two_not_three(self):
        """Regressão direta do commit 762f5a4: default é 2 robôs (tb1,tb2),
        não 3 — rodar os 3 sem GPU é o teto de recursos documentado."""
        os.environ.pop("FLEET_ROBOTS", None)
        mod = _import_multi_sim_launch()

        self.assertEqual(mod.ROBOTS, ["tb1", "tb2"])

    def test_fleet_robots_env_var_overrides_robot_list(self):
        os.environ["FLEET_ROBOTS"] = "tb1,tb2,tb3"
        mod = _import_multi_sim_launch()

        self.assertEqual(mod.ROBOTS, ["tb1", "tb2", "tb3"])

    def test_spawns_exactly_one_timer_action_per_robot_for_each_stage(self):
        os.environ["FLEET_ROBOTS"] = "tb1,tb2,tb3"
        mod = _import_multi_sim_launch()

        ld = mod.generate_launch_description()
        timers = _timer_actions(ld.entities)
        # 3 spawn + 3 slam + 3 nav2 = 9 TimerActions pra 3 robôs.
        self.assertEqual(len(timers), 9)

        include_counts = sum(
            1 for t in timers for a in t.actions if isinstance(a, IncludeLaunchDescription)
        )
        self.assertEqual(include_counts, 9)

    def test_slam_stagger_is_at_least_ten_seconds_apart(self):
        """O stagger de 12s entre SLAM consecutivos não é estético — um
        stagger de 8s já causou timeout real de lifecycle sob a carga de 3
        robôs (ver orquestracion.md, seção Limitação conhecida)."""
        os.environ["FLEET_ROBOTS"] = "tb1,tb2,tb3"
        mod = _import_multi_sim_launch()

        ld = mod.generate_launch_description()
        timers = sorted(_timer_actions(ld.entities), key=lambda t: t.period)
        # Períodos: 3 de spawn (curtos), depois 3 de slam, depois 3 de nav2.
        slam_periods = timers[3:6]
        periods = sorted(t.period for t in slam_periods)
        gaps = [b - a for a, b in zip(periods, periods[1:])]

        self.assertTrue(all(gap >= 10.0 for gap in gaps), f"gaps entre SLAM muito curtos: {gaps}")

    def test_nav2_starts_only_after_all_slam_instances_have_had_time_to_settle(self):
        os.environ["FLEET_ROBOTS"] = "tb1,tb2,tb3"
        mod = _import_multi_sim_launch()

        ld = mod.generate_launch_description()
        timers = sorted(_timer_actions(ld.entities), key=lambda t: t.period)
        slam_last = timers[5].period   # último dos 3 SLAM (índices 3,4,5 após os 3 de spawn)
        nav2_first = timers[6].period  # primeiro dos 3 Nav2

        self.assertGreater(nav2_first, slam_last)


if __name__ == "__main__":
    unittest.main()
