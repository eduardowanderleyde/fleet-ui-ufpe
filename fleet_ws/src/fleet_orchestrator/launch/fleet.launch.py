#!/usr/bin/env python3
"""Launch do fleet: orchestrator + collector.

Simulação 1 robô (map sem prefixo): ``single_robot_sim:=true`` (carrega ``config/single_robot_sim.yaml``).

Nota: ``ros2 launch`` **não** aceita ``--params-file`` como o ``ros2 run``; use o argumento abaixo.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterFile


def launch_setup(context, *args, **kwargs):
    single = context.launch_configurations.get("single_robot_sim", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    pkg = get_package_share_directory("fleet_orchestrator")
    single_yaml = os.path.join(pkg, "config", "single_robot_sim.yaml")

    # Mesma variável usada por turtlebot4_multi_sim.launch.py para decidir
    # quantos robôs sobem na simulação — precisa bater com o que é passado
    # aqui, senão fleet_orchestrator/sensor_collector ficam gerenciando um
    # robô "fantasma" que não existe no Gazebo.
    robots = [r.strip() for r in os.environ.get("FLEET_ROBOTS", "tb1,tb2").split(",") if r.strip()]

    # Robô real não tem /clock: com FLEET_USE_SIM_TIME=false (make robot-up)
    # os nós usam o relógio do sistema. Padrão true = simulação, como antes.
    sim_time = os.environ.get("FLEET_USE_SIM_TIME", "true").strip().lower() not in ("false", "0", "no")

    use_shared = LaunchConfiguration("use_shared_map_frame")
    routes_dir = LaunchConfiguration("routes_dir")
    collections_dir = LaunchConfiguration("collections_dir")

    if single:
        orchestrator = Node(
            package="fleet_orchestrator",
            executable="fleet_orchestrator",
            name="fleet_orchestrator",
            output="screen",
            parameters=[ParameterFile(single_yaml, allow_substs=True), {"use_sim_time": sim_time}],
        )
        collector = Node(
            package="fleet_data_collector",
            executable="sensor_collector",
            name="sensor_collector",
            output="screen",
            parameters=[ParameterFile(single_yaml, allow_substs=True), {"use_sim_time": sim_time}],
        )
    else:
        orchestrator = Node(
            package="fleet_orchestrator",
            executable="fleet_orchestrator",
            name="fleet_orchestrator",
            output="screen",
            parameters=[
                {"routes_dir": routes_dir, "use_shared_map_frame": use_shared, "use_sim_time": sim_time},
                {"robots": robots},
            ],
        )
        collector = Node(
            package="fleet_data_collector",
            executable="sensor_collector",
            name="sensor_collector",
            output="screen",
            parameters=[
                {"collections_dir": collections_dir, "use_sim_time": sim_time},
                {"robots": robots},
            ],
        )
    return [orchestrator, collector]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "single_robot_sim",
            default_value="false",
            description="Se true, carrega config/single_robot_sim.yaml (robots [''], map partilhado).",
        ),
        DeclareLaunchArgument(
            "use_shared_map_frame",
            default_value="false",
            description="Frame 'map' sem prefixo. true para sim ou mapa único (modo multi).",
        ),
        DeclareLaunchArgument("routes_dir", default_value="routes"),
        DeclareLaunchArgument("collections_dir", default_value="collections"),
        OpaqueFunction(function=launch_setup),
    ])
