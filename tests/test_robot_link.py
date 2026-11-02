import contextlib
import io
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "fleet_ws" / "scripts"))

import robot_link as rl  # noqa: E402
import robot_preflight as rp  # noqa: E402
import main as backend_main  # noqa: E402


def preflight_output(checks):
    """O texto que o robot_preflight.py imprime de verdade para essas checagens."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = rp.report(checks)
    return out.getvalue(), code


class FakeProc:
    def __init__(self, pid):
        self.pid = pid
        self.stdout = iter(())
        self.dead = False

    def poll(self):
        return 0 if self.dead else None


class WiggleTests(unittest.TestCase):
    def test_only_turns_in_place_and_comes_back(self):
        import robot_wiggle as rw
        steps = rw.phases(0.4, 0.4)
        self.assertEqual([round(w, 2) for w, _ in steps], [0.4, -0.4, 0.0])
        self.assertAlmostEqual(sum(w * t for w, t in steps), 0.0)

    def test_speed_and_time_are_capped(self):
        import robot_wiggle as rw
        (w, t), *_ = rw.phases(5.0, 10.0)
        self.assertLessEqual(w, rw.MAX_SPEED)
        self.assertLessEqual(t, rw.MAX_SECONDS)


class HelperTests(unittest.TestCase):
    def test_validate_ip(self):
        self.assertEqual(rl.validate_ip(" 192.168.50.11 "), "192.168.50.11")
        for bad in ("", "192.168.50", "robo", "192.168.50.11; rm -rf /"):
            with self.assertRaises(ValueError):
                rl.validate_ip(bad)

    def test_reachable_when_port_answers_or_refuses(self):
        with patch.object(rl.socket, "create_connection", side_effect=ConnectionRefusedError):
            self.assertTrue(rl.check_reachable("192.168.50.11")[0])

    def test_unreachable_on_timeout_names_the_ip(self):
        with patch.object(rl.socket, "create_connection", side_effect=socket.timeout):
            ok, detail = rl.check_reachable("192.168.50.1")
        self.assertFalse(ok)
        self.assertIn("192.168.50.1", detail)
        self.assertIn("roteador", detail)

    def test_parse_preflight_matches_the_real_report(self):
        text, _ = preflight_output([
            rp.Check("middleware", True, "rmw_cyclonedds_cpp"),
            rp.Check("taxa /scan", False, "nenhuma mensagem recebida"),
            rp.Check("Nav2 já rodando", False, "/navigate_to_pose no domínio", warn_only=True),
        ])
        checks = rl.parse_preflight(text)
        self.assertEqual(
            [(c["status"], c["name"], c["detail"]) for c in checks],
            [("ok", "middleware", "rmw_cyclonedds_cpp"),
             ("fail", "taxa /scan", "nenhuma mensagem recebida"),
             ("warn", "Nav2 já rodando", "/navigate_to_pose no domínio")],
        )

    def test_launch_commands_use_the_robot_up_parameters(self):
        cmds = dict(rl.launch_commands({"ROBOT_MAP": "hall_cin_v4", "X_POSE": "1.02", "Y_POSE": "16.62", "YAW": "0.0"}))
        self.assertIn("turtlebot4_real.launch.py", cmds["robot"])
        self.assertIn("x_pose:=1.02", cmds["robot"])
        self.assertIn("single_robot_sim:=true", cmds["fleet"])


class RobotLinkTests(unittest.TestCase):
    def setUp(self):
        self.nav_ready = False
        self.link = rl.RobotLink("/ws", lambda: {}, lambda: "", lambda started_at: self.nav_ready)
        self.started = []
        patch.object(self.link, "_start_processes", side_effect=lambda: self.started.append(True)).start()
        patch.object(self.link, "_stop_processes").start()
        # O giro de verdade precisa de ROS; os testes que olham para ele trocam de novo.
        patch.object(self.link, "_send_signal").start()
        self.addCleanup(patch.stopall)

    def connect_and_wait(self, ip="192.168.50.11"):
        self.link.connect(ip)
        self.link._worker.join(timeout=5)
        return self.link.status()

    def test_unreachable_ip_stops_before_preflight(self):
        with patch.object(rl, "check_reachable", return_value=(False, "não respondeu")), \
             patch.object(self.link, "_run_preflight") as preflight:
            state = self.connect_and_wait()
        self.assertEqual(state["phase"], "error")
        preflight.assert_not_called()
        self.assertEqual(self.started, [])

    def test_preflight_failure_does_not_start_nav2(self):
        text, code = preflight_output([rp.Check("taxa /scan", False, "nenhuma mensagem recebida")])
        with patch.object(rl, "check_reachable", return_value=(True, "ok")), \
             patch.object(self.link, "_run_preflight", return_value=(text, code)):
            state = self.connect_and_wait()
        self.assertEqual(state["phase"], "error")
        self.assertIn("FALHA", state["message"])
        self.assertEqual([c["name"] for c in state["checks"]], ["rede", "taxa /scan"])
        self.assertEqual(self.started, [])

    def test_warning_only_starts_and_becomes_ready_with_nav2_and_fleet(self):
        text, code = preflight_output([
            rp.Check("middleware", True, "rmw_cyclonedds_cpp"),
            rp.Check("Nav2 já rodando", False, "algo", warn_only=True),
        ])
        with patch.object(rl, "check_reachable", return_value=(True, "ok")), \
             patch.object(self.link, "_run_preflight", return_value=(text, code)):
            state = self.connect_and_wait()
        self.assertEqual(state["phase"], "starting")
        self.assertEqual(self.started, [True])

        self.nav_ready = True
        self.assertEqual(self.link.status()["phase"], "starting")  # orquestrador ainda não
        self.link._append("fleet", "[INFO] fleet_orchestrator ready robots=['']")
        self.assertEqual(self.link.status()["phase"], "ready")

    def test_ready_sends_the_connect_signal_once(self):
        text, code = preflight_output([rp.Check("middleware", True, "rmw_cyclonedds_cpp")])
        with patch.object(rl, "check_reachable", return_value=(True, "ok")), \
             patch.object(self.link, "_run_preflight", return_value=(text, code)):
            self.connect_and_wait()
        with patch.object(self.link, "_send_signal") as send:
            self.nav_ready = True
            self.link._append("fleet", "fleet_orchestrator ready")
            first = self.link.status()
            self.link.status()
            for t in list(threading.enumerate()):
                if t is not threading.current_thread() and t.daemon:
                    t.join(timeout=1)
        self.assertEqual(first["phase"], "ready")
        self.assertEqual(first["signal"], "sending")
        send.assert_called_once()

    def test_connect_signal_can_be_turned_off(self):
        self.link._ros_env = lambda: {"ROBOT_CONNECT_WIGGLE": "false"}
        text, code = preflight_output([rp.Check("middleware", True, "rmw_cyclonedds_cpp")])
        with patch.object(rl, "check_reachable", return_value=(True, "ok")), \
             patch.object(self.link, "_run_preflight", return_value=(text, code)):
            self.connect_and_wait()
        with patch.object(self.link, "_send_signal") as send:
            self.nav_ready = True
            self.link._append("fleet", "fleet_orchestrator ready")
            self.assertEqual(self.link.status()["signal"], "off")
        send.assert_not_called()

    def test_dead_process_turns_into_error(self):
        text, code = preflight_output([rp.Check("middleware", True, "rmw_cyclonedds_cpp")])
        with patch.object(rl, "check_reachable", return_value=(True, "ok")), \
             patch.object(self.link, "_run_preflight", return_value=(text, code)):
            self.connect_and_wait()
        proc = FakeProc(1)
        self.link._procs.append(("robot", proc))
        proc.dead = True
        self.assertEqual(self.link.status()["phase"], "error")

    def test_clock_command_uses_the_ip(self):
        with patch.object(rl, "check_reachable", return_value=(False, "x")):
            state = self.connect_and_wait("192.168.50.11")
        self.assertIn("ssh ubuntu@192.168.50.11", state["clock_command"])

    def test_invalid_ip_raises_before_any_work(self):
        with self.assertRaises(ValueError):
            self.link.connect("192.168.50")
        self.assertEqual(self.link.status()["phase"], "idle")


class RobotEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        transport = httpx.ASGITransport(app=backend_main.app)
        self.client = httpx.AsyncClient(transport=transport, base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_connect_is_refused_outside_robot_mode(self):
        with patch.object(backend_main, "ROBOT_MODE", False):
            r = await self.client.post("/api/robot/connect", json={"ip": "192.168.50.11"})
            s = await self.client.get("/api/robot/status")
        self.assertEqual(r.status_code, 409)
        self.assertFalse(s.json()["robot_mode"])

    async def test_simulation_is_blocked_in_robot_mode(self):
        with patch.object(backend_main, "ROBOT_MODE", True):
            r = await self.client.post("/api/simulation/start", json={"mode": "single"})
        self.assertEqual(r.status_code, 409)

    async def test_status_gives_the_robot_up_start_as_default_pose(self):
        with patch.dict("os.environ", {"X_POSE": "1.0216323137283325", "Y_POSE": "16.61626625061035", "YAW": "0.0", "ROBOT_MAP": ""}):
            s = (await self.client.get("/api/robot/status")).json()
        self.assertEqual(s["start_pose"], [1.022, 16.616, 0.0])
        self.assertEqual(s["robot_map"], "hall_cin_v4")
        self.assertTrue((ROOT / "frontend" / "public" / "hall_cin_v4_map.json").exists())

    async def test_invalid_ip_is_a_400(self):
        with patch.object(backend_main, "ROBOT_MODE", True):
            r = await self.client.post("/api/robot/connect", json={"ip": "robo"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
