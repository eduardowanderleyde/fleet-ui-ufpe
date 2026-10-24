# map_name: hall_cin_v4.yaml
# Original: script das autoras do artigo do CBSoft'26 “Wireless Connectivity Testing with Mobile Robots: A Bluetooth Low Energy Case Study”.
# Mudanças em relação ao original: flag --sim (relógio da simulação),
# --log-dir, e só começa a gravar o CSV depois da primeira pose do AMCL.
# Na simulação (mundo cbsoft_open) as coordenadas são as mesmas.
"""
Script para teste de navegação do TurtleBot 4 em dois trechos:
PONTO INICIAL -> PONTO MÉDIO -> PONTO FINAL

Objetivo:
- Definir a pose inicial do robô no mapa;
- Navegar primeiro até um ponto médio;
- Depois navegar até o ponto final;
- Registrar em CSV a posição AMCL, distância restante e velocidades vindas de /odom.

Antes de rodar:
1. Inicie localization + nav2 + rviz com o mapa correto.
2. Posicione o robô no ponto inicial.
    rode:
        ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose "{
        pose: {
            header: {
            stamp: {sec: 0, nanosec: 0},
            frame_id: 'map'
            },
            pose: {
            position: {x: 1.0216323137283325, y: 16.61626625061035, z: 0.0},
            orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}
            }
        }
        }"
3. Ajuste START, MIDPOINT e FINAL_GOAL com coordenadas do mapa atual.
4. Rode este script.
"""

import argparse
import os

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.executors import MultiThreadedExecutor

from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy

from datetime import datetime
import math
import csv
import time
import threading


# =========================
# CONFIGURAÇÕES DO TESTE
# =========================

# Frequência de gravação do CSV.
# 0.5 = 2 Hz
# 0.2 = 5 Hz
# 0.1 = 10 Hz
LOG_INTERVAL = 0.2

# Nome do arquivo de log
LOG_FILE = f"navegacao_2_trechos_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"


# =========================
# COORDENADAS DO MAPA
# =========================
# Use RViz -> Publish Point para pegar x,y:
# ros2 topic echo /clicked_point --once
#
# Ou
#
# Use RViz -> 2D Goal Pose para pegar x,y e orientação:
# ros2 topic echo /goal_pose --once


# PONTO INICIAL
# Ajuste com o ponto inicial real no mapa hall_cin_v4.
START = {
    "name": "Ponto_Inicial",
    "x": 1.0216323137283325,
    "y": 16.61626625061035,
    "z_orient": 0.0,
    "w_orient": 1.0,
}

# PONTO MÉDIO
# Substitua pelos valores reais do ponto médio no mapa hall_cin_v4.
MIDPOINT = {
    "name": "Ponto_Medio",
    "x": -2.5490856170654297,
    "y": -47.34372329711914,
    "z_orient": 0.0,
    "w_orient": 1.0,
}

# PONTO FINAL
# Ajuste com o ponto final real no mapa hall_cin_v4.
FINAL_GOAL = {
    "name": "Ponto_Final",
    "x": -33.71685791015625,
    "y": -47.11880874633789,
    "z_orient": 0.0,
    "w_orient": 1.0,
}

# O robô navegará apenas para estes dois alvos:
# START é usado só para setInitialPose.
ROUTE = [
    MIDPOINT,
    FINAL_GOAL,
]


class PoseMonitor(Node):
    """
    Nó auxiliar para escutar:
    - posição estimada no mapa via /amcl_pose;
    - velocidade real/estimada via /odom.
    """

    def __init__(self):
        super().__init__("pose_monitor")

        self.current_x = 0.0
        self.current_y = 0.0
        self.pose_received = False

        self.linear_x = 0.0
        self.linear_y = 0.0
        self.angular_z = 0.0
        self.linear_speed = 0.0

        # TRANSIENT_LOCAL igual ao publicador do AMCL: recebe na hora a última
        # pose publicada (a inicial). Com VOLATILE ela se perde e as primeiras
        # linhas do CSV saem em (0, 0) — aconteceu na corrida real 2026-05-19_15-57-33.
        amcl_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.pose_subscription = self.create_subscription(
            PoseWithCovarianceStamped,
            "/amcl_pose",
            self.pose_callback,
            amcl_qos,
        )

        self.odom_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        self.odom_subscription = self.create_subscription(
            Odometry,
            "/odom",
            self.odom_callback,
            self.odom_qos,
        )

    def pose_callback(self, msg):
        self.current_x = msg.pose.pose.position.x
        self.current_y = msg.pose.pose.position.y
        self.pose_received = True

    def odom_callback(self, msg):
        self.linear_x = msg.twist.twist.linear.x
        self.linear_y = msg.twist.twist.linear.y
        self.angular_z = msg.twist.twist.angular.z
        self.linear_speed = math.sqrt(self.linear_x**2 + self.linear_y**2)

def build_pose(navigator: BasicNavigator, point: dict) -> PoseStamped:
    """
    Cria um PoseStamped a partir de um dicionário:
    {
        "x": ...,
        "y": ...,
        "z_orient": ...,
        "w_orient": ...
    }
    """
    pose = PoseStamped()
    pose.header.frame_id = "map"
    pose.header.stamp = navigator.get_clock().now().to_msg()

    pose.pose.position.x = float(point["x"])
    pose.pose.position.y = float(point["y"])
    pose.pose.position.z = 0.0

    pose.pose.orientation.x = 0.0
    pose.pose.orientation.y = 0.0
    pose.pose.orientation.z = float(point.get("z_orient", 0.0))
    pose.pose.orientation.w = float(point.get("w_orient", 1.0))

    return pose


