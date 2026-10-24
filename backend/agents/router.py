"""
MissionRouter: dado uma única instrução de missão em linguagem natural e o
conjunto de robôs disponíveis (com pose ao vivo), decide qual robô deve
executá-la. Preenche a lacuna de trabalho futuro do Cap. 9 da dissertação
("Planner supervisor que aloca rotas entre os robôs disponíveis a partir de
uma única instrução de missão, não um mapa robô→instrução já decidido por um
humano") — hoje /api/agent/run_fleet só aceita um dict robot_id→instrução já
montado por fora; este módulo é o passo anterior que decide esse dict.

Dois níveis de escopo, ambos pilotos (não arquitetura final):
- `MissionRouter.route()`: aloca UM robô pra UMA missão inteira, via o
  primitivo Choice da TypeSafe.
- `decompose_and_route()`: o item "mais ambicioso" do Cap. 9 — quebra UMA
  missão em até N sub-tarefas (uma por robô disponível) via Claude (a
  TypeSafe não tem primitivo de extração de lista, só Choice/Score/Noul),
  depois roteia cada sub-tarefa com `MissionRouter.route()`, removendo do
  conjunto de candidatos o robô já alocado antes de rotear a próxima —
  nenhum robô recebe duas sub-tarefas. Isso é decomposição + roteamento
  combinados, não a negociação real entre agentes que o CLiMRS propõe
  (Cap. 9 também já registra essa distinção).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from anthropic import Anthropic
from typesafe_sdk import Choice, TypeSafeClient


@dataclass
class RobotCandidate:
    robot_id: str
    role: str
    nav_state: str
    pose: dict | None  # {"x": float, "y": float, "yaw": float, "valid": bool} ou None


@dataclass
class RoutingDecision:
    robot_id: str
    confidence: float
    probabilities: dict[str, float]
    model: str


class MissionRouter:
    """Roteia uma instrução de missão pro robô mais adequado dentre os
    candidatos informados. Não fala com ROS2 nem com o orquestrador —
    só decide o robot_id; quem executa é o Planner já existente."""

    def __init__(self, api_key: str | None = None) -> None:
        self._client = TypeSafeClient(api_key=api_key or os.environ.get("TYPESAFE_API_KEY"))

    def route(self, mission: str, candidates: list[RobotCandidate]) -> RoutingDecision:
        if not candidates:
            raise ValueError("Nenhum robô candidato disponível para rotear a missão.")
        if len(candidates) == 1:
            only = candidates[0]
            return RoutingDecision(
                robot_id=only.robot_id, confidence=1.0,
                probabilities={only.robot_id: 1.0}, model="trivial-single-candidate",
            )

        state_lines = [f"Missão: {mission}", "", "Robôs disponíveis:"]
        for c in candidates:
            pose_str = (
                f"posição ({c.pose['x']:.2f}, {c.pose['y']:.2f})"
                if c.pose and c.pose.get("valid") else "posição desconhecida"
            )
            state_lines.append(
                f"- {c.robot_id}: papel={c.role}, estado_navegação={c.nav_state}, {pose_str}"
            )
        state = "\n".join(state_lines)

        criteria = {
            c.robot_id: f"escolher {c.robot_id} pra executar a missão" for c in candidates
        }
        result = self._client.system_one(
            state,
            {"robot": Choice(
                instructions=(
                    "Qual robô deve executar essa missão? Prefira o robô mais "
                    "próximo do destino implícito na missão, com estado de "
                    "navegação livre (não navegando outra rota no momento)."
                ),
                criteria=criteria,
            )},
        )
        answer = result.answers["robot"]
        return RoutingDecision(
            robot_id=answer.choice,
            confidence=answer.confidence,
            probabilities=answer.probabilities,
            model=result.model,
        )


def decompose_mission(mission: str, max_subtasks: int, api_key: str | None = None) -> list[str]:
    """Quebra uma missão em até `max_subtasks` sub-tarefas independentes,
    via Claude (saída JSON estrita). Se a missão já for uma tarefa só
    (ex.: 'vá até o ponto X'), devolve lista de 1 elemento — não força
    divisão artificial."""
    if max_subtasks < 1:
        raise ValueError("max_subtasks precisa ser >= 1")
    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=1024,
        system=(
            "Você quebra uma missão de frota de robôs em sub-tarefas independentes. "
            f"No máximo {max_subtasks} sub-tarefas (uma por robô disponível). "
            "Se a missão já é uma tarefa única e indivisível, devolva só 1 sub-tarefa "
            "com o texto da missão original, não invente divisão artificial. "
            "Responda só com um JSON: {\"subtasks\": [\"...\", \"...\"]} — sem markdown, sem texto extra."
        ),
        messages=[{"role": "user", "content": mission}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    subtasks = [s.strip() for s in data["subtasks"] if s and s.strip()]
    if not subtasks:
        raise ValueError(f"Claude não devolveu nenhuma sub-tarefa válida: {text!r}")
    return subtasks[:max_subtasks]


def decompose_and_route(
    mission: str, candidates: list[RobotCandidate], router: MissionRouter | None = None,
) -> dict[str, str]:
    """Decompõe `mission` em até len(candidates) sub-tarefas e roteia cada
    uma pro robô mais adequado dentre os que ainda não foram alocados.
    Devolve {robot_id: sub_instrução}, no mesmo formato que
    /api/agent/run_fleet já consome."""
    if not candidates:
        raise ValueError("Nenhum robô candidato disponível.")
    router = router or MissionRouter()
    subtasks = decompose_mission(mission, max_subtasks=len(candidates))

    remaining = list(candidates)
    allocation: dict[str, str] = {}
    for subtask in subtasks:
        decision = router.route(subtask, remaining)
        allocation[decision.robot_id] = subtask
        remaining = [c for c in remaining if c.robot_id != decision.robot_id]
        if not remaining:
            break
    return allocation
