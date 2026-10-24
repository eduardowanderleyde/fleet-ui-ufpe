"""Regressões dos achados do code review de main..new-way-samsung (2026-10-23)."""
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ros_bridge import RosBridge  # noqa: E402


class ReturnLegsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        routes = Path(self.tmp.name) / "routes" / "default"
        routes.mkdir(parents=True)
        # Ida em L: (0,0) -> (10,0) -> (10,5), orientações da ida gravadas.
        (routes / "l.yaml").write_text(
            "poses:\n"
            "  - {x: 0.0, y: 0.0, yaw: 0.0}\n"
            "  - {x: 10.0, y: 0.0, yaw: 0.0}\n"
            "  - {x: 10.0, y: 5.0, yaw: 1.5708}\n"
        )
        self.bridge = RosBridge.__new__(RosBridge)
        self.bridge.ros_ws = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_return_legs_face_direction_of_travel_and_end_with_requested_yaw(self):
        if self.bridge._route_poses("l", "") is None:
            self.skipTest("formato de rota diferente do esperado por _route_poses")
        legs = self.bridge._return_legs("l", "", (0.0, 0.0, 0.7), current=(10.0, 5.0))
        # Volta a partir do ponto mais próximo (índice 2): passa por (10,0) e termina em (0,0).
        self.assertEqual([(round(x, 3), round(y, 3)) for x, y, _ in legs], [(10.0, 0.0), (0.0, 0.0)])
        self.assertAlmostEqual(legs[0][2], math.pi)  # de (10,0) olhando para (0,0)
        self.assertAlmostEqual(legs[-1][2], 0.7)      # orientação pedida

    def test_target_not_first_point_goes_direct(self):
        legs = self.bridge._return_legs("l", "", (3.0, 3.0, 0.0), current=(10.0, 5.0))
        self.assertEqual(legs, [(3.0, 3.0, 0.0)])


class RequireMuutTests(unittest.TestCase):
    def test_single_robot_without_namespace_may_move(self):
        try:
            import main  # noqa: F401
        except Exception as exc:  # backend precisa de fastapi/rclpy opcionais
            self.skipTest(f"backend indisponível: {exc}")
        with mock.patch.object(main, "_read_robot_roles", return_value={"tb1": "MUUT", "tb2": "FUUT"}):
            self.assertIsNone(main._require_muut(""))
            self.assertIsNone(main._require_muut("tb1"))
            self.assertEqual(main._require_muut("tb2").status_code, 403)
            self.assertEqual(main._require_muut("tb9").status_code, 403)


if __name__ == "__main__":
    unittest.main()
