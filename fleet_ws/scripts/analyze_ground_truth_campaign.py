#!/usr/bin/env python3
"""Analisa uma campanha gravada por run_ground_truth_campaign.py: RMSE de
/odom e /pose contra o ground truth, agregado pelas N réplicas, com IC
95% via t de Student (N pequeno — mesma justificativa já usada no projeto,
ver conhecimento/stats_methodology.md).

Uso (uma rota):
  python3 scripts/analyze_ground_truth_campaign.py runs/gt01_curta

Uso (comparar várias rotas, ver se o gap odom/pose cresce com a rota):
  python3 scripts/analyze_ground_truth_campaign.py runs/gt01_curta runs/gt01_longa runs/gt01_loop
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_runs import _read_traj_xy  # noqa: E402


def _interp_onto(t_src: np.ndarray, xy_src: np.ndarray, t_target: np.ndarray) -> np.ndarray:
    x = np.interp(t_target, t_src, xy_src[:, 0])
    y = np.interp(t_target, t_src, xy_src[:, 1])
    return np.stack([x, y], axis=1)


def _rmse_vs_gt(bag: Path, source_topic: str) -> float:
    """RMSE de source_topic vs. ground truth, interpolando o ground truth
    (fonte densa) pros horários exatos de source_topic -- não o contrário
    (recomendação do agente experiment-stats-methodology, 2026-10-02)."""
    # rebase=False: tempo ABSOLUTO, obrigatorio pra comparar topicos diferentes
    # dentro do mesmo bag (ver docstring de _read_traj_xy -- achado real desta
    # sessao: /pose comeca a publicar ~8-10s depois do ground truth, rebasear
    # cada um pro seu proprio t=0 produzia ~60cm de RMSE artificial).
    _, t_gt, x_gt, y_gt, _ = _read_traj_xy(bag, "/ground_truth_pose_clean", use_header_stamp=True, rebase=False)
    _, t_src, x_src, y_src, _ = _read_traj_xy(bag, source_topic, use_header_stamp=True, rebase=False)
    gt_xy = np.stack([x_gt, y_gt], axis=1)
    src_xy = np.stack([x_src, y_src], axis=1)
    gt_at_src_t = _interp_onto(t_gt, gt_xy, t_src)
    diffs = np.linalg.norm(src_xy - gt_at_src_t, axis=1)
    return float(np.sqrt(np.mean(diffs ** 2)))


def _mean_ci95(values: list) -> tuple:
    arr = np.array(values)
    n = len(arr)
    mean = float(np.mean(arr))
    if n < 2:
        return mean, float("nan"), float("nan")
    sem = stats.sem(arr)
    half = sem * stats.t.ppf(0.975, n - 1)
    return mean, mean - half, mean + half


def analyze_route(run_dir: Path) -> dict:
    manifest_path = run_dir / "campaign_manifest.json"
    manifest = json.loads(manifest_path.read_text())

    odom_rmse_cm, pose_rmse_cm = [], []
    per_replica = []
    for entry in manifest["replicas"]:
        if not (entry["boot_success"] and entry["record_success"]):
            continue
        export = json.loads(Path(entry["export_path"]).read_text())
        bag = Path(export["rosbag_path"])  # relativo a fleet_ws (cwd esperado)
        try:
            odom_rmse = _rmse_vs_gt(bag, "/odom") * 100
            pose_rmse = _rmse_vs_gt(bag, "/pose") * 100
        except Exception as e:
            print(f"  [AVISO] réplica {entry['replicate_id']}: {e}")
            continue
        odom_rmse_cm.append(odom_rmse)
        pose_rmse_cm.append(pose_rmse)
        per_replica.append({
            "replicate_id": entry["replicate_id"],
            "odom_vs_gt_rmse_cm": round(odom_rmse, 2),
            "pose_vs_gt_rmse_cm": round(pose_rmse, 2),
        })

    odom_mean, odom_lo, odom_hi = _mean_ci95(odom_rmse_cm)
    pose_mean, pose_lo, pose_hi = _mean_ci95(pose_rmse_cm)

    return {
        "route": manifest["route"],
        "protocol_id": manifest["protocol_id"],
        "n": len(odom_rmse_cm),
        "odom_vs_gt_rmse_cm": {"mean": round(odom_mean, 2), "ci95": [round(odom_lo, 2), round(odom_hi, 2)]},
        "pose_vs_gt_rmse_cm": {"mean": round(pose_mean, 2), "ci95": [round(pose_lo, 2), round(pose_hi, 2)]},
        "per_replica": per_replica,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    results = []
    for arg in sys.argv[1:]:
        run_dir = Path(arg)
        print(f"=== {run_dir} ===")
        result = analyze_route(run_dir)
        results.append(result)
        print(f"  rota: {result['route']}  N={result['n']}")
        print(f"  odom vs ground truth: {result['odom_vs_gt_rmse_cm']['mean']:.2f}cm "
              f"(IC95% [{result['odom_vs_gt_rmse_cm']['ci95'][0]:.2f}, {result['odom_vs_gt_rmse_cm']['ci95'][1]:.2f}])")
        print(f"  pose vs ground truth: {result['pose_vs_gt_rmse_cm']['mean']:.2f}cm "
              f"(IC95% [{result['pose_vs_gt_rmse_cm']['ci95'][0]:.2f}, {result['pose_vs_gt_rmse_cm']['ci95'][1]:.2f}])")
        print()

    if len(results) > 1:
        print("=== Resumo comparativo (odom vs. pose, por rota) ===")
        for r in results:
            print(f"  {r['route']:20s} N={r['n']:2d}  odom={r['odom_vs_gt_rmse_cm']['mean']:6.2f}cm  "
                  f"pose={r['pose_vs_gt_rmse_cm']['mean']:6.2f}cm")

    out = {"routes": results}
    out_path = Path(sys.argv[1]).parent / "ground_truth_campaign_analysis.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nAnálise salva em: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
