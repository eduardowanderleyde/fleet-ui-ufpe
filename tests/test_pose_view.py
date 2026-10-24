import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import main as backend_main  # noqa: E402


class PoseViewTests(unittest.TestCase):
    def test_pose_without_tf_history_keeps_validity(self):
        view = backend_main._pose_view({"x": 1.0, "y": 2.0, "valid": True, "source": "pose_topic"}, now=1000.0)
        self.assertTrue(view["valid"])
        self.assertNotIn("stale", view)

    def test_fresh_tf_pose_is_valid(self):
        view = backend_main._pose_view({"x": 1.0, "valid": True, "tf_ok_at": 999.5}, now=1000.0)
        self.assertTrue(view["valid"])

    def test_pose_goes_stale_when_tf_and_topic_stop(self):
        view = backend_main._pose_view(
            {"x": 1.0, "valid": True, "tf_ok_at": 990.0, "pose_topic_at": 991.0}, now=1000.0
        )
        self.assertFalse(view["valid"])
        self.assertTrue(view["stale"])

    def test_recent_pose_topic_keeps_pose_valid_after_tf_stops(self):
        view = backend_main._pose_view(
            {"x": 1.0, "valid": True, "tf_ok_at": 990.0, "pose_topic_at": 999.0}, now=1000.0
        )
        self.assertTrue(view["valid"])

    def test_view_does_not_mutate_stored_pose(self):
        stored = {"x": 1.0, "valid": True, "tf_ok_at": 0.0}
        backend_main._pose_view(stored, now=1000.0)
        self.assertTrue(stored["valid"])


if __name__ == "__main__":
    unittest.main()
