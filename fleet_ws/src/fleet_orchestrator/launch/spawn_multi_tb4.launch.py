#!/usr/bin/env python3
"""
Spawna UM TurtleBot4 namespaced dentro de um mundo Gazebo já em execução.

Usado por turtlebot4_multi_sim.launch.py para subir 3 robôs (tb1/tb2/tb3) no
mesmo mundo. Ao contrário de nav2_minimal_tb4_sim/spawn_tb4.launch.py (que só
funciona para 1 robô sem namespace), este arquivo:

  1. Usa o xacro forkado em urdf/tb4/ (fleet_orchestrator) que prefixa todo
     tópico gz-transport (cmd_vel, odom, tf, joint_states, imu, scan,
     rgbd_camera) com /<namespace> — sem isso, o plugin DiffDrive do TB4
     publica em tópicos absolutos fixos e todos os robôs colidiriam
     (confirmado empiricamente: um /cmd_vel movia todos).
  2. Gera uma cópia por-robô do tb4_bridge.yaml original (mesmo padrão que
     turtlebot4_sim.launch.py já usa para nav2.yaml via _make_nav2_params).
  3. Spawna com `-name <robot_name>` (não `-entity` — essa flag não existe
     no binário `ros_gz_sim create` desta versão e é silenciosamente
     ignorada; confirmado testando os dois manualmente).

Uso: incluído via IncludeLaunchDescription, nunca standalone (depende de um
mundo Gazebo já rodando).
"""
import os
import tempfile

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import Command, LaunchConfiguration
from launch_ros.actions import Node

ARGUMENTS = [
    DeclareLaunchArgument("namespace", description="Namespace/nome do robô (ex: tb1)"),
    DeclareLaunchArgument("robot_name", default_value=""),
    DeclareLaunchArgument("x_pose", default_value="0.0"),
    DeclareLaunchArgument("y_pose", default_value="0.0"),
    DeclareLaunchArgument("z_pose", default_value="0.01"),
    DeclareLaunchArgument("yaw", default_value="0.0"),
    DeclareLaunchArgument("use_sim_time", default_value="true"),
    DeclareLaunchArgument(
        "enable_camera_bridge", default_value="false",
        description="Liga image_bridge (RGBD) — nada no fleet_orchestrator/collector consome isso hoje; "
                    "é o custo de renderização mais alto sem GPU, então fica desligado por padrão.",
    ),
]


def _make_bridge_yaml(namespace: str) -> str:
    """Copia tb4_bridge.yaml prefixando ros_topic_name/gz_topic_name com /<namespace>
    (mesmo padrão do xacro forkado). O tópico clock fica global/compartilhado."""
    sim_dir = get_package_share_directory("nav2_minimal_tb4_sim")
    src = os.path.join(sim_dir, "configs", "tb4_bridge.yaml")
    with open(src) as f:
        entries = yaml.safe_load(f)

    prefix = f"/{namespace}" if namespace else ""
    for entry in entries:
        if entry.get("ros_topic_name") == "clock":
            continue
        entry["ros_topic_name"] = prefix + "/" + entry["ros_topic_name"].lstrip("/")
        entry["gz_topic_name"] = prefix + "/" + entry["gz_topic_name"].lstrip("/")

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=f"_tb4_bridge_{namespace}.yaml", delete=False)
    yaml.safe_dump(entries, tmp)
    tmp.close()
    return tmp.name


def launch_setup(context, *args, **kwargs):
    namespace = LaunchConfiguration("namespace").perform(context)
    robot_name = LaunchConfiguration("robot_name").perform(context) or namespace
    use_sim_time = LaunchConfiguration("use_sim_time")
    enable_camera_bridge = LaunchConfiguration("enable_camera_bridge").perform(context).lower() in ("true", "1", "yes")

    urdf_path = os.path.join(
        get_package_share_directory("fleet_orchestrator"), "urdf", "tb4", "standard", "turtlebot4.urdf.xacro"
    )
    bridge_yaml = _make_bridge_yaml(namespace)

    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        name="robot_state_publisher",
        namespace=namespace,
        output="screen",
        parameters=[{
            "use_sim_time": use_sim_time,
            "robot_description": Command(["xacro", " ", urdf_path, " namespace:=", namespace]),
        }],
        remappings=[("/tf", "tf"), ("/tf_static", "tf_static")],
    )

    bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        name=f"bridge_ros_gz_{namespace}",
        output="screen",
        parameters=[{"config_file": bridge_yaml, "use_sim_time": use_sim_time}],
    )

    spawn = Node(
        package="ros_gz_sim",
        executable="create",
        output="screen",
        arguments=[
            "-name", robot_name,
            "-topic", f"/{namespace}/robot_description",
            "-x", LaunchConfiguration("x_pose"),
            "-y", LaunchConfiguration("y_pose"),
            "-z", LaunchConfiguration("z_pose"),
            "-Y", LaunchConfiguration("yaw"),
        ],
        parameters=[{"use_sim_time": use_sim_time}],
    )

    actions = [robot_state_publisher, bridge, spawn]

    if enable_camera_bridge:
        for suffix in ("image", "depth_image"):
            actions.append(Node(
                package="ros_gz_image",
                executable="image_bridge",
                name=f"bridge_gz_ros_camera_{suffix}_{namespace}",
                output="screen",
                parameters=[{"use_sim_time": use_sim_time}],
                arguments=[f"/{namespace}/rgbd_camera/{suffix}"],
            ))

    return actions


def generate_launch_description():
    return LaunchDescription(ARGUMENTS + [OpaqueFunction(function=launch_setup)])
