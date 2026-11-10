import os
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

    def test_local_helper_nodes_do_not_count_as_robot(self):
        names = ["fleet_ui_bridge", "_ros2cli_daemon_0_abc", "_ros2cli_requester_x", "turtlebot4_node"]
        self.assertEqual(rp.robot_nodes(names, ("fleet_ui_bridge",)), ["turtlebot4_node"])
        self.assertEqual(rp.robot_nodes(["_ros2cli_daemon_0_abc"]), [])

    def test_report_exit_code_ignores_warnings(self):
        ok = [rp.Check("a", True, ""), rp.Check("b", False, "", warn_only=True)]
        self.assertEqual(rp.report(ok), 0)
        self.assertEqual(rp.report(ok + [rp.Check("c", False, "")]), 1)


class RobotPreflightNamespaceTests(unittest.TestCase):
    """Testes para suporte a namespace do robô."""
    
    def tearDown(self):
        if "ROBOT_NAMESPACE" in os.environ:
            del os.environ["ROBOT_NAMESPACE"]
    
    def test_get_namespace_empty(self):
        if "ROBOT_NAMESPACE" in os.environ:
            del os.environ["ROBOT_NAMESPACE"]
        self.assertEqual(rp._get_namespace(), "")
    
    def test_get_namespace_set(self):
        os.environ["ROBOT_NAMESPACE"] = "tb1"
        self.assertEqual(rp._get_namespace(), "tb1")
    
    def test_get_namespace_strips_slashes(self):
        os.environ["ROBOT_NAMESPACE"] = "/tb1/"
        self.assertEqual(rp._get_namespace(), "tb1")
    
    def test_topic_with_ns_adds_prefix(self):
        self.assertEqual(rp._topic_with_ns("scan", "tb1"), "/tb1/scan")
        self.assertEqual(rp._topic_with_ns("/scan", "tb1"), "/tb1/scan")
        self.assertEqual(rp._topic_with_ns("odom", "tb1"), "/tb1/odom")
    
    def test_topic_with_ns_no_prefix_when_empty(self):
        self.assertEqual(rp._topic_with_ns("scan", ""), "/scan")
        self.assertEqual(rp._topic_with_ns("/scan", ""), "/scan")
    
    def test_expected_topics_with_ns_all_prefixed(self):
        topics = rp._expected_topics_with_ns("tb1")
        self.assertIn("/tb1/scan", topics)
        self.assertIn("/tb1/odom", topics)
        self.assertIn("/tb1/tf", topics)
        self.assertIn("/tb1/tf_static", topics)
        self.assertNotIn("/scan", topics)
        self.assertNotIn("/odom", topics)
    
    def test_expected_topics_without_ns_global(self):
        topics = rp._expected_topics_with_ns("")
        self.assertIn("/scan", topics)
        self.assertIn("/odom", topics)
        self.assertIn("/tf", topics)
        self.assertNotIn("/tb1/scan", topics)
    
    def test_evaluate_types_with_namespace(self):
        advertised = {
            "/tb1/scan": ["sensor_msgs/msg/LaserScan"],
            "/tb1/odom": ["nav_msgs/msg/Odometry"],
            "/tb1/tf": ["tf2_msgs/msg/TFMessage"],
            "/tb1/tf_static": ["tf2_msgs/msg/TFMessage"],
        }
        checks = rp.evaluate_types(advertised, namespace="tb1")
        by_name = {c.name: c for c in checks}
        self.assertTrue(by_name["tópico /tb1/scan"].ok)
        self.assertTrue(by_name["tópico /tb1/odom"].ok)
        self.assertTrue(by_name["tópico /tb1/tf"].ok)
        self.assertTrue(by_name["tópico /tb1/tf_static"].ok)
    
    def test_evaluate_types_missing_namespaced_topic(self):
        advertised = {
            "/tb1/scan": ["sensor_msgs/msg/LaserScan"],
        }
        checks = rp.evaluate_types(advertised, namespace="tb1")
        by_name = {c.name: c for c in checks}
        self.assertTrue(by_name["tópico /tb1/scan"].ok)
        self.assertFalse(by_name["tópico /tb1/odom"].ok)


if __name__ == "__main__":
    unittest.main()
