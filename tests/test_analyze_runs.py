import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fleet_ws" / "scripts"))

from analyze_runs import (  # noqa: E402
    _find_slam_pose_topic_name,
    _resample_pair,
    _resample_xy_by_time,
    _resolve_trajectory_topic,
)


class AnalyzeRunsResamplingTests(unittest.TestCase):
    def test_time_resampling_interpolates_to_fixed_normalised_grid(self):
        t = np.array([0.0, 2.0, 4.0], dtype=np.float64)
        xy = np.array([[0.0, 0.0], [2.0, 0.0], [4.0, 0.0]], dtype=np.float64)

        out = _resample_xy_by_time(t, xy, samples=5)

        np.testing.assert_allclose(
            out,
            np.array([
                [0.0, 0.0],
                [1.0, 0.0],
                [2.0, 0.0],
                [3.0, 0.0],
                [4.0, 0.0],
            ]),
        )

    def test_time_pair_resampling_uses_requested_sample_count(self):
        t1 = np.array([0.0, 1.0], dtype=np.float64)
        xy1 = np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float64)
        t2 = np.array([10.0, 15.0, 20.0], dtype=np.float64)
        xy2 = np.array([[0.0, 0.0], [0.5, 0.0], [1.0, 0.0]], dtype=np.float64)

        a, b = _resample_pair(xy1, xy2, t1=t1, t2=t2, mode="time", samples=4)

        self.assertEqual(a.shape, (4, 2))
        self.assertEqual(b.shape, (4, 2))
        np.testing.assert_allclose(a, b)

    def test_index_resampling_preserves_legacy_min_length(self):
        xy1 = np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float64)
        xy2 = np.array([[0.0, 0.0], [0.5, 0.0], [1.0, 0.0]], dtype=np.float64)

        a, b = _resample_pair(xy1, xy2, mode="index")

        self.assertEqual(a.shape, (2, 2))
        self.assertEqual(b.shape, (2, 2))


class SlamPoseTopicResolutionTests(unittest.TestCase):
    """Antes desta correção, --trajectory-topic auto nunca reconhecia o tópico
    "pose" (estimativa ao vivo do SLAM Toolbox, corrigida no referencial do
    mapa) e caía direto pra /odom (odometria bruta, acumula deriva sem
    correção) mesmo quando a pose do SLAM tinha sido gravada — inflando
    RMSE/erro final por deriva de odometria, não por repetibilidade real."""

    def test_find_slam_pose_topic_name_matches_bare_pose(self):
        tmap = {"/pose": "geometry_msgs/msg/PoseWithCovarianceStamped", "/odom": "nav_msgs/msg/Odometry"}
        self.assertEqual(_find_slam_pose_topic_name(tmap), "/pose")

    def test_find_slam_pose_topic_name_matches_namespaced_pose(self):
        tmap = {"/tb1/pose": "geometry_msgs/msg/PoseWithCovarianceStamped"}
        self.assertEqual(_find_slam_pose_topic_name(tmap), "/tb1/pose")

    def test_find_slam_pose_topic_name_not_confused_by_amcl_pose(self):
        tmap = {"/amcl_pose": "geometry_msgs/msg/PoseWithCovarianceStamped"}
        self.assertIsNone(_find_slam_pose_topic_name(tmap))

    def test_auto_mode_prefers_slam_pose_over_odom_when_recorded(self):
        tmap = {
            "/pose": "geometry_msgs/msg/PoseWithCovarianceStamped",
            "/odom": "nav_msgs/msg/Odometry",
        }
        counts = {"/pose": 42, "/odom": 42}

        topic = _resolve_trajectory_topic("fake_uri", "auto", tmap=tmap, counts=counts)

        self.assertEqual(topic, "/pose")

    def test_auto_mode_still_prefers_amcl_pose_over_slam_pose(self):
        tmap = {
            "/amcl_pose": "geometry_msgs/msg/PoseWithCovarianceStamped",
            "/pose": "geometry_msgs/msg/PoseWithCovarianceStamped",
            "/odom": "nav_msgs/msg/Odometry",
        }
        counts = {"/amcl_pose": 10, "/pose": 42, "/odom": 42}

        topic = _resolve_trajectory_topic("fake_uri", "auto", tmap=tmap, counts=counts)

        self.assertEqual(topic, "/amcl_pose")

    def test_auto_mode_falls_back_to_odom_when_slam_pose_has_no_messages(self):
        tmap = {
            "/pose": "geometry_msgs/msg/PoseWithCovarianceStamped",
            "/odom": "nav_msgs/msg/Odometry",
        }
        counts = {"/pose": 0, "/odom": 42}

        topic = _resolve_trajectory_topic("fake_uri", "auto", tmap=tmap, counts=counts)

        self.assertEqual(topic, "/odom")

    def test_slam_pose_mode_raises_when_topic_missing(self):
        tmap = {"/odom": "nav_msgs/msg/Odometry"}

        with self.assertRaises(RuntimeError):
            _resolve_trajectory_topic("fake_uri", "slam_pose", tmap=tmap, counts={})

    def test_slam_pose_mode_raises_when_topic_has_no_messages(self):
        tmap = {"/pose": "geometry_msgs/msg/PoseWithCovarianceStamped"}
        counts = {"/pose": 0}

        with self.assertRaises(RuntimeError):
            _resolve_trajectory_topic("fake_uri", "slam_pose", tmap=tmap, counts=counts)

    def test_slam_pose_mode_returns_topic_when_present(self):
        tmap = {"/tb2/pose": "geometry_msgs/msg/PoseWithCovarianceStamped"}
        counts = {"/tb2/pose": 5}

        topic = _resolve_trajectory_topic("fake_uri", "slam_pose", tmap=tmap, counts=counts)

        self.assertEqual(topic, "/tb2/pose")


if __name__ == "__main__":
    unittest.main()
