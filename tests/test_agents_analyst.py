import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from agents.analyst import Analyst, AnalystError  # noqa: E402


SUMMARY = {
    "reference_label": "baseline",
    "labels": ["baseline", "replay_01", "replay_02"],
    "runs": [
        {"label": "baseline", "duration_sec": 18.0, "path_length_m": 0.25},
        {"label": "replay_01", "duration_sec": 10.0, "path_length_m": 0.05},
        {"label": "replay_02", "duration_sec": 9.5, "path_length_m": 0.0},
    ],
    "pairwise_rmse_m": [
        [0.0, 0.02, 0.08],
        [0.02, 0.0, 0.06],
        [0.08, 0.06, 0.0],
    ],
    "vs_reference": [
        {"label": "baseline", "rmse_vs_ref_m": 0.0},
        {"label": "replay_01", "rmse_vs_ref_m": 0.02},
        {"label": "replay_02", "rmse_vs_ref_m": 0.08},
    ],
}


class AnalystTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        runs_dir = Path(self.tmp.name)
        (runs_dir / "campaign01" / "analysis").mkdir(parents=True)
        (runs_dir / "campaign01" / "analysis" / "summary.json").write_text(json.dumps(SUMMARY))
        self.analyst = Analyst(runs_dir=runs_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_analyze_experiment_flags_runs_above_threshold(self):
        result = self.analyst.analyze_experiment("campaign01", rmse_threshold_m=0.05)

        self.assertEqual(result["num_runs"], 3)
        self.assertEqual([r["label"] for r in result["flagged_runs"]], ["replay_02"])
        self.assertAlmostEqual(result["max_rmse_vs_ref_m"], 0.08)

    def test_compare_runs_reads_pairwise_matrix(self):
        result = self.analyst.compare_runs("campaign01", "replay_01", "replay_02")

        self.assertAlmostEqual(result["rmse_m"], 0.06)
        self.assertEqual(result["duration_sec_a"], 10.0)
        self.assertEqual(result["duration_sec_b"], 9.5)

    def test_missing_run_raises(self):
        with self.assertRaises(AnalystError):
            self.analyst.load_summary("does_not_exist")


DIAGNOSE_SUMMARY = {
    "reference_label": "baseline",
    "labels": ["baseline", "static_run", "short_run", "long_run", "endpoint_miss_run", "unknown_run"],
    "runs": [
        {"label": "baseline", "duration_sec": 20.0, "path_length_m": 1.0, "num_poses": 200, "static_traj_warn": False},
        {"label": "static_run", "duration_sec": 5.0, "path_length_m": 0.0, "num_poses": 50, "static_traj_warn": True},
        {"label": "short_run", "duration_sec": 6.0, "path_length_m": 0.9, "num_poses": 60, "static_traj_warn": False},
        {"label": "long_run", "duration_sec": 40.0, "path_length_m": 1.1, "num_poses": 300, "static_traj_warn": False},
        {"label": "endpoint_miss_run", "duration_sec": 19.0, "path_length_m": 1.0, "num_poses": 190, "static_traj_warn": False},
        {"label": "unknown_run", "duration_sec": 20.5, "path_length_m": 1.05, "num_poses": 205, "static_traj_warn": False},
    ],
    "pairwise_rmse_m": [[0.0] * 6 for _ in range(6)],  # não usado nesses testes
    "vs_reference": [
        {"label": "baseline", "rmse_vs_ref_m": 0.0, "duration_ratio_vs_ref": 1.0, "final_endpoint_error_m": 0.0},
        {"label": "static_run", "rmse_vs_ref_m": 0.20, "duration_ratio_vs_ref": 0.25, "final_endpoint_error_m": 0.15},
        {"label": "short_run", "rmse_vs_ref_m": 0.10, "duration_ratio_vs_ref": 0.3, "final_endpoint_error_m": 0.05},
        {"label": "long_run", "rmse_vs_ref_m": 0.09, "duration_ratio_vs_ref": 2.0, "final_endpoint_error_m": 0.04},
        {"label": "endpoint_miss_run", "rmse_vs_ref_m": 0.06, "duration_ratio_vs_ref": 1.0, "final_endpoint_error_m": 0.20},
        {"label": "unknown_run", "rmse_vs_ref_m": 0.06, "duration_ratio_vs_ref": 1.02, "final_endpoint_error_m": 0.03},
    ],
}


class AnalystDiagnoseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        runs_dir = Path(self.tmp.name)
        (runs_dir / "diag01" / "analysis").mkdir(parents=True)
        (runs_dir / "diag01" / "analysis" / "summary.json").write_text(json.dumps(DIAGNOSE_SUMMARY))
        self.analyst = Analyst(runs_dir=runs_dir)

    def tearDown(self):
        self.tmp.cleanup()

    def _hypothesis_for(self, result: dict, label: str) -> str:
        entry = next(r for r in result["flagged_runs"] if r["label"] == label)
        return entry["hypothesis"]

    def test_flags_same_runs_as_analyze_experiment(self):
        result = self.analyst.diagnose_experiment("diag01")

        flagged_labels = {r["label"] for r in result["flagged_runs"]}
        self.assertEqual(
            flagged_labels,
            {"static_run", "short_run", "long_run", "endpoint_miss_run", "unknown_run"},
        )

    def test_static_trajectory_takes_priority_over_short_duration(self):
        """static_run também tem duration_ratio=0.25 (curto) — a hipótese
        principal tem que ser a estática, não a de duração (mais severa/
        mais específica), mas ambos os sinais devem aparecer."""
        result = self.analyst.diagnose_experiment("diag01")
        entry = next(r for r in result["flagged_runs"] if r["label"] == "static_run")

        self.assertIn("estática", entry["hypothesis"])
        self.assertEqual(len(entry["signals"]), 2)

    def test_short_duration_hypothesis(self):
        result = self.analyst.diagnose_experiment("diag01")
        self.assertIn("abortado", self._hypothesis_for(result, "short_run"))

    def test_long_duration_hypothesis(self):
        result = self.analyst.diagnose_experiment("diag01")
        self.assertIn("recovery", self._hypothesis_for(result, "long_run"))

    def test_endpoint_mismatch_hypothesis(self):
        result = self.analyst.diagnose_experiment("diag01")
        self.assertIn("não convergiu no destino", self._hypothesis_for(result, "endpoint_miss_run"))

    def test_unknown_cause_falls_back_to_generic_hypothesis(self):
        result = self.analyst.diagnose_experiment("diag01")
        self.assertIn("sem sinais óbvios", self._hypothesis_for(result, "unknown_run"))

    def test_diagnose_experiment_keeps_analyze_experiment_summary_fields(self):
        """diagnose_experiment não deveria jogar fora os números que
        analyze_experiment já calcula, só enriquecer flagged_runs."""
        result = self.analyst.diagnose_experiment("diag01", rmse_threshold_m=0.05)

        self.assertEqual(result["run_id"], "diag01")
        self.assertEqual(result["rmse_threshold_m"], 0.05)
        self.assertIn("mean_rmse_vs_ref_m", result)


if __name__ == "__main__":
    unittest.main()
