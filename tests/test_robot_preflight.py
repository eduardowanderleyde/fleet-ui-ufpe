import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fleet_ws" / "scripts"))

import robot_preflight as rp  # noqa: E402


class RobotPreflightRulesTests(unittest.TestCase):
    def test_cyclonedds_is_ok_and_fastdds_fails(self):
        self.assertTrue(rp.evaluate_rmw("rmw_cyclonedds_cpp").ok)
        self.assertFalse(rp.evaluate_rmw("rmw_fastrtps_cpp").ok)
        self.assertFalse(rp.evaluate_rmw("").ok)

    def test_rate_below_minimum_fails(self):
        self.assertFalse(rp.evaluate_rate("/scan", 2.0).ok)
        self.assertTrue(rp.evaluate_rate("/scan", 10.0).ok)
        self.assertFalse(rp.evaluate_rate("/odom", None).ok)

    def test_clock_skew_limit(self):
        self.assertTrue(rp.evaluate_skew("/scan", 0.08).ok)
        self.assertFalse(rp.evaluate_skew("/scan", 1.5).ok)
        self.assertFalse(rp.evaluate_skew("/scan", -0.9).ok)
        self.assertFalse(rp.evaluate_skew("/scan", None).ok)

    def test_topic_types(self):
        advertised = {
            "/scan": ["sensor_msgs/msg/LaserScan"],
            "/odom": ["nav_msgs/msg/Odometry"],
            "/tf": ["tf2_msgs/msg/TFMessage"],
        }
        by_name = {c.name: c for c in rp.evaluate_types(advertised)}
        self.assertTrue(by_name["tópico /scan"].ok)
        self.assertFalse(by_name["tópico /tf_static"].ok)
        wrong = rp.evaluate_types({"/scan": ["std_msgs/msg/String"]})
        self.assertFalse(wrong[0].ok)

    def test_existing_nav2_is_a_warning_not_a_failure(self):
        check = rp.evaluate_nav2({"/follow_waypoints/_action/status": ["action_msgs/msg/GoalStatusArray"]})
        self.assertFalse(check.ok)
        self.assertTrue(check.warn_only)
        self.assertTrue(rp.evaluate_nav2({}).ok)

    def test_topic_stats(self):
        stats = rp.TopicStats(stamps_wall=[0.0, 0.1, 0.2, 0.3], skews=[0.1, 0.3, 0.2])
        self.assertAlmostEqual(stats.rate_hz(), 10.0)
        self.assertAlmostEqual(stats.median_skew(), 0.2)
        self.assertIsNone(rp.TopicStats().rate_hz())

    def test_report_exit_code_ignores_warnings(self):
        ok = [rp.Check("a", True, ""), rp.Check("b", False, "", warn_only=True)]
        self.assertEqual(rp.report(ok), 0)
        self.assertEqual(rp.report(ok + [rp.Check("c", False, "")]), 1)


if __name__ == "__main__":
    unittest.main()
