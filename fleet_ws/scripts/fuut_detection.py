"""
Detecção do MUUT pelo FUUT via subtração de referência: compara um scan de
LiDAR vivo contra um scan de referência do mesmo ambiente vazio (gravado
antes do MUUT entrar em cena) e localiza o maior cluster de pontos que
ficaram significativamente mais próximos — presumivelmente o MUUT passando
na frente do FUUT.

Escopo deliberado (ver design.md do change `fuut-pilot-experiment`): NÃO é
um detector geral de objetos. Assume cenário estático com um único
obstáculo transitório por vez, a mesma suposição que o protocolo de
record-replay já faz em toda a dissertação (Seção Limitações,
09_conclusao.tex).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

TURTLEBOT4_RADIUS_M = 0.17


@dataclass
class DetectedObstacle:
    distance_m: float
    bearing_deg: float
    num_points: int


def detect_obstacle(
    reference_ranges: list[float],
    live_ranges: list[float],
    angle_min_rad: float,
    angle_increment_rad: float,
    threshold_m: float = TURTLEBOT4_RADIUS_M,
) -> DetectedObstacle | None:
    """Acha o maior cluster contíguo de índices onde live ficou mais perto
    que reference por mais que threshold_m. None se nenhum ponto qualificar.
    Índices inf/nan (sem retorno de eco) contam como "sem obstáculo" ali."""
    if len(reference_ranges) != len(live_ranges):
        raise ValueError("reference_ranges e live_ranges precisam ter o mesmo tamanho")

    flagged = [
        math.isfinite(ref) and math.isfinite(live) and (ref - live) > threshold_m
        for ref, live in zip(reference_ranges, live_ranges)
    ]

    clusters: list[list[int]] = []
    current: list[int] = []
    for i, is_flagged in enumerate(flagged):
        if is_flagged:
            current.append(i)
        elif current:
            clusters.append(current)
            current = []
    if current:
        clusters.append(current)

    if not clusters:
        return None

    best = max(clusters, key=len)
    distances = [live_ranges[i] for i in best]
    angles = [angle_min_rad + i * angle_increment_rad for i in best]

    return DetectedObstacle(
        distance_m=sum(distances) / len(distances),
        bearing_deg=math.degrees(sum(angles) / len(angles)),
        num_points=len(best),
    )
