#!/usr/bin/env python3
"""
TurtleBot4 — simulação com 3 robôs (tb1, tb2, tb3) no mesmo mundo Gazebo.

Sibling de turtlebot4_sim.launch.py (que continua servindo só 1 robô,
intocado, como fallback/regressão). Este arquivo:

  1. Sobe o servidor Gazebo uma única vez (réplica da metade "servidor" de
     nav2_minimal_tb4_sim/simulation.launch.py — não a inclui inteira porque
     ela também spawna 1 robô sem namespace com o xacro NÃO forkado).
  2. Spawna tb1/tb2/tb3 via spawn_multi_tb4.launch.py (xacro forkado,
     tópicos gz-transport prefixados por robô).
  3. Sobe SLAM Toolbox e Nav2 por robô via os launch files ORIGINAIS e
     intocados do turtlebot4_navigation (já suportam `namespace` de fábrica:
     remapeiam /tf -> /<namespace>/tf internamente, frame_ids continuam sem
     prefixo — é essa a convenção padrão do Nav2 pra multi-robô, e é por
     isso que fleet_orchestrator passou a ter 1 TF buffer por robô).

Uso:
  ros2 launch fleet_orchestrator turtlebot4_multi_sim.launch.py
  ros2 launch fleet_orchestrator turtlebot4_multi_sim.launch.py headless:=false enable_camera_bridge:=true
"""
import os
import tempfile

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    AppendEnvironmentVariable,
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    TimerAction,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node

# Lido no import (este arquivo é reexecutado a cada `ros2 launch`), não como
# LaunchConfiguration, porque ROBOTS decide QUANTOS nós existem no
# LaunchDescription — isso tem que estar resolvido antes de generate_launch_
# description() rodar, uma lista de LaunchConfiguration não dá pra iterar.
#
# Default caiu de 3 para 2 robôs: rodar os 3 ao mesmo tempo sem GPU deixa o
# Nav2 instável sob carga (NAV2_ABORTED recorrente, ~600%+ CPU — ver
# orquestracion.md). tb1+tb2 já cobrem a demo de múltiplos agentes de forma
# confiável; use FLEET_ROBOTS=tb1,tb2,tb3 para voltar aos 3.
ROBOTS = [r.strip() for r in os.environ.get("FLEET_ROBOTS", "tb1,tb2").split(",") if r.strip()]
# Espaçados ~2m em y — checar manualmente com headless:=false antes de confiar
# de olhos fechados (não há garantia de que essas poses estão livres de
# obstáculo em warehouse.sdf só de ler o SDF estaticamente).
DEFAULT_POSES = {
    "tb1": ("0.0", "0.0", "0.0"),
    "tb2": ("0.0", "2.0", "0.0"),
    "tb3": ("0.0", "4.0", "0.0"),
}


def _make_nav2_params(_ctx):
    """Idêntico ao helper de turtlebot4_sim.launch.py — o conteúdo não é
    específico de robô, então um único arquivo serve para os 3 includes."""
    pkg_nav4 = get_package_share_directory('turtlebot4_navigation')
    src = os.path.join(pkg_nav4, 'config', 'nav2.yaml')
    with open(src) as f:
        cfg = yaml.safe_load(f)

    def _patch(d):
        if isinstance(d, dict):
            for k, v in d.items():
                if k == 'enable_stamped_cmd_vel':
                    d[k] = False
                else:
                    _patch(v)

    _patch(cfg)

    # nav2.yaml estoque do TB4 força regenerate_noises:true no MPPI, contra o
    # próprio default recomendado pelo Nav2 (false) — achado do agente
    # experiment-nav2-tracking (ver conhecimento/nav2_tracking.md e
    # implementacao.md). Default aqui preserva o comportamento já usado em
    # toda campanha reportada até agora; para o experimento candidato use
    # NAV2_MPPI_REGENERATE_NOISES=false (mesmo padrão de FLEET_ROBOTS).
    regenerate_noises = os.environ.get('NAV2_MPPI_REGENERATE_NOISES', 'true').strip().lower() not in ('false', '0', 'no')
    try:
        cfg['controller_server']['ros__parameters']['FollowPath']['regenerate_noises'] = regenerate_noises
    except KeyError:
        pass

    # Trims CPU cost per robot for the 3x multi-robot case (stock values are
    # tuned for 1 robot with a GPU-backed lidar; here it's 3x software-
    # rendered, no GPU — measured ~630% CPU across 3 TB4s before this).
    # local_costmap update/publish 5/2 -> 3/1Hz cuts how often each robot's
    # 3x3m rolling costmap gets recomputed. Global costmap already ticks at
    # 1Hz stock, left untouched.
    #
    # controller_frequency was also tried at 10Hz (down from stock 20Hz) but
    # that broke tb1's bringup: nav2_controller validates its period against
    # the sim's physics step ("Controller period more then model dt"), so
    # halving it isn't safe without also checking/raising the world's
    # max_step_size — left at stock for now.
    try:
        lc = cfg['local_costmap']['local_costmap']['ros__parameters']
        lc['update_frequency'] = 3.0
        lc['publish_frequency'] = 1.0
    except KeyError:
        pass

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='_nav2_multi.yaml', delete=False)
    yaml.safe_dump(cfg, tmp)
    tmp.close()
    return tmp.name


