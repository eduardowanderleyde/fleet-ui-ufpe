#!/usr/bin/env python3
"""Converte a gravação (MCAP) de um replay do fleet-ui no CSV do nav_3points.py.

Assim os scripts de análise das autoras (analise/) leem corridas
feitas pelo botão "Executar replay" do mesmo jeito que leem as do script
delas. Mesmas colunas e mesma semântica:

- uma linha a cada 0,2 s (LOG_INTERVAL do nav_3points.py);
- Pos_X/Pos_Y = última /amcl_pose (ou /pose, no modo SLAM) — com
  --pose-source ground_truth usa a posição exata do Gazebo;
- velocidades = último /odom;
- alvo = próximo ponto da rota; avança quando o robô chega a menos de
  ARRIVE_TOL_M dele (linha com Status SUCCEEDED).

Diferença conhecida: Distancia_Restante aqui é a distância em linha reta até
o alvo; no nav_3points.py é o distance_remaining do Nav2 (comprimento do
caminho planejado). Nos trechos retos do percurso CBSoft as duas coincidem.

Horário: no robô real os carimbos já são o relógio de parede (o que casa
com o log do nRF Connect). Na simulação são tempo simulado; aí o início é
alinhado ao horário do nome da pasta da gravação (UTC, do backend).

Uso (dentro do container, com o ROS carregado):
    python3 bag_to_nav_csv.py collections/default/<pasta_da_gravacao> \\
        --route routes/default/percurso_cbsoft.yaml --out-dir collections/cbsoft
"""
from __future__ import annotations

import argparse
import bisect
import csv
import math
import os
from datetime import datetime, timezone

import yaml

LOG_INTERVAL = 0.2
ARRIVE_TOL_M = 0.5
SIM_TIME_LIMIT = 1e9  # carimbos abaixo disso são tempo simulado, não Unix

COLUMNS = [
    "Timestamp_Legivel", "Unix_Time", "Waypoint_Index", "Waypoint_Nome",
    "Target_X", "Target_Y", "Pos_X", "Pos_Y", "Distancia_Restante",
    "Velocidade_Linear_X_m_s", "Velocidade_Linear_Y_m_s",
    "Velocidade_Angular_Z_rad_s", "Velocidade_Linear_Total_m_s", "Status",
]


def waypoint_names(n: int) -> list[str]:
    """Nomes iguais aos do nav_3points.py no caso de 3 pontos."""
    if n == 3:
        return ["Ponto_Inicial", "Ponto_Medio", "Ponto_Final"]
    return ["Ponto_Inicial"] + [f"Ponto_{i}" for i in range(1, n - 1)] + ["Ponto_Final"]


def recording_start(poses, odoms) -> float:
    """Início real da gravação.

    A /amcl_pose é TRANSIENT_LOCAL: a primeira que chega é a última que o AMCL
    publicou, às vezes dezenas de segundos antes de a gravação começar. Começar
    por ela deslocava a corrida inteira (40 s numa corrida real). O /odom flui
    sem parar, então marca bem quando a gravação começou.
    """
    first_pose = min(p[0] for p in poses)
    return max(first_pose, min(o[0] for o in odoms)) if odoms else first_pose


def _latest(series: list[tuple], times: list[float], t: float):
    i = bisect.bisect_right(times, t) - 1
    return series[i] if i >= 0 else None


