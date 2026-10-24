import json
import sys
import unittest
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import main as backend_main  # noqa: E402
from agents.executor import Executor, ExecutorError  # noqa: E402


def _fake_run_service(service, service_type, request_json, timeout=10):
    """Substitui RosBridge.run_service: sem ROS 2, sem subprocess, respostas fixas.
    O formato de list_robots/list_routes espelha a saída REAL de
    `ros2 service call` (prosa + repr do Python após "response:") — não é
    YAML, nunca foi; ver RosBridge.extract_list_field e o teste de
    regressão em test_ros_bridge.py que capturou isso ao vivo."""
    req = json.loads(request_json) if request_json else {}
    if service == "list_robots":
        return True, "response:\nfleet_msgs.srv.ListRobots_Response(robot_ids=['tb1', 'tb2'])"
    if service == "list_routes":
        return True, "response:\nfleet_msgs.srv.ListRoutes_Response(route_names=['percurso1'])"
    if service in (
        "start_record", "stop_record", "play_route", "go_to_point",
        "cancel", "enable_collection", "disable_collection",
    ):
        return True, f"ok:{service}:{req.get('robot_id', '')}"
    return False, f"unknown service {service}"


class ExecutorIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Executor falando HTTP de verdade com o app FastAPI real, só trocando a
    fronteira ROS 2 (RosBridge.run_service) por respostas fixas."""

    async def asyncSetUp(self):
        self._orig_run_service = backend_main._bridge.run_service
        backend_main._bridge.run_service = _fake_run_service
        transport = httpx.ASGITransport(app=backend_main.app)
        self.executor = Executor(base_url="http://test", transport=transport)

    async def asyncTearDown(self):
        backend_main._bridge.run_service = self._orig_run_service
        await self.executor.aclose()

    async def test_list_robots_and_routes(self):
        self.assertEqual(await self.executor.list_robots(), ["tb1", "tb2"])
        self.assertEqual(await self.executor.list_routes(), ["percurso1"])

    async def test_move_and_recording_roundtrip(self):
        self.assertTrue((await self.executor.move_robot("tb1", 1.0, 2.0, 0.5))["success"])
        self.assertTrue((await self.executor.start_recording("tb1", "rota_x"))["success"])
        self.assertTrue((await self.executor.stop_recording("tb1"))["success"])
        self.assertTrue((await self.executor.replay_route("tb1", "rota_x"))["success"])
        self.assertTrue((await self.executor.cancel("tb1"))["success"])

    async def test_collection_roundtrip(self):
        self.assertTrue((await self.executor.start_collection("tb1", ["scan", "odom"]))["success"])
        self.assertTrue((await self.executor.stop_collection("tb1"))["success"])

    async def test_get_robot_status_not_found_raises(self):
        with self.assertRaises(ExecutorError):
            await self.executor.get_robot_status("does-not-exist")

    async def test_get_job_missing_raises(self):
        with self.assertRaises(ExecutorError):
            await self.executor.get_job("nope")


if __name__ == "__main__":
    unittest.main()
