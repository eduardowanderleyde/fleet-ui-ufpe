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
    def __init__(self, *args, **kwargs):
        pass

    async def run(self, instruction: str) -> PlanResult:
        return PlanResult(
            final_text=f"echo: {instruction}",
            steps=[PlanStep(tool_name="list_robots", tool_input={}, result=["tb1"])],
        )


class AgentPersistenceTests(unittest.IsolatedAsyncioTestCase):
    """Prova que um job de agente sobrevive a um "restart" do backend (limpar os
    dicts em memória) e aparece em /api/agent/history — a lacuna que motivou
    _save_agent_run/_load_agent_run."""

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

    async def _wait_finished(self, path: str) -> dict:
        job = None
        for _ in range(50):
            job = (await self.client.get(path)).json()
            if not job.get("running"):
                return job
            await asyncio.sleep(0.01)
        raise AssertionError(f"job at {path} never finished")

    async def test_single_job_survives_in_memory_dict_being_cleared(self):
        resp = await self.client.post("/api/agent/run", json={"instruction": "liste os robôs"})
        job_id = resp.json()["job_id"]
        await self._wait_finished(f"/api/agent/job/{job_id}")

        # Simula um restart do backend: o dict em memória some, só o disco resta.
        backend_main._agent_jobs.pop(job_id, None)

        reloaded = (await self.client.get(f"/api/agent/job/{job_id}")).json()
        self.assertEqual(reloaded["instruction"], "liste os robôs")
        self.assertEqual(reloaded["final_text"], "echo: liste os robôs")
        self.assertFalse(reloaded["running"])
        self.assertIsNotNone(reloaded["started_at"])
        self.assertIsNotNone(reloaded["finished_at"])

    async def test_fleet_job_survives_in_memory_dict_being_cleared(self):
        resp = await self.client.post("/api/agent/run_fleet", json={"instructions": {"tb1": "oi"}})
        job_id = resp.json()["job_id"]
        await self._wait_finished(f"/api/agent/fleet_job/{job_id}")

        backend_main._fleet_jobs.pop(job_id, None)

        reloaded = (await self.client.get(f"/api/agent/fleet_job/{job_id}")).json()
        self.assertEqual(reloaded["robots"]["tb1"]["final_text"], "echo: oi")
        self.assertFalse(reloaded["running"])

    async def test_history_lists_finished_runs_most_recent_first(self):
        r1 = await self.client.post("/api/agent/run", json={"instruction": "primeira"})
        await self._wait_finished(f"/api/agent/job/{r1.json()['job_id']}")
        r2 = await self.client.post("/api/agent/run_fleet", json={"instructions": {"tb1": "segunda"}})
        await self._wait_finished(f"/api/agent/fleet_job/{r2.json()['job_id']}")

        history = (await self.client.get("/api/agent/history")).json()["runs"]

        self.assertEqual(len(history), 2)
        kinds = {r["kind"] for r in history}
        self.assertEqual(kinds, {"single", "fleet"})
        single_entry = next(r for r in history if r["kind"] == "single")
        self.assertEqual(single_entry["instruction"], "primeira")
        fleet_entry = next(r for r in history if r["kind"] == "fleet")
        self.assertEqual(fleet_entry["robots"]["tb1"]["instruction"], "segunda")

    async def test_history_empty_when_nothing_persisted_yet(self):
        history = (await self.client.get("/api/agent/history")).json()
        self.assertEqual(history["runs"], [])


if __name__ == "__main__":
    unittest.main()
