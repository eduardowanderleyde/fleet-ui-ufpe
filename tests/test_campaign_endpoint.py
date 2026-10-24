import json
import shutil
import sys
import unittest
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import main as backend_main  # noqa: E402
from agents.executor import Executor  # noqa: E402


class CampaignIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Executa /api/run_campaign contra o app FastAPI real, trocando só a
    fronteira de subprocess (RosBridge.run_experiment_step/analyze_bags) por
    fakes — prova que a orquestração (baseline + N replays -> analyze_runs.py)
    está certa sem precisar de ROS/Gazebo de verdade."""

    RUN_ID = "test_campaign_xyz"

    async def asyncSetUp(self):
        self._orig_step = backend_main._bridge.run_experiment_step
        self._orig_analyze = backend_main._bridge.analyze_bags
        self.step_calls: list[str] = []
        self.analyze_calls: list[tuple] = []

        def fake_step(cmd, export_path, line_callback=None):
            self.step_calls.append(cmd[2])  # argv[2] = "record" ou "replay"
            if line_callback:
                line_callback(f"[fake] {cmd[2]}")
            idx = len(self.step_calls)
            return {
                "lines": [f"[fake] {cmd[2]}"],
                "result": {"success": True, "rosbag_path": f"/fake/bag_{idx}"},
                "error": None,
                "exit_code": 0,
            }

        def fake_analyze(bag_paths, labels, output_dir, timeout=180):
            self.analyze_calls.append((bag_paths, labels, output_dir))
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / "summary.json").write_text(json.dumps({
                "labels": labels,
                "reference_label": labels[0],
                "runs": [{"label": l} for l in labels],
                "pairwise_rmse_m": [[0.0] * len(labels) for _ in labels],
                "vs_reference": [{"label": l, "rmse_vs_ref_m": 0.0} for l in labels],
            }))
            return True, "ok"

        backend_main._bridge.run_experiment_step = fake_step
        backend_main._bridge.analyze_bags = fake_analyze
        transport = httpx.ASGITransport(app=backend_main.app)
        self.executor = Executor(base_url="http://test", transport=transport)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://test")

    async def asyncTearDown(self):
        backend_main._bridge.run_experiment_step = self._orig_step
        backend_main._bridge.analyze_bags = self._orig_analyze
        backend_main._campaign_jobs.pop(self.RUN_ID, None)
        await self.executor.aclose()
        await self.client.aclose()
        run_dir = Path(backend_main.ROS_WS) / "runs" / self.RUN_ID
        shutil.rmtree(run_dir, ignore_errors=True)

    async def test_campaign_runs_baseline_plus_repetitions_and_analyzes(self):
        run_id = await self.executor.run_campaign({
            "robot": "default",
            "route": "rota_teste",
            "points": [[1, 0, 0], [2, 0, 0]],
            "repetitions": 2,
            "run_id": self.RUN_ID,
        })
        self.assertEqual(run_id, self.RUN_ID)

        job = await self.executor.wait_for_campaign_job(run_id, poll_interval=0.01, timeout=5)

        self.assertFalse(job["running"])
        self.assertIsNone(job["error"])
        self.assertEqual(self.step_calls, ["record", "replay", "replay"])
        self.assertEqual([s["label"] for s in job["steps"]], ["baseline", "replay_01", "replay_02"])
        self.assertEqual(self.analyze_calls[0][0], ["/fake/bag_1", "/fake/bag_2", "/fake/bag_3"])
        self.assertEqual(self.analyze_calls[0][1], ["baseline", "replay_01", "replay_02"])
        self.assertEqual(job["summary"]["labels"], ["baseline", "replay_01", "replay_02"])

    async def test_campaign_stops_and_reports_error_when_a_step_fails(self):
        def failing_step(cmd, export_path, line_callback=None):
            self.step_calls.append(cmd[2])
            return {"lines": [], "result": None, "error": "boom", "exit_code": 1}

        backend_main._bridge.run_experiment_step = failing_step

        run_id = await self.executor.run_campaign({
            "route": "rota_teste", "points": [[1, 0, 0]], "repetitions": 3, "run_id": self.RUN_ID,
        })
        job = await self.executor.wait_for_campaign_job(run_id, poll_interval=0.01, timeout=5)

        self.assertFalse(job["running"])
        self.assertIsNotNone(job["error"])
        self.assertEqual(self.step_calls, ["record"])  # não tentou os replays após a falha
        self.assertEqual(self.analyze_calls, [])  # nunca chegou a chamar analyze_runs.py

    async def test_repetitions_below_one_rejected(self):
        resp = await self.client.post("/api/run_campaign", json={
            "route": "r", "points": [[0, 0, 0]], "repetitions": 0,
        })
        self.assertEqual(resp.status_code, 400)

    async def test_unknown_campaign_job_returns_404(self):
        resp = await self.client.get("/api/campaign_job/does-not-exist")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