ARGUMENTS = [
    DeclareLaunchArgument("world", default_value="warehouse", description="Mundo: warehouse | depot"),
    DeclareLaunchArgument(
        "headless", default_value="true",
        description="Sem GUI do gzclient por padrão — stack 3x mais pesada que o modo 1-robô.",
    ),
    DeclareLaunchArgument("enable_camera_bridge", default_value="false"),
    DeclareLaunchArgument(
        "bringup_nav", default_value="true",
        description="Sobe SLAM+Nav2 de todos os robôs junto com o mundo. "
                    "bringup_nav:=false deixa só Gazebo + modelos spawnados "
                    "(visíveis, parados) — pra ligar a navegação de 1 robô "
                    "por vez depois via activate_robot_nav.launch.py, evitando "
                    "rodar N pilhas de Nav2 completas ao mesmo tempo (ver "
                    "'Detected jump back in time' em orquestracion.md).",
    ),
]
for rid, (x, y, yaw) in DEFAULT_POSES.items():
    ARGUMENTS += [
        DeclareLaunchArgument(f"{rid}_x", default_value=x),
        DeclareLaunchArgument(f"{rid}_y", default_value=y),
        DeclareLaunchArgument(f"{rid}_yaw", default_value=yaw),
    ]


def generate_launch_description():
    pkg_minimal = get_package_share_directory('nav2_minimal_tb4_sim')
    pkg_nav4 = get_package_share_directory('turtlebot4_navigation')
    orchestrator_launch_dir = os.path.join(
        get_package_share_directory('fleet_orchestrator'), 'launch'
    )

    world_path = PathJoinSubstitution([pkg_minimal, 'worlds', [LaunchConfiguration('world'), '.sdf']])
    headless = LaunchConfiguration('headless')

    # ── Servidor Gazebo, uma vez só (réplica de simulation.launch.py, sem o
    #    spawn de robô embutido que ela faz) ──────────────────────────────
    world_sdf = tempfile.mktemp(prefix='nav2_multi_', suffix='.sdf')
    world_sdf_xacro = ExecuteProcess(cmd=['xacro', '-o', world_sdf, ['headless:=', headless], world_path])

    set_env_vars_resources = AppendEnvironmentVariable(
        'GZ_SIM_RESOURCE_PATH',
        os.path.join(get_package_share_directory('nav2_minimal_tb4_description'), '..'),
    )

    gazebo_server = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('ros_gz_sim'), 'launch', 'gz_sim.launch.py')
        ),
        launch_arguments={'gz_args': ['-r -s ', world_sdf]}.items(),
    )
    gazebo_client = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('ros_gz_sim'), 'launch', 'gz_sim.launch.py')
        ),
        condition=UnlessCondition(headless),
        launch_arguments={'gz_args': ['-v4 -g ']}.items(),
    )

    # ── /clock: 1 bridge compartilhado por todos os robôs ─────────────────
    clock_yaml = tempfile.NamedTemporaryFile(mode='w', suffix='_clock_bridge.yaml', delete=False)
    yaml.safe_dump([{
        'ros_topic_name': 'clock', 'gz_topic_name': '/clock',
        'ros_type_name': 'rosgraph_msgs/msg/Clock', 'gz_type_name': 'gz.msgs.Clock',
        'direction': 'GZ_TO_ROS',
    }], clock_yaml)
    clock_yaml.close()
    clock_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name='bridge_ros_gz_clock',
        output='screen',
        parameters=[{'config_file': clock_yaml.name}],
    )

    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(set_env_vars_resources)
    ld.add_action(world_sdf_xacro)
    ld.add_action(gazebo_server)
    ld.add_action(gazebo_client)
    ld.add_action(clock_bridge)

    # ── Spawn dos 3 robôs (xacro forkado, tópicos por-robô) ───────────────
    for i, rid in enumerate(ROBOTS):
        spawn = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(orchestrator_launch_dir, 'spawn_multi_tb4.launch.py')
            ),
            launch_arguments={
                'namespace': rid,
                'robot_name': rid,
                'x_pose': LaunchConfiguration(f'{rid}_x'),
                'y_pose': LaunchConfiguration(f'{rid}_y'),
                'yaw': LaunchConfiguration(f'{rid}_yaw'),
                'enable_camera_bridge': LaunchConfiguration('enable_camera_bridge'),
            }.items(),
        )
        ld.add_action(TimerAction(period=float(i) * 2.0, actions=[spawn]))

    # ── SLAM Toolbox por robô (launch file original, intocado) ────────────
    # Stagger generoso: 3 instâncias do solver Ceres competindo por CPU no
    # boot já causou 1 timeout real de lifecycle (change_state) numa corrida
    # mais apertada (8s) — 12s dá folga suficiente pra cada uma estabilizar
    # antes da próxima competir por CPU.
    bringup_nav = LaunchConfiguration('bringup_nav')
    for i, rid in enumerate(ROBOTS):
        slam = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(pkg_nav4, 'launch', 'slam.launch.py')),
            launch_arguments=[('namespace', rid), ('use_sim_time', 'true'), ('sync', 'true')],
            condition=IfCondition(bringup_nav),
        )
        ld.add_action(TimerAction(period=10.0 + float(i) * 12.0, actions=[slam]))

    # ── Nav2 por robô (launch file original, intocado; params compartilhados) ─
    nav2_params_file = _make_nav2_params(None)
    for i, rid in enumerate(ROBOTS):
        nav2 = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(pkg_nav4, 'launch', 'nav2.launch.py')),
            launch_arguments=[
                ('namespace', rid),
                ('use_sim_time', 'true'),
                ('params_file', nav2_params_file),
            ],
            condition=IfCondition(bringup_nav),
        )
        ld.add_action(TimerAction(period=50.0 + float(i) * 12.0, actions=[nav2]))

    return ld
