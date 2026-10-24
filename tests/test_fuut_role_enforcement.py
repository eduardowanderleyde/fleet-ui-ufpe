import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import main as backend_main  # noqa: E402


class FuutRoleEnforcementTests(unittest.IsolatedAsyncioTestCase):
    """Prova que play_route/go_to_point/start_record/stop_record rejeitam
    robôs não-MUUT (FUUT, SU, papel ausente) com 403, e que MUUT continua
    funcionando sem mudança de comportamento — sem precisar de ROS/Gazebo
    de verdade (_run_ros2_service é trocado por fake)."""

    async def asyncSetUp(self):
        self._roles = {"tb1": "MUUT", "tb2": "FUUT", "tb3": "SU"}
        self._roles_patch = patch.object(
            backend_main, "_read_robot_roles", side_effect=lambda: dict(self._roles)
        )
        self._roles_patch.start()

        self.ros2_calls: list[tuple] = []

        def fake_run_ros2_service(service, srv_type, payload):
            self.ros2_calls.append((service, srv_type, payload))
            return True, "ok"

        self._ros2_patch = patch.object(
            backend_main, "_run_ros2_service", side_effect=fake_run_ros2_service
        )
        self._ros2_patch.start()

        transport = httpx.ASGITransport(app=backend_main.app)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self._ros2_patch.stop()
        self._roles_patch.stop()

    async def _assert_rejected(self, path: str, robot_id: str, **extra):
        resp = await self.client.post(path, params={"robot_id": robot_id, **extra})
        self.assertEqual(resp.status_code, 403, resp.text)
        self.assertEqual(self.ros2_calls, [])

    async def _assert_allowed(self, path: str, robot_id: str, **extra):
        before = len(self.ros2_calls)
        resp = await self.client.post(path, params={"robot_id": robot_id, **extra})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.json()["success"])
        self.assertEqual(len(self.ros2_calls), before + 1)

    async def test_fuut_rejected_on_play_route(self):
        await self._assert_rejected("/api/play_route", "tb2", route_name="r1")

    async def test_su_rejected_on_go_to_point(self):
        await self._assert_rejected("/api/go_to_point", "tb3", x=1.0, y=2.0, yaw=0.0)

    async def test_unknown_robot_id_rejected(self):
        await self._assert_rejected("/api/go_to_point", "tb_desconhecido", x=1.0, y=2.0, yaw=0.0)

    async def test_fuut_rejected_on_start_record(self):
        await self._assert_rejected("/api/start_record", "tb2", route_name="r1")

    async def test_fuut_rejected_on_stop_record(self):
        await self._assert_rejected("/api/stop_record", "tb2")

    async def test_muut_allowed_on_play_route(self):
        await self._assert_allowed("/api/play_route", "tb1", route_name="r1")

    async def test_muut_allowed_on_go_to_point(self):
        await self._assert_allowed("/api/go_to_point", "tb1", x=1.0, y=2.0, yaw=0.0)

    async def test_muut_allowed_on_start_and_stop_record(self):
        await self._assert_allowed("/api/start_record", "tb1", route_name="r1")
        await self._assert_allowed("/api/stop_record", "tb1")


if __name__ == "__main__":
    unittest.main()
