"""Testes para backend/robot_config.py — resolução de namespace de tópicos."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import robot_config as rc


class TestRobotNamespaceConfig(unittest.TestCase):
    """Testes para RobotNamespaceConfig."""
    
    def test_topic_with_namespace(self):
        cfg = rc.RobotNamespaceConfig("tb1")
        self.assertEqual(cfg.topic("scan"), "/tb1/scan")
        self.assertEqual(cfg.topic("/scan"), "/tb1/scan")
        self.assertEqual(cfg.topic("odom"), "/tb1/odom")
        self.assertEqual(cfg.topic("tf"), "/tb1/tf")
    
    def test_topic_without_namespace(self):
        cfg = rc.RobotNamespaceConfig("")
        self.assertEqual(cfg.topic("scan"), "/scan")
        self.assertEqual(cfg.topic("/scan"), "/scan")
        self.assertEqual(cfg.topic("odom"), "/odom")
    
    def test_topics_dict_with_namespace(self):
        cfg = rc.RobotNamespaceConfig("tb1")
        base = {"/scan": "LaserScan", "/odom": "Odometry"}
        result = cfg.topics(base)
        self.assertEqual(result, {"/tb1/scan": "LaserScan", "/tb1/odom": "Odometry"})
    
    def test_topics_dict_without_namespace(self):
        cfg = rc.RobotNamespaceConfig("")
        base = {"/scan": "LaserScan", "/odom": "Odometry"}
        result = cfg.topics(base)
        self.assertEqual(result, {"/scan": "LaserScan", "/odom": "Odometry"})
    
    def test_frame_without_prefix(self):
        cfg = rc.RobotNamespaceConfig("tb1")
        self.assertEqual(cfg.frame("base_link"), "base_link")
        self.assertEqual(cfg.frame("odom"), "odom")
    
    def test_frame_with_prefix(self):
        cfg = rc.RobotNamespaceConfig("tb1")
        self.assertEqual(cfg.frame("base_link", prefix_frames=True), "tb1/base_link")
        self.assertEqual(cfg.frame("odom", prefix_frames=True), "tb1/odom")
    
    def test_frame_empty_namespace(self):
        cfg = rc.RobotNamespaceConfig("")
        self.assertEqual(cfg.frame("base_link"), "base_link")
        self.assertEqual(cfg.frame("base_link", prefix_frames=True), "base_link")
    
    def test_has_namespace(self):
        self.assertTrue(rc.RobotNamespaceConfig("tb1").has_namespace)
        self.assertFalse(rc.RobotNamespaceConfig("").has_namespace)
    
    def test_from_env(self):
        os.environ["ROBOT_NAMESPACE"] = "tb2"
        try:
            cfg = rc.RobotNamespaceConfig.from_env()
            self.assertEqual(cfg.namespace, "tb2")
        finally:
            del os.environ["ROBOT_NAMESPACE"]
    
    def test_from_env_with_slashes(self):
        os.environ["ROBOT_NAMESPACE"] = "/tb1/"
        try:
            cfg = rc.RobotNamespaceConfig.from_env()
            self.assertEqual(cfg.namespace, "tb1")
        finally:
            del os.environ["ROBOT_NAMESPACE"]
    
    def test_from_env_empty(self):
        if "ROBOT_NAMESPACE" in os.environ:
            del os.environ["ROBOT_NAMESPACE"]
        cfg = rc.RobotNamespaceConfig.from_env()
        self.assertEqual(cfg.namespace, "")


class TestTopicHelpers(unittest.TestCase):
    """Testes para funções auxiliares de tópicos."""
    
    def test_topic_with_namespace_function(self):
        self.assertEqual(rc.topic_with_namespace("scan", "tb1"), "/tb1/scan")
        self.assertEqual(rc.topic_with_namespace("/scan", "tb1"), "/tb1/scan")
        self.assertEqual(rc.topic_with_namespace("scan", ""), "/scan")
    
    def test_expected_robot_topics_with_namespace(self):
        topics = rc.expected_robot_topics("tb1")
        self.assertIn("/tb1/scan", topics)
        self.assertIn("/tb1/odom", topics)
        self.assertIn("/tb1/tf", topics)
        self.assertIn("/tb1/cmd_vel", topics)
    
    def test_expected_robot_topics_without_namespace(self):
        topics = rc.expected_robot_topics("")
        self.assertIn("/scan", topics)
        self.assertIn("/odom", topics)
        self.assertIn("/tf", topics)
        self.assertIn("/cmd_vel", topics)


class TestGetNamespace(unittest.TestCase):
    """Testes para get_namespace()."""
    
    def tearDown(self):
        if "ROBOT_NAMESPACE" in os.environ:
            del os.environ["ROBOT_NAMESPACE"]
    
    def test_get_namespace_set(self):
        os.environ["ROBOT_NAMESPACE"] = "tb1"
        self.assertEqual(rc.get_namespace(), "tb1")
    
    def test_get_namespace_empty(self):
        if "ROBOT_NAMESPACE" in os.environ:
            del os.environ["ROBOT_NAMESPACE"]
        self.assertEqual(rc.get_namespace(), "")
    
    def test_get_namespace_strips_slashes(self):
        os.environ["ROBOT_NAMESPACE"] = "/tb1/"
        self.assertEqual(rc.get_namespace(), "tb1")
    
    def test_get_namespace_strips_spaces(self):
        os.environ["ROBOT_NAMESPACE"] = "  tb1  "
        self.assertEqual(rc.get_namespace(), "tb1")


if __name__ == "__main__":
    unittest.main()
