import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fleet_ws" / "scripts" / "cbsoft"))

import bag_to_nav_csv as conv  # noqa: E402

ROUTE = [(0.0, 0.0), (0.0, -10.0), (-5.0, -10.0)]


def _l_shaped_run(speed=0.25, dt=0.1):
    """Robô sai de (0,0), desce 10 m, vira e anda 5 m pro oeste."""
    poses, odoms, t, x, y = [], [], 100.0, 0.0, 0.0
    for tx, ty in ROUTE[1:]:
        while abs(tx - x) + abs(ty - y) > 1e-9:
            step = min(speed * dt, abs(tx - x) + abs(ty - y))
            vx = step / dt * (1 if tx > x else -1 if tx < x else 0)
            vy = step / dt * (1 if ty > y else -1 if ty < y else 0)
            x += vx * dt
            y += vy * dt
            t += dt
            poses.append((t, x, y))
            odoms.append((t, vx, vy, 0.0))
    return poses, odoms


class BuildRowsTests(unittest.TestCase):
    def setUp(self):
        poses, odoms = _l_shaped_run()
        self.rows = conv.build_rows(poses, odoms, ROUTE)
        self.col = {name: i for i, name in enumerate(conv.COLUMNS)}

    def test_columns_match_nav_3points(self):
        self.assertEqual(conv.COLUMNS[0], "Timestamp_Legivel")
        self.assertEqual(conv.COLUMNS[-1], "Status")
        self.assertEqual(len(self.rows[0]), len(conv.COLUMNS))

    def test_status_sequence(self):
        statuses = [r[self.col["Status"]] for r in self.rows]
        self.assertEqual(statuses[0], "START")
        self.assertEqual(statuses.count("SUCCEEDED"), 2)
        self.assertEqual(statuses[-1], "SUCCEEDED")

    def test_targets_advance_in_route_order(self):
        names = [r[self.col["Waypoint_Nome"]] for r in self.rows if r[self.col["Status"]] == "SUCCEEDED"]
        self.assertEqual(names, ["Ponto_Medio", "Ponto_Final"])
        start = self.rows[0]
        self.assertEqual((start[self.col["Waypoint_Index"]], start[self.col["Waypoint_Nome"]]), (0, "Ponto_Inicial"))

    def test_sampling_interval(self):
        times = [r[self.col["Unix_Time"]] for r in self.rows[:20]]
        gaps = {round(b - a, 6) for a, b in zip(times, times[1:])}
        self.assertEqual(gaps, {conv.LOG_INTERVAL})

    def test_distance_remaining_decreases_on_first_leg(self):
        leg = [r[self.col["Distancia_Restante"]] for r in self.rows if r[self.col["Waypoint_Index"]] == 1
               and r[self.col["Status"]] == "NAVIGATING"]
        self.assertGreater(leg[0], leg[-1])
        self.assertAlmostEqual(leg[0], 10.0, delta=0.3)

    def test_velocity_comes_from_odom(self):
        speeds = [r[self.col["Velocidade_Linear_Total_m_s"]] for r in self.rows[1:-1]]
        self.assertAlmostEqual(sum(speeds) / len(speeds), 0.25, delta=0.01)

    def test_latched_pose_before_recording_does_not_shift_start(self):
        poses, odoms = _l_shaped_run()
        latched = [(poses[0][0] - 40.0, 0.0, 0.0)]  # /amcl_pose guardada pelo DDS
        rows = conv.build_rows(latched + poses, odoms, ROUTE)
        self.assertAlmostEqual(rows[0][self.col["Unix_Time"]], odoms[0][0])
        self.assertEqual(len(rows), len(self.rows))

    def test_wall_offset_shifts_time(self):
        poses, odoms = _l_shaped_run()
        rows = conv.build_rows(poses, odoms, ROUTE, wall_offset=1_000_000.0)
        self.assertAlmostEqual(rows[0][self.col["Unix_Time"]] - self.rows[0][self.col["Unix_Time"]], 1_000_000.0)


class WallOffsetTests(unittest.TestCase):
    def test_sim_time_aligns_to_bag_name_utc(self):
        off = conv.wall_offset_from_bag_name("collections/default/2026-10-22_02-15-26_564408_3c082aa5", 500.0)
        self.assertAlmostEqual(off + 500.0, 1792635326.564408, places=3)

    def test_wall_clock_stamps_untouched(self):
        self.assertEqual(conv.wall_offset_from_bag_name("x/2026-10-22_02-15-26_564408_a", 1.79e9), 0.0)

    def test_unexpected_name_falls_back(self):
        self.assertEqual(conv.wall_offset_from_bag_name("x/minha_gravacao", 500.0), 0.0)


if __name__ == "__main__":
    unittest.main()
