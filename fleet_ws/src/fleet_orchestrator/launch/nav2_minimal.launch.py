#!/usr/bin/env python3
"""
Versão enxuta de nav2_bringup/launch/navigation_launch.py — sobe só os
servidores que o fluxo go_to_point (NavigateToPose com 1 pose, sem rota,
sem múltiplos waypoints, sem doca) realmente usa.

Cortado em relação ao original (confirmado contra a árvore de
comportamento padrão do Nav2, navigate_to_pose_w_replanning_and_recovery.xml,
que não referencia nenhum dos dois):
  - route_server       (navegação por grafo de rotas nomeadas — não é o
                         que go_to_point nem play_route fazem)
  - docking_server      (auto-doca — não usado)

Mantido (controller_server, smoother_server, planner_server,
behavior_server, bt_navigator, velocity_smoother, collision_monitor,
waypoint_follower, lifecycle_manager) — a árvore padrão chama
smoother_server (SmoothPath) e behavior_server (spin/backup/wait de
recuperação), cortar esses quebraria a navegação de verdade.
`waypoint_follower` foi cortado originalmente (2026-09-30) por engano de
escopo — corrigido em 2026-10-03: `play_route` (campanhas de
repetibilidade via `FollowWaypoints`, não só `go_to_point`) também passa
por este arquivo quando a navegação é ativada via
`activate_robot_nav.launch.py`, e sem `waypoint_follower` a action fica
listada mas sem nenhum servidor respondendo (`Nav2 follow_waypoints not
available`). Achado ao vivo rodando uma campanha multi-robô pela
primeira vez neste caminho.

Existe porque nav2_bringup/launch/navigation_launch.py não expõe nenhum
jeito de desligar servidor individual via argumento de launch — a lista
de lifecycle_nodes está hardcoded no arquivo. Motivação: achado ao vivo
(2026-09-30, orquestracion.md) de que a rajada de ~15-18 nós na ativação
de cada robô sobrecarrega a descoberta DDS o bastante pra causar "jump
back in time" — reduzir o número de nós reduz essa rajada.

Usado só por activate_robot_nav.launch.py, no lugar do
turtlebot4_navigation/nav2.launch.py padrão (que inclui a versão
completa).
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace, SetParameter, SetRemap
from launch_ros.descriptions import ParameterFile
from nav2_common.launch import RewrittenYaml

ARGUMENTS = [
    DeclareLaunchArgument('namespace', default_value='', description='Robot namespace'),
    DeclareLaunchArgument('use_sim_time', default_value='false', description='Use sim time'),
    DeclareLaunchArgument('params_file', description='Full path to the Nav2 params YAML'),
    DeclareLaunchArgument('autostart', default_value='true', description='Autostart o lifecycle manager'),
    DeclareLaunchArgument('log_level', default_value='info', description='Log level'),
]

LIFECYCLE_NODES = [
    'controller_server',
    'smoother_server',
    'planner_server',
    'behavior_server',
    'velocity_smoother',
    'collision_monitor',
    'bt_navigator',
    'waypoint_follower',
]


def _launch_setup(context, *args, **kwargs):
    namespace = LaunchConfiguration('namespace')
    use_sim_time = LaunchConfiguration('use_sim_time')
    autostart = LaunchConfiguration('autostart')
    params_file = LaunchConfiguration('params_file')
    log_level = LaunchConfiguration('log_level')

    # Mesmo remap que turtlebot4_navigation/nav2.launch.py faz — sem isso os
    # costmaps assinam o tópico de scan errado (namespace_str + default do
    # Nav2, não o /scan de verdade do robô) e nunca enxergam o lidar.
    namespace_str = namespace.perform(context)
    if namespace_str and not namespace_str.startswith('/'):
        namespace_str = '/' + namespace_str
    scan_remaps = [
        SetRemap(namespace_str + '/global_costmap/scan', namespace_str + '/scan'),
        SetRemap(namespace_str + '/local_costmap/scan', namespace_str + '/scan'),
    ]

    remappings = [('/tf', 'tf'), ('/tf_static', 'tf_static')]

    configured_params = ParameterFile(
        RewrittenYaml(
            source_file=params_file,
            root_key=namespace,
            param_rewrites={'autostart': autostart},
            convert_types=True,
        ),
        allow_substs=True,
    )

    common_node_kwargs = dict(
        output='screen',
        respawn=False,
        respawn_delay=2.0,
        parameters=[configured_params],
        arguments=['--ros-args', '--log-level', log_level],
    )

    nodes = [
        PushRosNamespace(namespace),
        *scan_remaps,
        SetParameter('use_sim_time', use_sim_time),
        Node(package='nav2_controller', executable='controller_server',
             remappings=remappings + [('cmd_vel', 'cmd_vel_nav')], **common_node_kwargs),
        Node(package='nav2_smoother', executable='smoother_server', name='smoother_server',
             remappings=remappings, **common_node_kwargs),
        Node(package='nav2_planner', executable='planner_server', name='planner_server',
             remappings=remappings, **common_node_kwargs),
        Node(package='nav2_behaviors', executable='behavior_server', name='behavior_server',
             remappings=remappings + [('cmd_vel', 'cmd_vel_nav')], **common_node_kwargs),
        Node(package='nav2_bt_navigator', executable='bt_navigator', name='bt_navigator',
             remappings=remappings, **common_node_kwargs),
        Node(package='nav2_velocity_smoother', executable='velocity_smoother', name='velocity_smoother',
             remappings=remappings + [('cmd_vel', 'cmd_vel_nav')], **common_node_kwargs),
        Node(package='nav2_collision_monitor', executable='collision_monitor', name='collision_monitor',
             remappings=remappings, **common_node_kwargs),
        # Reintroduzido (2026-10-03, ver orquestracion.md): a ativacao
        # sequencial multi-robo so precisava de go_to_point (NavigateToPose,
        # 1 pose por vez) quando este arquivo foi enxugado em 2026-09-30, por
        # isso waypoint_follower tinha sido cortado -- mas play_route/replay
        # (campanhas de repetibilidade, inclusive via agente de IA) usa
        # FollowWaypoints, que depende deste no. Sem ele, play_route falha
        # com "Nav2 follow_waypoints not available" (action listada mas sem
        # servidor nenhum atendendo -- confirmado com
        # `ros2 action info .../follow_waypoints` mostrando 0 servers).
        Node(package='nav2_waypoint_follower', executable='waypoint_follower', name='waypoint_follower',
             remappings=remappings, **common_node_kwargs),
        Node(
            package='nav2_lifecycle_manager', executable='lifecycle_manager',
            name='lifecycle_manager_navigation', output='screen',
            arguments=['--ros-args', '--log-level', log_level],
            parameters=[{'autostart': autostart}, {'node_names': LIFECYCLE_NODES}],
        ),
    ]

    return [GroupAction(nodes)]


def generate_launch_description():
    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(OpaqueFunction(function=_launch_setup))
    return ld
