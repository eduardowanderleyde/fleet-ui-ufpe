import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fleet_ws" / "scripts"))

from fuut_detection import detect_obstacle  # noqa: E402


class FuutDetectionTests(unittest.TestCase):
    N = 360
    ANGLE_MIN = -math.pi
    ANGLE_INC = 2 * math.pi / N  # 1 grau por índice

    def _empty_scan(self, range_m: float = 5.0) -> list[float]:
        return [range_m] * self.N

    def test_no_obstacle_returns_none(self):
        ref = self._empty_scan()
        live = self._empty_scan()
        self.assertIsNone(detect_obstacle(ref, live, self.ANGLE_MIN, self.ANGLE_INC))

    def test_detects_single_cluster_distance_and_bearing(self):
        ref = self._empty_scan(5.0)
        live = self._empty_scan(5.0)
        # Obstáculo a 2.0m, ocupando índices 90-94 (bearing esperado ~ -90°).
        for i in range(90, 95):
            live[i] = 2.0

        result = detect_obstacle(ref, live, self.ANGLE_MIN, self.ANGLE_INC)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.distance_m, 2.0, delta=0.1)
        expected_bearing = math.degrees(self.ANGLE_MIN + 92 * self.ANGLE_INC)
        self.assertAlmostEqual(result.bearing_deg, expected_bearing, delta=5.0)
        self.assertEqual(result.num_points, 5)

    def test_picks_largest_cluster_when_multiple_present(self):
        ref = self._empty_scan(5.0)
        live = self._empty_scan(5.0)
        live[10] = 4.5  # ruído: 1 ponto isolado, abaixo do threshold de cluster relevante
        for i in range(200, 210):  # cluster real maior, 10 pontos
            live[i] = 1.5

        result = detect_obstacle(ref, live, self.ANGLE_MIN, self.ANGLE_INC)
        self.assertIsNotNone(result)
        self.assertEqual(result.num_points, 10)
        self.assertAlmostEqual(result.distance_m, 1.5, delta=0.05)

    def test_inf_readings_are_not_flagged(self):
        ref = self._empty_scan(5.0)
        live = self._empty_scan(5.0)
        live[50] = float("inf")  # eco perdido, não é obstáculo
        self.assertIsNone(detect_obstacle(ref, live, self.ANGLE_MIN, self.ANGLE_INC))

    def test_mismatched_lengths_raise(self):
        with self.assertRaises(ValueError):
            detect_obstacle([1.0, 2.0], [1.0], self.ANGLE_MIN, self.ANGLE_INC)


if __name__ == "__main__":
    unittest.main()
