"""
Executor: única fronteira entre os agentes de IA e o Fleet UI.

Os agentes nunca falam com ROS 2 diretamente — chamam estas funções de alto
nível, que por sua vez chamam a API HTTP do backend (main.py). Isso mantém o
controle bruto do robô (cmd_vel, TF, DDS) fora do alcance do agente.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx


class ExecutorError(RuntimeError):
    """Erro ao chamar a API do Fleet UI."""


class Executor:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """`transport` lets tests wire this up to an in-memory ASGI app (httpx.ASGITransport)."""
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "Executor":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _get(self, path: str, **params: Any) -> dict:
        resp = await self._client.get(path, params=params)
        return self._unwrap(resp)

    async def _post(self, path: str, json: dict | None = None, **params: Any) -> dict:
        resp = await self._client.post(path, params=params, json=json)
        return self._unwrap(resp)

    @staticmethod
    def _unwrap(resp: httpx.Response) -> dict:
        try:
            data = resp.json()
        except ValueError as exc:
            raise ExecutorError(f"Resposta não-JSON do backend: {resp.text[:200]}") from exc
        if resp.status_code >= 400:
            raise ExecutorError(data.get("message") or data.get("error") or f"HTTP {resp.status_code}")
        return data

    # -- status / descoberta ------------------------------------------------

    async def get_fleet_status(self) -> dict:
        return await self._get("/api/status")

    async def get_robot_status(self, robot_id: str) -> dict:
        status = await self.get_fleet_status()
        for robot in status.get("robots", []):
            if robot.get("robot_id") == robot_id:
                # Pose deste robô (status["pose"] é só a do robô padrão).
                pose = (status.get("poses") or {}).get(robot_id) or status.get("pose")
                return {**robot, "pose": pose}
        raise ExecutorError(f"Robô '{robot_id}' não encontrado na frota")

    async def list_robots(self) -> list[str]:
        data = await self._get("/api/list_robots")
        return data.get("robot_ids", [])

    async def list_routes(self, robot_id: str = "") -> list[str]:
        data = await self._get("/api/list_routes", robot_id=robot_id)
        return data.get("route_names", [])

    # -- navegação e gravação -------------------------------------------------

    async def move_robot(self, robot_id: str, x: float, y: float, yaw: float = 0.0) -> dict:
        return await self._post("/api/go_to_point", robot_id=robot_id, x=x, y=y, yaw=yaw)

    async def cancel(self, robot_id: str) -> dict:
        return await self._post("/api/cancel", robot_id=robot_id)

    async def start_recording(self, robot_id: str, route_name: str) -> dict:
        return await self._post("/api/start_record", robot_id=robot_id, route_name=route_name)

    async def stop_recording(self, robot_id: str) -> dict:
        return await self._post("/api/stop_record", robot_id=robot_id)

    async def replay_route(self, robot_id: str, route_name: str) -> dict:
        return await self._post("/api/play_route", robot_id=robot_id, route_name=route_name)

    async def start_collection(self, robot_id: str, topics: list[str] | None = None, output_mode: str = "rosbag2") -> dict:
        topics = topics or ["scan", "odom"]
        return await self._post(
            "/api/enable_collection",
            robot_id=robot_id,
            topics=",".join(topics),
            output_mode=output_mode,
        )

    async def stop_collection(self, robot_id: str) -> dict:
        return await self._post("/api/disable_collection", robot_id=robot_id)

    # -- experimentos assíncronos (jobs) --------------------------------------

    async def run_experiment(self, config: dict) -> str:
        """Dispara um record/replay via /api/run_config. Retorna o job_id."""
        data = await self._post("/api/run_config", json=config)
        return data["job_id"]

    async def get_job(self, job_id: str) -> dict:
        return await self._get(f"/api/job/{job_id}")

    async def wait_for_job(self, job_id: str, poll_interval: float = 1.0, timeout: float = 300.0) -> dict:
        """Faz polling de /api/job/{id} até terminar ou estourar o timeout."""
        deadline = time.monotonic() + timeout
        while True:
            job = await self.get_job(job_id)
            if not job.get("running"):
                return job
            if time.monotonic() > deadline:
                raise ExecutorError(f"Timeout esperando job {job_id}")
            await asyncio.sleep(poll_interval)

    # -- campanhas (baseline + N repetições + análise) -------------------------

    async def run_campaign(self, config: dict) -> str:
        """Dispara 1 gravação baseline + N reproduções da mesma rota, seguidas de
        analyze_runs.py, via /api/run_campaign. Retorna o run_id (para usar depois
        com Analyst.analyze_experiment/compare_runs)."""
        data = await self._post("/api/run_campaign", json=config)
        return data["run_id"]

    async def get_campaign_job(self, run_id: str) -> dict:
        return await self._get(f"/api/campaign_job/{run_id}")

    async def wait_for_campaign_job(self, run_id: str, poll_interval: float = 2.0, timeout: float = 1800.0) -> dict:
        """Faz polling de /api/campaign_job/{run_id} até terminar. Timeout maior que
        wait_for_job: 1 baseline + N reproduções + análise leva bem mais que um passo só."""
        deadline = time.monotonic() + timeout
        while True:
            job = await self.get_campaign_job(run_id)
            if not job.get("running"):
                return job
            if time.monotonic() > deadline:
                raise ExecutorError(f"Timeout esperando campanha {run_id}")
            await asyncio.sleep(poll_interval)
