"""
Classifica se o RMSE de uma réplica específica é consistente com ruído
esperado do controlador estocástico (MPPI resample ruído gaussiano a cada
ciclo, Seção de Ameaças à Validade do Cap. 7) ou se é indício de problema
real de repetibilidade (protocolo, pose inicial, mudança de mecanismo).

Hoje esse julgamento é inteiramente manual — o autor lê a tabela de RMSE
por réplica e decide "isso é normal ou não". Este módulo usa o primitivo
Score da TypeSafe pra formalizar parte desse julgamento, sem substituir a
decisão final do autor nem reinterpretar resultados já publicados — é uma
ferramenta de triagem, não uma reclassificação automática de dados.

Escopo deliberado: julga UMA réplica contra o contexto estatístico da
campanha (média, desvio-padrão, N). Não tenta causalidade — "ruído
esperado" vs. "indício de problema" é uma classificação de plausibilidade,
não uma prova.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from typesafe_sdk import Score, TypeSafeClient

_LEVELS = [
    "Claramente dentro do ruído esperado — valor próximo da média da campanha, "
    "sem razão pra suspeitar de algo além da estocasticidade normal do controlador",
    "Compatível com ruído esperado, mas no extremo da distribuição — vale registrar, "
    "não vale investigar sozinho",
    "Suspeito — a magnitude é maior do que o esperado só por estocasticidade do "
    "controlador; vale conferir o log/bag dessa réplica especificamente antes de "
    "descartar como ruído",
    "Forte indício de problema real — a magnitude foge tanto do padrão da campanha "
    "que atribuir só a ruído de controlador seria pouco defensável sem investigação",
]


@dataclass
class CampaignContext:
    mean_rmse_cm: float
    std_rmse_cm: float
    n_replicas: int
    tolerance_cm: float
    controller: str = "MPPI (Model Predictive Path Integral), estocástico por projeto, regenerate_noises=true"


@dataclass
class ReplicaMetrics:
    replica_id: str
    rmse_cm: float
    duration_s: float | None = None
    mean_duration_s: float | None = None


@dataclass
class NoiseClassification:
    level: float
    label: str
    confidence: float
    probabilities: dict[int, float]
    z_score: float


class NoiseClassifier:
    def __init__(self, api_key: str | None = None) -> None:
        self._client = TypeSafeClient(api_key=api_key or os.environ.get("TYPESAFE_API_KEY"))

    def classify(self, replica: ReplicaMetrics, context: CampaignContext) -> NoiseClassification:
        z_score = (
            (replica.rmse_cm - context.mean_rmse_cm) / context.std_rmse_cm
            if context.std_rmse_cm > 0 else 0.0
        )
        duration_note = ""
        if replica.duration_s is not None and context.n_replicas > 1 and replica.mean_duration_s:
            dur_ratio = replica.duration_s / replica.mean_duration_s
            duration_note = (
                f" A duração dessa réplica foi {replica.duration_s:.2f}s contra uma "
                f"média de {replica.mean_duration_s:.2f}s na campanha (razão {dur_ratio:.2f}x)."
            )

        state = (
            f"Campanha de repetibilidade: N={context.n_replicas} réplicas, controlador "
            f"{context.controller}. RMSE médio da campanha: {context.mean_rmse_cm:.2f}cm, "
            f"desvio-padrão: {context.std_rmse_cm:.2f}cm. Tolerância operacional de "
            f"referência (Nav2 goal checker): {context.tolerance_cm:.1f}cm.\n"
            f"Réplica em avaliação ({replica.replica_id}): RMSE={replica.rmse_cm:.2f}cm "
            f"(z-score calculado: {z_score:+.2f} desvios-padrão da média).{duration_note}"
        )

        result = self._client.system_one(
            state,
            {"classification": Score(
                instructions=(
                    "Essa réplica específica é consistente com ruído esperado do "
                    "controlador estocástico, ou é indício de problema real de "
                    "repetibilidade que mereceria investigação? Considere o z-score, "
                    "mas também se o valor absoluto ainda está bem abaixo da "
                    "tolerância operacional (o que reduz a urgência mesmo se for "
                    "estatisticamente um outlier)."
                ),
                criteria=_LEVELS,
            )},
        )
        answer = result.answers["classification"]
        return NoiseClassification(
            level=answer.score,
            label=_LEVELS[round(answer.score)],
            confidence=answer.confidence,
            probabilities=answer.probabilities,
            z_score=z_score,
        )
