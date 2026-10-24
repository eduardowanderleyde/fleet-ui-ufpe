"""
Planner: converte uma instrução em linguagem natural numa sequência de
chamadas às ferramentas de tools.py (Executor/Analyst), usando tool calling
da Claude API. O modelo decide o quê fazer; Executor decide como executar.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from anthropic import AsyncAnthropic

from .analyst import Analyst
from .executor import Executor
from .tools import TOOL_SPECS

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = (
    "Você orquestra uma frota de robôs TurtleBot4 através de um conjunto fixo de ferramentas. "
    "Nunca invente robôs, rotas ou run_ids que não tenham sido retornados por uma ferramenta. "
    "Sempre confira o estado do robô antes de comandos de movimento, e resuma o resultado ao final."
)


@dataclass
class PlanStep:
    tool_name: str
    tool_input: dict
    result: Any


@dataclass
class PlanResult:
    final_text: str
    steps: list[PlanStep] = field(default_factory=list)


class Planner:
    def __init__(
        self,
        executor: Executor,
        analyst: Analyst | None = None,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        max_turns: int = 12,
        robot_id: str | None = None,
    ) -> None:
        """`robot_id`, se informado, restringe este Planner a um único robô: toda
        ferramenta que aceita robot_id (ou config.robot) é forçada para esse valor,
        mesmo que o modelo peça outro — para rodar N agentes independentes com
        segurança, um por robô, sem que um agente possa mexer no robô de outro."""
        self.executor = executor
        self.analyst = analyst or Analyst()
        self.model = model
        self.max_turns = max_turns
        self.robot_id = robot_id
        self._client = AsyncAnthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    def _system_prompt(self) -> str:
        if not self.robot_id:
            return SYSTEM_PROMPT
        return SYSTEM_PROMPT + f" Você está restrito ao robô '{self.robot_id}' — não pode operar nenhum outro."

    def _scope_input(self, tool_name: str, tool_input: dict) -> dict:
        if not self.robot_id:
            return tool_input
        scoped = dict(tool_input)
        if "robot_id" in scoped:
            scoped["robot_id"] = self.robot_id
        if tool_name == "run_experiment" and isinstance(scoped.get("config"), dict):
            scoped["config"] = {**scoped["config"], "robot": self.robot_id}
        if tool_name == "run_campaign":
            # "robot" não é obrigatório no schema (default backend é "default"),
            # então força incondicionalmente — não dá pra confiar em "in scoped".
            scoped["robot"] = self.robot_id
        return scoped

    async def _dispatch(self, tool_name: str, tool_input: dict) -> Any:
        """`tool_input` deve já estar escopado (ver `_scope_input`) — chamado por `run()`."""
        if tool_name == "list_robots":
            return await self.executor.list_robots()
        if tool_name == "list_routes":
            return await self.executor.list_routes(tool_input.get("robot_id", ""))
        if tool_name == "get_robot_status":
            return await self.executor.get_robot_status(tool_input["robot_id"])
        if tool_name == "move_robot":
            return await self.executor.move_robot(
                tool_input["robot_id"], tool_input["x"], tool_input["y"], tool_input.get("yaw", 0.0)
            )
        if tool_name == "start_recording":
            return await self.executor.start_recording(tool_input["robot_id"], tool_input["route_name"])
        if tool_name == "stop_recording":
            return await self.executor.stop_recording(tool_input["robot_id"])
        if tool_name == "replay_route":
            return await self.executor.replay_route(tool_input["robot_id"], tool_input["route_name"])
        if tool_name == "start_collection":
            return await self.executor.start_collection(tool_input["robot_id"], tool_input.get("topics"))
        if tool_name == "stop_collection":
            return await self.executor.stop_collection(tool_input["robot_id"])
        if tool_name == "run_experiment":
            job_id = await self.executor.run_experiment(tool_input["config"])
            return await self.executor.wait_for_job(job_id)
        if tool_name == "run_campaign":
            campaign_cfg = {k: v for k, v in tool_input.items() if k != "run_id" or v}
            run_id = await self.executor.run_campaign(campaign_cfg)
            return await self.executor.wait_for_campaign_job(run_id)
        if tool_name == "analyze_experiment":
            return self.analyst.analyze_experiment(
                tool_input["run_id"], tool_input.get("rmse_threshold_m", 0.05)
            )
        if tool_name == "diagnose_experiment":
            return self.analyst.diagnose_experiment(
                tool_input["run_id"], tool_input.get("rmse_threshold_m", 0.05)
            )
        if tool_name == "compare_runs":
            return self.analyst.compare_runs(
                tool_input["run_id"], tool_input["label_a"], tool_input["label_b"]
            )
        raise ValueError(f"Ferramenta desconhecida: {tool_name}")

    async def run(self, instruction: str) -> PlanResult:
        messages: list[dict] = [{"role": "user", "content": instruction}]
        steps: list[PlanStep] = []

        for _ in range(self.max_turns):
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=self._system_prompt(),
                tools=TOOL_SPECS,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                final_text = "".join(b.text for b in response.content if b.type == "text")
                return PlanResult(final_text=final_text, steps=steps)

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                scoped_input = self._scope_input(block.name, block.input)
                try:
                    result = await self._dispatch(block.name, scoped_input)
                    content = json.dumps(result, default=str)
                    is_error = False
                except Exception as exc:  # noqa: BLE001 - repassa qualquer falha de ferramenta ao modelo
                    result = str(exc)
                    content = result
                    is_error = True
                steps.append(PlanStep(tool_name=block.name, tool_input=scoped_input, result=result))
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error}
                )
            messages.append({"role": "user", "content": tool_results})

        raise RuntimeError(f"Planner excedeu max_turns={self.max_turns} sem concluir")
