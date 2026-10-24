#!/usr/bin/env python3
"""
Avaliação formal do NoiseClassifier (piloto TypeSafe) contra uma baseline
estatística clássica (regra de sigma: |z| < 1/2/3 desvios-padrão), pra
responder: o julgamento do TypeSafe concorda com a regra ingênua, e onde
discorda, a diferença é defensável (porque pondera também a tolerância
absoluta) ou é só ruído do modelo?

Contexto fixo: a campanha REAL já publicada na dissertação (N=10,
média=3,35cm, desvio=1,10cm, tolerância Nav2=25cm).

Uso: TYPESAFE_API_KEY=... python3 evaluate_noise_classifier.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from agents.noise_classifier import NoiseClassifier, CampaignContext, ReplicaMetrics


def baseline_sigma_rule(z: float) -> int:
    """Regra clássica de 3-sigma, binada nos mesmos 4 níveis do
    NoiseClassifier (0=normal .. 3=forte indício)."""
    az = abs(z)
    if az < 1.0:
        return 0
    if az < 2.0:
        return 1
    if az < 3.0:
        return 2
    return 3


def main() -> None:
    ctx = CampaignContext(mean_rmse_cm=3.35, std_rmse_cm=1.10, n_replicas=10, tolerance_cm=25.0)
    clf = NoiseClassifier()

    # Grade sistemática de RMSE cobrindo z de -1.5 a +15 (campanha real só
    # teve z entre -1.5 e +1.3; o resto é synthetic, cobrindo o espaço que
    # uma campanha real poderia um dia produzir).
    test_rmse_values = [
        1.65, 2.01, 2.57, 2.58, 3.35, 3.77, 4.08, 4.19, 4.58, 4.76,  # réplicas reais + média
        5.5, 6.0, 7.0, 8.0, 10.0, 12.0, 15.0, 18.0, 22.0, 30.0,       # synthetic, crescente
    ]

    rows = []
    for rmse in test_rmse_values:
        replica = ReplicaMetrics(replica_id=f"rmse_{rmse}", rmse_cm=rmse)
        result = clf.classify(replica, ctx)
        baseline_level = baseline_sigma_rule(result.z_score)
        rows.append((rmse, result.z_score, baseline_level, result.level, result.confidence))

    print(f"{'RMSE(cm)':>9} {'z-score':>8} {'baseline':>9} {'typesafe':>9} {'diff':>6} {'conf':>6}")
    print("-" * 55)
    diffs = []
    exact_matches = 0
    for rmse, z, baseline, ts_level, conf in rows:
        diff = ts_level - baseline
        diffs.append(abs(diff))
        if round(ts_level) == baseline:
            exact_matches += 1
        print(f"{rmse:9.2f} {z:+8.2f} {baseline:9d} {ts_level:9.2f} {diff:+6.2f} {conf:6.2f}")

    n = len(rows)
    mean_abs_diff = sum(diffs) / n
    print("-" * 55)
    print(f"N={n}  concordância exata (arredondado): {exact_matches}/{n} ({100*exact_matches/n:.0f}%)")
    print(f"Diferença média absoluta (TypeSafe - baseline): {mean_abs_diff:.3f} níveis")

    print()
    print("Casos de maior discordância (|diff| >= 1):")
    for rmse, z, baseline, ts_level, conf in rows:
        if abs(ts_level - baseline) >= 1.0:
            below_tolerance_pct = 100 * rmse / ctx.tolerance_cm
            print(
                f"  RMSE={rmse:.2f}cm (z={z:+.2f}): baseline={baseline}, "
                f"typesafe={ts_level:.2f} — RMSE é {below_tolerance_pct:.1f}% da tolerância de {ctx.tolerance_cm}cm"
            )


if __name__ == "__main__":
    main()
