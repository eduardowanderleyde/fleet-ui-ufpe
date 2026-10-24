import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import main as backend_main  # noqa: E402


class FakeProc:
    """Substitui subprocess.Popen: .stdout itera linhas fixas, .pid/.poll()
    não tocam em processo real nenhum — os.killpg/os.getpgid também são
    trocados por fakes no teardown, então nada aqui chama o kernel de verdade."""

    def __init__(self, lines, pid):
        self._lines = list(lines)
        self.pid = pid
        self.terminated = False

    @property
    def stdout(self):
        return iter(self._lines)

    def poll(self):
        return 0 if self.terminated else None


class SimulationEndpointTests(unittest.IsolatedAsyncioTestCase):
    """/api/simulation/* contra o app FastAPI real, só trocando a fronteira de
    processo (subprocess.Popen, os.killpg/os.getpgid, time.sleep) por fakes —
    prova a máquina de estados (running/ready/error, detecção de prontidão
    via 'Managed nodes are active' + 'fleet_orchestrator ready', rejeição de
    início duplicado, parada) sem precisar de ROS/Gazebo de verdade."""

    async def asyncSetUp(self):
        self.fake_procs: list[FakeProc] = []
        self.popen_calls: list[list[str]] = []
        self.popen_envs: list[dict] = []
        self.killpg_calls: list[int] = []
        self._next_pid = 1000

        def fake_popen(argv, **kwargs):
            self.popen_calls.append(argv)
            self.popen_envs.append(kwargs.get("env") or {})
            lines = self._pending_lines.pop(0) if self._pending_lines else []
            self._next_pid += 1
            proc = FakeProc(lines, self._next_pid)
            self.fake_procs.append(proc)
            return proc

        self._pending_lines: list[list[str]] = []
        self._popen_patch = patch.object(backend_main.subprocess, "Popen", side_effect=fake_popen)
        self._popen_patch.start()
        def fake_killpg(pgid, sig):
            self.killpg_calls.append(pgid)
            for p in self.fake_procs:
                if p.pid == pgid:
                    p.terminated = True  # simula o processo realmente morrendo no SIGTERM

        self._killpg_patch = patch.object(backend_main.os, "killpg", side_effect=fake_killpg)
        self._killpg_patch.start()
        self._getpgid_patch = patch.object(backend_main.os, "getpgid", side_effect=lambda pid: pid)
        self._getpgid_patch.start()
        self._sleep_patch = patch.object(backend_main.time, "sleep", lambda *_: None)
        self._sleep_patch.start()
        # _stop_simulation() também roda um pkill de segurança via
        # subprocess.run (não Popen) — sem isso, herdaria o fake_popen acima
        # (que devolve um FakeProc sem suporte a "with", quebrando o
        # subprocess.run real por dentro).
        self.pkill_calls: list[list[str]] = []
        self._run_patch = patch.object(
            backend_main.subprocess, "run",
            side_effect=lambda argv, **kwargs: self.pkill_calls.append(argv),
        )
        self._run_patch.start()

        transport = httpx.ASGITransport(app=backend_main.app)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://test")

    async def asyncTearDown(self):
        backend_main._stop_simulation()
        for p in (self._popen_patch, self._killpg_patch, self._getpgid_patch, self._sleep_patch, self._run_patch):
            p.stop()
        await self.client.aclose()

    async def _wait_until(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            await asyncio.sleep(0.02)
        return False

    async def test_options_lists_worlds_and_robots_from_roles_yaml(self):
        resp = await self.client.get("/api/simulation/options")
        data = resp.json()
        self.assertEqual(data["worlds"], ["warehouse", "depot"])
        self.assertIn("tb1", data["robots"])
        self.assertIn("tb1", data["roles"])
        self.assertEqual(data["roles"]["tb1"], "MUUT")

    async def test_single_mode_becomes_ready_after_markers_from_both_processes(self):
        self._pending_lines = [
            ["Activating bt_navigator", "Managed nodes are active"],  # sim
            ["fleet_orchestrator ready robots=['']"],                  # fleet
        ]
        resp = await self.client.post("/api/simulation/start", json={"mode": "single", "world": "warehouse"})
        self.assertEqual(resp.status_code, 200)

        ok = await self._wait_until(lambda: backend_main._sim_state["ready"] is True)
        self.assertTrue(ok, backend_main._sim_state)
        self.assertEqual(len(self.popen_calls), 2)
        self.assertIn("turtlebot4_sim.launch.py", self.popen_calls[0][2])
        self.assertIn("headless:=True", self.popen_calls[0][2])  # PythonExpression do vendor exige "True" maiúsculo
        self.assertIn("single_robot_sim:=true", self.popen_calls[1][2])

    async def test_multi_mode_needs_one_ready_marker_per_robot(self):
        self._pending_lines = [
            ["Managed nodes are active"],  # só 1 de 2 esperados
            ["fleet_orchestrator ready robots=['tb1', 'tb2']"],
        ]
        resp = await self.client.post(
            "/api/simulation/start",
            json={"mode": "multi", "world": "depot", "robots": ["tb1", "tb2"]},
        )
        self.assertEqual(resp.status_code, 200)

        await asyncio.sleep(0.1)  # dá tempo das threads leitoras consumirem as linhas fake
        self.assertFalse(backend_main._sim_state["ready"])  # só 1 de 2 robôs sinalizou pronto
        self.assertEqual(self.popen_envs[0].get("FLEET_ROBOTS"), "tb1,tb2")

    async def test_stale_nav2_state_from_previous_session_does_not_fake_ready(self):
        """Achado ao vivo: nav2_ready_robots/robots (escritos por nav2_check_cb/
        fleet_cb, timers de longa duração que nunca são resetados) sobreviviam
        de uma sessão anterior e faziam o cross-check de /api/simulation/status
        reportar ready=true pra uma sessão NOVA em t=+0s, antes de qualquer
        processo da simulação atual sequer ter subido."""
        import time as _time
        # Estado deixado por uma sessão ANTERIOR já encerrada — tb1/tb2 nav2_ready
        # de verdade, só que antes de existir qualquer sessão nova.
        with backend_main._status_lock:
            backend_main._fleet_status["nav2_ready_robots"] = ["tb1", "tb2"]
            backend_main._fleet_status["nav2_ready_robots_at"] = _time.monotonic()
            backend_main._fleet_status["robots"] = [{"robot_id": "tb1"}, {"robot_id": "tb2"}]
            backend_main._fleet_status["robots_at"] = _time.monotonic()

        self._pending_lines = [[], []]  # nada de "Managed nodes are active" — só o cross-check poderia marcar ready
        resp = await self.client.post(
            "/api/simulation/start",
            json={"mode": "multi", "world": "warehouse", "robots": ["tb1", "tb2"]},
        )
        self.assertEqual(resp.status_code, 200)

        status = (await self.client.get("/api/simulation/status")).json()
        self.assertFalse(status["ready"], "dado stale de sessão anterior não deveria contar como pronto")

        # Agora simula nav2_check_cb/fleet_cb rodando de verdade, DEPOIS do início desta sessão.
        with backend_main._status_lock:
            backend_main._fleet_status["nav2_ready_robots_at"] = _time.monotonic()
            backend_main._fleet_status["robots_at"] = _time.monotonic()
        status = (await self.client.get("/api/simulation/status")).json()
        self.assertTrue(status["ready"], "dado fresco pós-início da sessão deveria marcar ready")

    async def test_bringup_failure_sets_error_without_stopping(self):
        self._pending_lines = [
            ["Failed to activate global_costmap...", "Aborting bringup"],
            [],
        ]
        resp = await self.client.post("/api/simulation/start", json={"mode": "single"})
        self.assertEqual(resp.status_code, 200)

        ok = await self._wait_until(lambda: backend_main._sim_state["error"] is not None)
        self.assertTrue(ok, backend_main._sim_state)
        self.assertTrue(backend_main._sim_state["running"])  # não mata sozinho

    async def test_start_rejected_with_409_when_already_running(self):
        self._pending_lines = [[], []]
        first = await self.client.post("/api/simulation/start", json={"mode": "single"})
        self.assertEqual(first.status_code, 200)

        second = await self.client.post("/api/simulation/start", json={"mode": "single"})
        self.assertEqual(second.status_code, 409)

    async def test_stop_kills_both_process_groups_and_resets_state(self):
        self._pending_lines = [[], []]
        await self.client.post("/api/simulation/start", json={"mode": "single"})
        self.assertTrue(backend_main._sim_state["running"])

        resp = await self.client.post("/api/simulation/stop")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.killpg_calls), 2)  # sim + fleet
        self.assertFalse(backend_main._sim_state["running"])
        self.assertEqual(backend_main._sim_state["lines"], [])

    async def test_activate_robot_rejected_without_running_simulation(self):
        resp = await self.client.post("/api/simulation/activate_robot", params={"robot_id": "tb1"})
        self.assertEqual(resp.status_code, 409)

    async def test_activate_robot_rejected_for_robot_outside_current_simulation(self):
        self._pending_lines = [[], []]
        await self.client.post(
            "/api/simulation/start",
            json={"mode": "multi", "world": "warehouse", "robots": ["tb1", "tb2"]},
        )
        resp = await self.client.post("/api/simulation/activate_robot", params={"robot_id": "tb3"})
        self.assertEqual(resp.status_code, 400)

    async def test_activate_then_deactivate_robot_launches_and_kills_process_group(self):
        self._pending_lines = [[], [], []]  # sim, fleet, activate_robot_nav
        await self.client.post(
            "/api/simulation/start",
            json={"mode": "multi", "world": "warehouse", "robots": ["tb1", "tb2"], "sequential_nav": True},
        )
        self.assertIn("bringup_nav:=false", self.popen_calls[0][-1])

        resp = await self.client.post("/api/simulation/activate_robot", params={"robot_id": "tb1"})
        self.assertEqual(resp.status_code, 200)
        await asyncio.sleep(0.05)
        self.assertIn("tb1", backend_main._robot_nav_procs)
        self.assertIn("namespace:=tb1", self.popen_calls[-1][-1])

        resp = await self.client.post("/api/simulation/deactivate_robot", params={"robot_id": "tb1"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("tb1", backend_main._robot_nav_procs)
        self.assertIn(self.fake_procs[-1].pid, self.killpg_calls)

    async def test_stop_simulation_also_cleans_up_active_robot_nav(self):
        self._pending_lines = [[], [], []]
        await self.client.post(
            "/api/simulation/start",
            json={"mode": "multi", "world": "warehouse", "robots": ["tb1", "tb2"], "sequential_nav": True},
        )
        await self.client.post("/api/simulation/activate_robot", params={"robot_id": "tb1"})
        await asyncio.sleep(0.05)
        self.assertIn("tb1", backend_main._robot_nav_procs)

        await self.client.post("/api/simulation/stop")
        self.assertEqual(backend_main._robot_nav_procs, {})


if __name__ == "__main__":
    unittest.main()