def write_log_row(writer, pose_monitor, waypoint_index, target, distancia_restante, status):
    now = datetime.now()

    writer.writerow([
        now.strftime("%H:%M:%S.%f")[:-3],
        time.time(),
        waypoint_index,
        target["name"],
        target["x"],
        target["y"],
        pose_monitor.current_x,
        pose_monitor.current_y,
        distancia_restante,
        pose_monitor.linear_x,
        pose_monitor.linear_y,
        pose_monitor.angular_z,
        pose_monitor.linear_speed,
        status,
    ])


def navigate_to_target(navigator, pose_monitor, writer, waypoint_index, target):
    """
    Envia o robô para um alvo e grava logs até a navegação terminar.
    """
    goal_pose = build_pose(navigator, target)

    print(
        f"🚀 Indo para {target['name']}: "
        f"X={target['x']:.2f}, Y={target['y']:.2f}"
    )

    navigator.goToPose(goal_pose)

    while not navigator.isTaskComplete():
        feedback = navigator.getFeedback()

        distancia_restante = 0.0
        if feedback:
            distancia_restante = feedback.distance_remaining

        write_log_row(
            writer=writer,
            pose_monitor=pose_monitor,
            waypoint_index=waypoint_index,
            target=target,
            distancia_restante=distancia_restante,
            status="NAVIGATING",
        )

        time.sleep(LOG_INTERVAL)

    result = navigator.getResult()

    if result == TaskResult.SUCCEEDED:
        print(f"✅ Chegou em {target['name']}.")
        status = "SUCCEEDED"
    elif result == TaskResult.CANCELED:
        print(f"⚠️ Navegação para {target['name']} foi cancelada.")
        status = "CANCELED"
    elif result == TaskResult.FAILED:
        print(f"❌ Navegação para {target['name']} falhou.")
        status = "FAILED"
    else:
        print(f"❓ Resultado desconhecido ao ir para {target['name']}.")
        status = "UNKNOWN"

    write_log_row(
        writer=writer,
        pose_monitor=pose_monitor,
        waypoint_index=waypoint_index,
        target=target,
        distancia_restante=0.0,
        status=status,
    )

    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sim", action="store_true",
                        help="usa o relógio da simulação (use_sim_time)")
    parser.add_argument("--log-dir", default=".",
                        help="pasta onde o CSV é gravado")
    args = parser.parse_args()

    rclpy.init()

    navigator = BasicNavigator()
    pose_monitor = PoseMonitor()

    if args.sim:
        sim_time = Parameter("use_sim_time", Parameter.Type.BOOL, True)
        navigator.set_parameters([sim_time])
        pose_monitor.set_parameters([sim_time])

    os.makedirs(args.log_dir, exist_ok=True)
    log_path = os.path.join(args.log_dir, LOG_FILE)

    executor = MultiThreadedExecutor()
    executor.add_node(pose_monitor)

    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    try:
        # Define a pose inicial do robô
        initial_pose = build_pose(navigator, START)

        print(
            f"📍 Definindo posição inicial: "
            f"X={START['x']:.2f}, Y={START['y']:.2f}"
        )
        navigator.setInitialPose(initial_pose)

        print("⏳ Aguardando Nav2 ficar ativo...")
        navigator.waitUntilNav2Active()

        print("⏳ Aguardando primeira pose do AMCL...")
        deadline = time.time() + 10.0
        while not pose_monitor.pose_received and time.time() < deadline:
            time.sleep(0.1)
        if not pose_monitor.pose_received:
            print("⚠️ Nenhuma pose do AMCL em 10 s — as primeiras linhas podem sair em (0, 0).")

        with open(log_path, "w", newline="") as f:
            writer = csv.writer(f)

            writer.writerow([
                "Timestamp_Legivel",
                "Unix_Time",
                "Waypoint_Index",
                "Waypoint_Nome",
                "Target_X",
                "Target_Y",
                "Pos_X",
                "Pos_Y",
                "Distancia_Restante",
                "Velocidade_Linear_X_m_s",
                "Velocidade_Linear_Y_m_s",
                "Velocidade_Angular_Z_rad_s",
                "Velocidade_Linear_Total_m_s",
                "Status",
            ])

            print(f"💾 Gravando dados em: {log_path}")

            # Registra uma linha inicial antes de começar a navegação
            write_log_row(
                writer=writer,
                pose_monitor=pose_monitor,
                waypoint_index=0,
                target=START,
                distancia_restante=0.0,
                status="START",
            )

            # Navega: ponto inicial -> ponto médio -> ponto final
            for index, target in enumerate(ROUTE, start=1):
                result = navigate_to_target(
                    navigator=navigator,
                    pose_monitor=pose_monitor,
                    writer=writer,
                    waypoint_index=index,
                    target=target,
                )

                if result != TaskResult.SUCCEEDED:
                    print("🛑 Encerrando rota porque um trecho não foi concluído com sucesso.")
                    break

        print("🏁 Teste finalizado.")

    finally:
        executor.shutdown()
        pose_monitor.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()