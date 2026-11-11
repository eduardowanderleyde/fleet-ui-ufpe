#!/usr/bin/env python3
"""
TurtleBot4 real — só o lado do PC: mapa pronto + AMCL + Nav2 (ROS 2 Jazzy).

O robô (Humble) já sobe sozinho os drivers e publica /scan, /odom e /tf. As
actions do Nav2 mudaram entre Humble e Jazzy (FollowWaypoints,
NavigateToPose), então o Nav2 roda aqui, do lado do fleet-ui; com o robô só
trocamos LaserScan/Odometry/TFMessage e /cmd_vel (Twist), que são iguais nas
duas versões. É o mesmo arranjo do setup do CIn (Nav2 no PC, em Docker).

Suporta ROBOT_NAMESPACE para TurtleBot4 com tópicos prefixados (ex.: /tb1/scan).
Quando o namespace está definido, cria bridges que republicam os tópicos do
robô (/tb1/scan, /tb1/tf, etc.) nos tópicos globais que o AMCL/Nav2 esperam
(/scan, /tf, etc.), e /cmd_vel para /tb1/cmd_vel.

Antes: `make robot-check ROBOT_NAMESPACE=tb1`. Depois: `make robot-up ROBOT_NAMESPACE=tb1`.

Uso:
  ros2 launch fleet_orchestrator turtlebot4_real.launch.py
  ros2 launch fleet_orchestrator turtlebot4_real.launch.py map:=hall_cin_v4 x_pose:=1.02 y_pose:=16.62 yaw:=0.0
  ROBOT_NAMESPACE=tb1 ros2 launch fleet_orchestrator turtlebot4_real.launch.py
"""
import importlib.util
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _sim_launch_helpers():
    """Reaproveita os ajustes de nav2.yaml/localization.yaml do launch da
    simulação (cmd_vel sem stamp, timeouts de rota longa, pose inicial do
    AMCL), para o robô real usar exatamente a mesma configuração do Nav2."""
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'turtlebot4_sim.launch.py')
    spec = importlib.util.spec_from_file_location('turtlebot4_sim_launch', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get_namespace() -> str:
    """Retorna o namespace do robô (ROBOT_NAMESPACE), sem barras."""
    return os.environ.get("ROBOT_NAMESPACE", "").strip().strip("/")


ARGUMENTS = [
    DeclareLaunchArgument('map', default_value='hall_cin_v4',
                          description='Mapa em share/fleet_orchestrator/maps/<map>.yaml'),
    # START do percurso CBSoft (nav_3points.py), onde o robô fica no início.
    DeclareLaunchArgument('x_pose', default_value='1.0216323137283325'),
    DeclareLaunchArgument('y_pose', default_value='16.61626625061035'),
    DeclareLaunchArgument('yaw', default_value='0.0'),
]


def _launch_setup(context, *args, **kwargs):
    helpers = _sim_launch_helpers()
    pkg_nav4 = get_package_share_directory('turtlebot4_navigation')
    pkg_fleet = get_package_share_directory('fleet_orchestrator')

    map_name = LaunchConfiguration('map').perform(context)
    map_yaml = os.path.join(pkg_fleet, 'maps', f'{map_name}.yaml')
    if not os.path.exists(map_yaml):
        raise RuntimeError(f'mapa não encontrado: {map_yaml}')

    actions = []
    namespace = _get_namespace()
    
    if namespace:
        from rclpy.qos import QoSProfile, DurabilityPolicy, HistoryPolicy, ReliabilityPolicy
        
        actions.append(Node(
            package='topic_tools',
            executable='relay',
            name='relay_scan',
            output='screen',
            arguments=[f'/{namespace}/scan', '/scan'],
        ))
        actions.append(Node(
            package='topic_tools',
            executable='relay',
            name='relay_odom',
            output='screen',
            arguments=[f'/{namespace}/odom', '/odom'],
        ))
        actions.append(Node(
            package='topic_tools',
            executable='relay',
            name='relay_imu',
            output='screen',
            arguments=[f'/{namespace}/imu', '/imu'],
        ))
        actions.append(Node(
            package='topic_tools',
            executable='relay',
            name='relay_tf',
            output='screen',
            arguments=[f'/{namespace}/tf', '/tf'],
        ))
        actions.append(Node(
            package='topic_tools',
            executable='relay',
            name='relay_tf_static',
            output='screen',
            arguments=[f'/{namespace}/tf_static', '/tf_static'],
        ))
        actions.append(Node(
            package='topic_tools',
            executable='relay',
            name='relay_cmd_vel',
            output='screen',
            arguments=['/cmd_vel', f'/{namespace}/cmd_vel'],
        ))
        actions.append(Node(
            package='topic_tools',
            executable='relay',
            name='relay_joint_states',
            output='screen',
            arguments=[f'/{namespace}/joint_states', '/joint_states'],
        ))
        actions.append(Node(
            package='topic_tools',
            executable='relay',
            name='relay_robot_description',
            output='screen',
            arguments=[f'/{namespace}/robot_description', '/robot_description'],
        ))

    localization = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(pkg_nav4, 'launch', 'localization.launch.py')),
        launch_arguments=[
            ('use_sim_time', 'false'),
            ('map', map_yaml),
            ('params', helpers._make_localization_params(
                LaunchConfiguration('x_pose').perform(context),
                LaunchConfiguration('y_pose').perform(context),
                LaunchConfiguration('yaw').perform(context),
            )),
        ],
    )
    actions.append(localization)

    # Nav2 alguns segundos depois do AMCL publicar map -> odom.
    nav2 = TimerAction(
        period=5.0,
        actions=[IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(pkg_nav4, 'launch', 'nav2.launch.py')),
            launch_arguments=[
                ('use_sim_time', 'false'),
                ('params_file', helpers._make_nav2_params(None)),
            ],
        )],
    )
    actions.append(nav2)
    
    return actions


def generate_launch_description():
    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(OpaqueFunction(function=_launch_setup))
    return ld
