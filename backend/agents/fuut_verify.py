"""
Verificação cruzada via FUUT: dado que uma unidade fixa (FUUT) observa a
cena de uma posição estacionária, e uma unidade móvel (MUUT) reporta sua
própria pose via odometria/SLAM, este módulo julga o quanto a observação
independente da FUUT corrobora a pose que o MUUT reivindica.

Preenche a lacuna "papel FUUT nunca exercitado" (Cap. 9, Limitações): a
dualidade MUUT/FUUT foi motivada na Introdução como enriquecimento
metodológico — observação exógena como fonte de verdade alternativa — mas
nunca foi testada nem em piloto. Este é um primeiro piloto desse uso.

Escopo deliberado deste piloto (ver conversa com o autor, 2026-10-08):
recebe uma FuutObservation já processada (distância/direção/instante de um
obstáculo transitório detectado) — NÃO faz detecção de robô em LiDAR bruto,
que é um problema de percepção separado e maior, registrado como próximo
passo. A geometria (converter observação polar da FUUT em coordenada do
mundo e comparar com a pose do MUUT) é calculada aqui em Python, de forma
determinística; o que o TypeSafe julga é a corroboração qualitativa
considerando também o alinhamento temporal, não a aritmética em si.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass

from typesafe_sdk import Score, TypeSafeClient

_LEVELS = [
    "Nenhuma correspondência — a FUUT não detectou nada compatível com a "
    "posição/instante reportados pelo MUUT",
    "Correspondência fraca — algo foi detectado na região aproximada, mas "
    "distância geométrica ou instante divergem bastante",
    "Correspondência moderada — direção e instante compatíveis, mas a "
    "distância geométrica diverge mais do que o esperado por ruído de sensor",
    "Correspondência forte — distância geométrica, direção e instante "
    "todos compatíveis com a pose reportada pelo MUUT, dentro de ruído "
    "esperado de sensor",
]


@dataclass
class FuutPose:
    x: float
    y: float


@dataclass
class FuutObservation:
    """Um obstáculo transitório detectado pela FUUT, em coordenadas
    polares relativas à própria FUUT (já processado — não é o scan bruto)."""
    distance_m: float
    bearing_deg: float  # 0° = eixo x da FUUT, sentido anti-horário
    timestamp_s: float


@dataclass
class MuutClaim:
    x: float
    y: float
    timestamp_s: float


@dataclass
class VerificationResult:
    level: float
    label: str
    confidence: float
    probabilities: dict[int, float]
    geometric_discrepancy_m: float
    time_discrepancy_s: float


def _observed_world_xy(fuut: FuutPose, obs: FuutObservation) -> tuple[float, float]:
    angle = math.radians(obs.bearing_deg)
    return (
        fuut.x + obs.distance_m * math.cos(angle),
        fuut.y + obs.distance_m * math.sin(angle),
    )


class FuutVerifier:
    def __init__(self, api_key: str | None = None) -> None:
        self._client = TypeSafeClient(api_key=api_key or os.environ.get("TYPESAFE_API_KEY"))

    def verify(self, fuut: FuutPose, observation: FuutObservation, claim: MuutClaim) -> VerificationResult:
        obs_x, obs_y = _observed_world_xy(fuut, observation)
        geometric_discrepancy = math.hypot(obs_x - claim.x, obs_y - claim.y)
        time_discrepancy = abs(observation.timestamp_s - claim.timestamp_s)

        state = (
            f"FUUT está fixa em ({fuut.x:.2f}, {fuut.y:.2f}). "
            f"Ela detectou um obstáculo transitório a {observation.distance_m:.2f}m, "
            f"direção {observation.bearing_deg:.1f}°, no instante t={observation.timestamp_s:.2f}s "
            f"— o que corresponde à posição absoluta estimada ({obs_x:.2f}, {obs_y:.2f}).\n"
            f"O MUUT reportou (via sua própria odometria/SLAM) estar na posição "
            f"({claim.x:.2f}, {claim.y:.2f}) no instante t={claim.timestamp_s:.2f}s.\n"
            f"Discrepância geométrica calculada: {geometric_discrepancy:.3f}m. "
            f"Discrepância temporal: {time_discrepancy:.3f}s."
        )

        result = self._client.system_one(
            state,
            {"corroboration": Score(
                instructions=(
                    "O quanto a observação independente da FUUT corrobora a pose "
                    "que o MUUT reportou, considerando que ruído de sensor típico "
                    "(LiDAR + estimativa de distância/direção) é da ordem de poucos "
                    "centímetros a dezenas de centímetros, e pequena defasagem "
                    "temporal entre coleta e reporte é esperada?"
                ),
                criteria=_LEVELS,
            )},
        )
        answer = result.answers["corroboration"]
        return VerificationResult(
            level=answer.score,
            label=_LEVELS[round(answer.score)],
            confidence=answer.confidence,
            probabilities=answer.probabilities,
            geometric_discrepancy_m=geometric_discrepancy,
            time_discrepancy_s=time_discrepancy,
        )