def build_rows(poses, odoms, route, wall_offset: float = 0.0) -> list[list]:
    """poses: [(t, x, y)], odoms: [(t, vx, vy, wz)], route: [(x, y)] com o início.

    Puro (sem ROS) pra poder testar. wall_offset soma ao tempo pra virar Unix.
    """
    if not poses or len(route) < 2:
        return []
    poses = sorted(poses)
    odoms = sorted(odoms)
    pose_t = [p[0] for p in poses]
    odom_t = [o[0] for o in odoms]
    names = waypoint_names(len(route))
    t_end = max(poses[-1][0], odoms[-1][0] if odoms else poses[-1][0])

    def row(t, idx, status):
        _, x, y = _latest(poses, pose_t, t)
        o = _latest(odoms, odom_t, t)
        vx, vy, wz = (o[1], o[2], o[3]) if o else (0.0, 0.0, 0.0)
        tx, ty = route[idx]
        dist = 0.0 if status in ("START", "SUCCEEDED") else math.hypot(tx - x, ty - y)
        unix = t + wall_offset
        legivel = datetime.fromtimestamp(unix).strftime("%H:%M:%S.%f")[:-3]
        return [legivel, unix, idx, names[idx], tx, ty, x, y, dist,
                vx, vy, wz, math.hypot(vx, vy), status]

    t = recording_start(poses, odoms)
    rows = [row(t, 0, "START")]
    t += LOG_INTERVAL
    idx = 1
    while idx < len(route) and t <= t_end:
        _, x, y = _latest(poses, pose_t, t)
        if math.hypot(route[idx][0] - x, route[idx][1] - y) < ARRIVE_TOL_M:
            rows.append(row(t, idx, "SUCCEEDED"))
            idx += 1
        else:
            rows.append(row(t, idx, "NAVIGATING"))
        t += LOG_INTERVAL
    return rows


def wall_offset_from_bag_name(bag_dir: str, first_stamp: float) -> float:
    """Gravação em tempo simulado: alinha o início ao horário do nome da pasta."""
    if first_stamp >= SIM_TIME_LIMIT:
        return 0.0
    name = os.path.basename(os.path.normpath(bag_dir))
    try:
        start = datetime.strptime(name[:26], "%Y-%m-%d_%H-%M-%S_%f").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.0
    return start.timestamp() - first_stamp


def read_bag(bag_dir: str, pose_source: str):
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=bag_dir, storage_id="mcap"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    types = {t.name: t.type for t in reader.get_all_topics_and_types()}
    pose_topics = {"amcl": ("/amcl_pose", "/pose"), "ground_truth": ("/ground_truth_pose_clean",)}[pose_source]
    poses: dict[str, list] = {name: [] for name in pose_topics}
    odoms: list = []
    while reader.has_next():
        topic, data, stamp_ns = reader.read_next()
        if topic in poses:
            msg = deserialize_message(data, get_message(types[topic]))
            pose = msg.pose.pose if hasattr(msg.pose, "pose") else msg.pose
            poses[topic].append((stamp_ns * 1e-9, pose.position.x, pose.position.y))
        elif topic == "/odom":
            msg = deserialize_message(data, get_message(types[topic]))
            tw = msg.twist.twist
            odoms.append((stamp_ns * 1e-9, tw.linear.x, tw.linear.y, tw.angular.z))
    chosen = next((poses[name] for name in pose_topics if poses[name]), [])
    return chosen, odoms


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bag_dir", help="pasta da gravação (collections/<robô>/<data>_...)")
    ap.add_argument("--route", required=True, help="YAML da rota reproduzida (routes/<robô>/<rota>.yaml)")
    ap.add_argument("--out-dir", default=".", help="pasta onde o CSV é gravado")
    ap.add_argument("--pose-source", choices=["amcl", "ground_truth"], default="amcl",
                    help="amcl = igual ao nav_3points.py; ground_truth = posição exata (só simulação)")
    args = ap.parse_args()

    with open(args.route) as f:
        route = [(float(p["x"]), float(p["y"])) for p in (yaml.safe_load(f) or {}).get("poses") or []]
    poses, odoms = read_bag(args.bag_dir, args.pose_source)
    if not poses:
        print(f"Nenhuma pose ({args.pose_source}) na gravação {args.bag_dir}.")
        return 1

    offset = wall_offset_from_bag_name(args.bag_dir, recording_start(poses, odoms))
    rows = build_rows(poses, odoms, route, offset)
    start = datetime.fromtimestamp(rows[0][1]).strftime("%Y-%m-%d_%H-%M-%S")
    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"navegacao_2_trechos_{start}.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        w.writerows(rows)
    reached = sum(1 for r in rows if r[-1] == "SUCCEEDED")
    print(f"{out}: {len(rows)} linhas, {reached}/{len(route) - 1} alvos alcançados"
          + (" (horário alinhado pelo nome da pasta: gravação em tempo simulado)" if offset else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
