import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import main as backend_main  # noqa: E402
from agents.planner import PlanResult, PlanStep  # noqa: E402


class FakePlanner:
    """Substitui o Planner real: sem chamada de rede à Anthropic."""

    def __init__(self, *args, **kwargs):
        pass

    async def run(self, instruction: str) -> PlanResult:
        return PlanResult(
            final_text=f"echo: {instruction}",
            steps=[PlanStep(tool_name="list_robots", tool_input={}, result=["tb1"])],
        )


class AgentEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._orig_planner = backend_main.Planner
        self._orig_key = os.environ.get("ANTHROPIC_API_KEY")
        self._orig_runs_dir = backend_main._AGENT_RUNS_DIR
        self._tmp_runs_dir = tempfile.TemporaryDirectory()
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        backend_main.Planner = FakePlanner
        backend_main._AGENT_RUNS_DIR = Path(self._tmp_runs_dir.name)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=backend_main.app), base_url="http://test"
        )

    async def asyncTearDown(self):
        backend_main.Planner = self._orig_planner
        backend_main._AGENT_RUNS_DIR = self._orig_runs_dir
        self._tmp_runs_dir.cleanup()
        if self._orig_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = self._orig_key
        await self.client.aclose()

    async def test_missing_instruction_returns_400(self):
        resp = await self.client.post("/api/agent/run", json={"instruction": ""})
        self.assertEqual(resp.status_code, 400)

    async def test_missing_api_key_returns_400(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        resp = await self.client.post("/api/agent/run", json={"instruction": "oi"})
        self.assertEqual(resp.status_code, 400)

    async def test_run_and_poll_job_to_completion(self):
        resp = await self.client.post("/api/agent/run", json={"instruction": "liste os robôs"})
        self.assertEqual(resp.status_code, 200)
        job_id = resp.json()["job_id"]

        job = None
        for _ in range(50):
            job = (await self.client.get(f"/api/agent/job/{job_id}")).json()
            if not job["running"]:
                break
            await asyncio.sleep(0.01)

        self.assertIsNotNone(job)
        self.assertFalse(job["running"])
        self.assertIsNone(job["error"])
        self.assertEqual(job["final_text"], "echo: liste os robôs")
        self.assertEqual(job["steps"][0]["tool_name"], "list_robots")

    async def test_unknown_job_returns_404(self):
        resp = await self.client.get("/api/agent/job/does-not-exist")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
