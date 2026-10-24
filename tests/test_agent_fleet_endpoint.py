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
from agents.planner import PlanResult  # noqa: E402


class FakeScopedPlanner:
    """Substitui o Planner real: registra com qual robot_id cada instância foi
    criada, para provar que /api/agent/run_fleet escopa 1 agente por robô."""

    calls: list[tuple[str | None, str]] = []

    def __init__(self, executor, analyst, *, model="claude-sonnet-5", api_key=None, max_turns=12, robot_id=None):
        self.robot_id = robot_id

    async def run(self, instruction: str) -> PlanResult:
        FakeScopedPlanner.calls.append((self.robot_id, instruction))
        return PlanResult(final_text=f"{self.robot_id}: {instruction}", steps=[])


class AgentFleetEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._orig_planner = backend_main.Planner
        self._orig_key = os.environ.get("ANTHROPIC_API_KEY")
        self._orig_runs_dir = backend_main._AGENT_RUNS_DIR
        self._tmp_runs_dir = tempfile.TemporaryDirectory()
        os.environ["ANTHROPIC_API_KEY"] = "test-key"
        backend_main.Planner = FakeScopedPlanner
        backend_main._AGENT_RUNS_DIR = Path(self._tmp_runs_dir.name)
        FakeScopedPlanner.calls = []
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

    async def _poll(self, job_id: str) -> dict:
        job = None
        for _ in range(50):
            job = (await self.client.get(f"/api/agent/fleet_job/{job_id}")).json()
            if not job["running"]:
                return job
            await asyncio.sleep(0.01)
        raise AssertionError("fleet job never finished running")

    async def test_missing_instructions_returns_400(self):
        resp = await self.client.post("/api/agent/run_fleet", json={"instructions": {}})
        self.assertEqual(resp.status_code, 400)

    async def test_each_robot_gets_its_own_scoped_agent(self):
        resp = await self.client.post("/api/agent/run_fleet", json={
            "instructions": {"tb1": "vá para o ponto A", "tb2": "grave a rota B", "tb3": "reproduza a rota C"},
        })
        self.assertEqual(resp.status_code, 200)
        job = await self._poll(resp.json()["job_id"])

        self.assertEqual(job["robots"]["tb1"]["final_text"], "tb1: vá para o ponto A")
        self.assertEqual(job["robots"]["tb2"]["final_text"], "tb2: grave a rota B")
        self.assertEqual(job["robots"]["tb3"]["final_text"], "tb3: reproduza a rota C")
        self.assertEqual(
            set(FakeScopedPlanner.calls),
            {
                ("tb1", "vá para o ponto A"),
                ("tb2", "grave a rota B"),
                ("tb3", "reproduza a rota C"),
            },
        )

    async def test_unknown_fleet_job_returns_404(self):
        resp = await self.client.get("/api/agent/fleet_job/does-not-exist")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
