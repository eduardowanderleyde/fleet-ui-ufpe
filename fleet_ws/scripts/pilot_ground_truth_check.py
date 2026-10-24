#!/usr/bin/env python3
"""Piloto: compara /odom, /pose e /ground_truth_pose_clean dentro do MESMO bag.

Etapa 2 do plano em orquestracion.md ("Plano: campanha /odom vs. /pose vs.
ground truth") -- 1 replay curto só, gravando as três fontes, pra pegar erro
de referencial/timestamp antes de gastar tempo com as 30 execuções da
campanha principal. Só seguir pra campanha depois que isto fizer sentido
visualmente (mesma forma, mesma escala, sem deslocamento constante).

Uso:
  python3 scripts/pilot_ground_truth_check.py collections/default/<bag> \\
    --output-dir pilot_analysis/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_runs import _bag_duration_sec, _read_traj_xy, _topic_message_counts  # noqa: E402

TOPICS = {
    "odom": "/odom",
    "pose": "/pose",
    "ground_truth": "/ground_truth_pose_clean",
}


def _interp_onto(t_src: np.ndarray, xy_src: np.ndarray, t_target: np.ndarray) -> np.ndarray:
    x = np.interp(t_target, t_src, xy_src[:, 0])
    y = np.interp(t_target, t_src, xy_src[:, 1])
    return np.stack([x, y], axis=1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bag", help="Diretório do bag MCAP com as 3 fontes gravadas (--topics ... odom pose ground_truth_pose_clean)")
    ap.add_argument("--output-dir", default="pilot_analysis")
    args = ap.parse_args()

    bag_dir = Path(args.bag)
    uri = str(bag_dir.resolve())
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    counts = _topic_message_counts(uri)
    duration = _bag_duration_sec(uri)
    print(f"Bag: {uri}")
    print(f"Duração total (metadata): {duration:.2f}s" if duration else "Duração total: desconhecida")
    print()

    data = {}
    for key, topic in TOPICS.items():
        if counts.get(topic, 0) == 0:
            print(f"[AVISO] {topic} tem 0 mensagens nesse bag -- regrave com --topics incluindo {topic.lstrip('/')}")
            continue
        # use_header_stamp=True, rebase=False: as 3 fontes estao no MESMO
        # bag, todas com /clock de sim time em comum -- precisa do tempo
        # ABSOLUTO (rebase=False), nao relativo ao t=0 de cada topico. Achado
        # real desta sessao: /pose comeca a publicar bem depois do ground
        # truth (SLAM Toolbox tem delay de 8s no launch + tempo até o robô
        # andar os 10cm minimos) -- rebasear cada fonte pro seu proprio t=0
        # produzia ~60cm de erro artificial ao comparar.
        _name, t, x, y, dur = _read_traj_xy(bag_dir, topic, use_header_stamp=True, rebase=False)
        n = len(t)
        hz = (n - 1) / dur if dur and dur > 0 else float("nan")
        data[key] = {"t": t, "xy": np.stack([x, y], axis=1), "hz": hz, "n": n}
        print(f"{key:14s} {topic:28s} n={n:5d}  duração={dur:6.2f}s  Hz médio={hz:6.2f}")

    missing = [k for k in TOPICS if k not in data]
    if missing:
        print(f"\nFaltando {missing} -- não é possível comparar as 3 fontes. Regrave o bag com todos os tópicos.")
        return 1

    # Checagem de alinhamento no instante inicial (robô parado logo após o
    # spawn) -- achado do agente experiment-gazebo-tracking
    # (conhecimento/gazebo_tracking.md, 2026-10-02): /odom e a TF map->odom
    # deveriam nascer em ~(0,0) pra este projeto (spawn em 0,0,0). Compara
    # a 1a amostra de cada fonte; não é garantia, é a validação ao vivo que
    # a pesquisa recomendou em vez de assumir.
    print("\n== Checagem de alinhamento (1a amostra de cada fonte, robô parado) ==")
    for key in TOPICS:
        xy0 = data[key]["xy"][0]
        print(f"{key:14s} x={xy0[0]:+.4f}  y={xy0[1]:+.4f}")

    # RMSE: interpola a fonte densa (ground truth) pros horários exatos das
    # fontes esparsas (/odom, /pose) -- recomendação do agente
    # experiment-stats-methodology (conhecimento/stats_methodology.md,
    # 2026-10-02), não o contrário, pra não "cortar a curva" da fonte
    # esparsa em trechos com curvatura.
    print("\n== RMSE vs. ground truth (ground truth interpolado p/ horários de cada fonte) ==")
    gt = data["ground_truth"]
    for key in ("odom", "pose"):
        src = data[key]
        if src["t"][0] < gt["t"][0] or src["t"][-1] > gt["t"][-1]:
            print(f"{key:14s} [AVISO] fora do intervalo de tempo do ground truth -- RMSE pode incluir extrapolação")
        gt_at_src_t = _interp_onto(gt["t"], gt["xy"], src["t"])
        diffs = np.linalg.norm(src["xy"] - gt_at_src_t, axis=1)
        rmse_cm = float(np.sqrt(np.mean(diffs ** 2))) * 100
        print(f"{key:14s} RMSE={rmse_cm:6.2f} cm  (n={len(diffs)} amostras)")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 7))
        colors = {"odom": "tab:blue", "pose": "tab:orange", "ground_truth": "tab:green"}
        for key in TOPICS:
            xy = data[key]["xy"]
            ax.plot(xy[:, 0], xy[:, 1], label=key, color=colors[key], marker=".", markersize=2, linewidth=1)
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        ax.set_aspect("equal")
        ax.legend()
        ax.set_title("Piloto: /odom vs /pose vs ground truth")
        fig_path = out_dir / "pilot_overlay.png"
        fig.savefig(fig_path, dpi=150)
        print(f"\nFigura: {fig_path}")
    except ImportError:
        print("\n[AVISO] matplotlib não disponível -- pulei a figura, só os números acima.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
