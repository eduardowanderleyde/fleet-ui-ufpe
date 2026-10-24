import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.planner import Planner  # noqa: E402


class PlannerScopingTests(unittest.TestCase):
    """_scope_input é o que garante que um agente restrito a um robô não pode
    ser convencido pelo modelo a operar outro. Testado sem chamar a Anthropic."""

    def setUp(self):
        self.scoped = Planner(executor=MagicMock(), analyst=MagicMock(), robot_id="tb1", api_key="test")
        self.unscoped = Planner(executor=MagicMock(), analyst=MagicMock(), api_key="test")

    def test_forces_robot_id_field_even_if_model_requests_another(self):
        scoped_input = self.scoped._scope_input("move_robot", {"robot_id": "tb2", "x": 1, "y": 2})
        self.assertEqual(scoped_input["robot_id"], "tb1")

    def test_forces_run_experiment_config_robot(self):
        scoped_input = self.scoped._scope_input(
            "run_experiment", {"config": {"robot": "tb2", "route": "r1"}}
        )
        self.assertEqual(scoped_input["config"]["robot"], "tb1")

    def test_noop_for_tools_without_robot_id(self):
        self.assertEqual(self.scoped._scope_input("list_robots", {}), {})

    def test_unscoped_planner_leaves_robot_id_untouched(self):
        scoped_input = self.unscoped._scope_input("move_robot", {"robot_id": "tb2"})
        self.assertEqual(scoped_input["robot_id"], "tb2")

    def test_system_prompt_mentions_robot_only_when_scoped(self):
        self.assertIn("tb1", self.scoped._system_prompt())
        self.assertNotIn("restrito", self.unscoped._system_prompt())


if __name__ == "__main__":
    unittest.main()
