#!/usr/bin/env python3
"""
TurtleBot4 Standard — simulação via nav2_minimal_tb4_sim (Gazebo Harmonic nativo).

Usa o pacote mínimo do Nav2 que resolve problemas de compatibilidade do
irobot_create_gz_plugins com Gazebo Harmonic (Issues #81, #94, #563).

Mundos disponíveis: warehouse (padrão), depot

Uso:
  ros2 launch fleet_orchestrator turtlebot4_sim.launch.py
  ros2 launch fleet_orchestrator turtlebot4_sim.launch.py world:=depot
"""
import os
import tempfile
import yaml

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    OpaqueFunction,
    TimerAction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


def _make_nav2_params(_ctx):
    """Lê o nav2.yaml do TB4, força enable_stamped_cmd_vel=False e grava num temp file.

    O bridge nav2_minimal_tb4_sim usa geometry_msgs/Twist (não TwistStamped),
    por isso o Nav2 tem de publicar sem stamp. Fix para Issue #94.
    """
    pkg_nav4 = get_package_share_directory('turtlebot4_navigation')
    src = os.path.join(pkg_nav4, 'config', 'nav2.yaml')
    with open(src) as f:
        cfg = yaml.safe_load(f)

    # Percorre todos os nós e desactiva stamped cmd_vel
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

    # Rotas longas (percurso do CBSoft, ~95 m): o BT replaneja a 1 Hz e só
    # espera 20 ms (default_server_timeout do TB4) o planner aceitar o pedido;
    # com o NavFn ainda calculando o anterior, estoura e aborta a navegação
    # inteira. Opt-in por env para não mudar as campanhas já reportadas.
    server_timeout = os.environ.get('NAV2_DEFAULT_SERVER_TIMEOUT_MS', '').strip()
    if server_timeout:
        cfg['bt_navigator']['ros__parameters']['default_server_timeout'] = int(server_timeout)
    if os.environ.get('NAV2_NAVFN_USE_ASTAR', '').strip().lower() in ('true', '1', 'yes'):
        cfg['planner_server']['ros__parameters']['GridBased']['use_astar'] = True

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='_nav2.yaml', delete=False)
    yaml.safe_dump(cfg, tmp)
    tmp.close()
    return tmp.name


_GROUND_TRUTH_ROBOT_INDEX = {'cbsoft_open': 0}


def _make_localization_params(x, y, yaw):
    """localization.yaml do TB4 com a pose inicial do AMCL igual à pose de spawn.

    Sem isso o AMCL só publica map→odom depois que alguém manda /initialpose,
    e o Nav2/frontend ficam parados até lá.
    """
    pkg_nav4 = get_package_share_directory('turtlebot4_navigation')
    with open(os.path.join(pkg_nav4, 'config', 'localization.yaml')) as f:
        cfg = yaml.safe_load(f)
    amcl = cfg['amcl']['ros__parameters']
    amcl['set_initial_pose'] = True
    amcl['initial_pose'] = {'x': float(x), 'y': float(y), 'z': 0.0, 'yaw': float(yaw)}
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='_localization.yaml', delete=False)
    yaml.safe_dump(cfg, tmp)
    tmp.close()
    return tmp.name


ARGUMENTS = [
    DeclareLaunchArgument('world', default_value='warehouse',
                          description='Mundo: warehouse | depot | cbsoft_open'),
    DeclareLaunchArgument('localization', default_value='slam',
                          description='slam (mapeia ao vivo) | amcl (mapa pronto em maps/<world>.yaml)'),
    DeclareLaunchArgument('x_pose', default_value='0.0'),
    DeclareLaunchArgument('y_pose', default_value='0.0'),
    DeclareLaunchArgument('yaw',    default_value='0.0'),
    DeclareLaunchArgument('headless', default_value='False',
                          description='Sem GUI do Gazebo (mesmo padrão de turtlebot4_multi_sim.launch.py)'),
]


def _launch_setup(context, *args, **kwargs):
    pkg_minimal = get_package_share_directory('nav2_minimal_tb4_sim')
    pkg_nav4    = get_package_share_directory('turtlebot4_navigation')

    # Capturado como string Python simples, AQUI, antes de qualquer
    # IncludeLaunchDescription rodar. Achado ao vivo (2026-09-30): o include
    # de `sim` abaixo passa 'world' como argumento pro simulation.launch.py
    # do vendor com o CAMINHO COMPLETO do .sdf (não o nome simples) — e como
    # LaunchConfiguration é um dicionário global compartilhado no launch,
    # isso SOBRESCREVE o valor de 'world' pro resto da árvore de launch.
    # O bridge de ground truth (abaixo) que lesse LaunchConfiguration('world')
    # depois disso pegaria o caminho completo por engano, não "warehouse".
    world_name = LaunchConfiguration('world').perform(context)
    localization = LaunchConfiguration('localization').perform(context)

    pkg_fleet = get_package_share_directory('fleet_orchestrator')
    own_world = os.path.join(pkg_fleet, 'worlds', f'{world_name}.sdf')
    if os.path.exists(own_world):
        world_path = own_world
    else:
        world_path = PathJoinSubstitution([pkg_minimal, 'worlds', [world_name, '.sdf']])

    # ── Simulação mínima TB4 (Gazebo Harmonic nativo) ─────────────────────────
    sim_args = [
        ('world',   world_path),
        ('headless', LaunchConfiguration('headless')),
        ('x_pose',  LaunchConfiguration('x_pose')),
        ('y_pose',  LaunchConfiguration('y_pose')),
        ('yaw',     LaunchConfiguration('yaw')),
    ]
    # O launch do vendor sempre abre o RViz, sem opção de desligar. Sem GUI,
    # ele vai com uma config vazia a 1 fps: com a config padrão consome ~270%
    # de CPU e, junto com a GUI do Gazebo, o Nav2 aborta trajetos longos.
    if LaunchConfiguration('headless').perform(context).lower() == 'true':
        sim_args.append(('rviz_config_file', os.path.join(pkg_fleet, 'config', 'rviz_minimal.rviz')))
    sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(pkg_minimal, 'launch', 'simulation.launch.py')
        ),
        launch_arguments=sim_args,
    )

    # ── Ground truth: pose real do robô no mundo Gazebo, direto da cena ──────
    # (não é odometria por integração de roda — é a pose exata que o Gazebo
    # mantém internamente para cada entidade, sem ruído/deriva nenhuma).
    # Confirmado ao vivo (orquestracion.md, "Plano: campanha /odom vs /pose vs
    # ground truth") que /world/<world>/dynamic_pose/info já publica isso de
    # fábrica, sem precisar de plugin novo no xacro/SDF — só bridgear.
    gz_topic = f"/world/{world_name}/dynamic_pose/info"
    ground_truth_bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name='bridge_ground_truth',
        output='screen',
        arguments=[f"{gz_topic}@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V"],
        remappings=[(gz_topic, 'ground_truth_pose')],
    )

    # O bridge acima perde o nome de cada entidade (child_frame_id vazio) —
    # este nó extrai só a entrada do robô por índice fixo e publica como
    # PoseStamped limpo (ver fleet_orchestrator/ground_truth_filter.py).
    # Índice do robô no array de dynamic_pose depende do mundo: no warehouse
    # há 2 entidades dinâmicas antes dele; no cbsoft_open (tudo estático) ele
    # é o primeiro. Conferido ao vivo comparando com a pose de spawn.
    gt_params = {'use_sim_time': True}
    if world_name in _GROUND_TRUTH_ROBOT_INDEX:
        gt_params['robot_index'] = _GROUND_TRUTH_ROBOT_INDEX[world_name]
    ground_truth_filter = Node(
        package='fleet_orchestrator',
        executable='ground_truth_filter',
        name='ground_truth_filter',
        output='screen',
        parameters=[gt_params],
    )

    # ── Localização (8s após Gazebo): SLAM Toolbox ou map_server + AMCL ───────
    if localization == 'amcl':
        map_yaml = os.path.join(pkg_fleet, 'maps', f'{world_name}.yaml')
        if not os.path.exists(map_yaml):
            raise RuntimeError(f'localization:=amcl exige mapa pronto em {map_yaml}')
        localizer = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(pkg_nav4, 'launch', 'localization.launch.py')
            ),
            launch_arguments=[
                ('use_sim_time', 'true'),
                ('map', map_yaml),
                ('params', _make_localization_params(
                    LaunchConfiguration('x_pose').perform(context),
                    LaunchConfiguration('y_pose').perform(context),
                    LaunchConfiguration('yaw').perform(context),
                )),
            ],
        )
    elif localization == 'slam':
        localizer = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(pkg_nav4, 'launch', 'slam.launch.py')
            ),
            launch_arguments=[('use_sim_time', 'true'), ('sync', 'true')],
        )
    else:
        raise RuntimeError(f'localization inválido: {localization!r} (use slam | amcl)')
    slam = TimerAction(period=8.0, actions=[localizer])

    # ── Nav2 (12s após Gazebo) ────────────────────────────────────────────────
    # Gera params com enable_stamped_cmd_vel=False (bridge usa Twist, não TwistStamped)
    nav2_params_file = _make_nav2_params(None)
    nav2 = TimerAction(
        period=12.0,
        actions=[IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(pkg_nav4, 'launch', 'nav2.launch.py')
            ),
            launch_arguments=[
                ('use_sim_time', 'true'),
                ('params_file', nav2_params_file),
            ],
        )],
    )

    return [sim, ground_truth_bridge, ground_truth_filter, slam, nav2]


def generate_launch_description():
    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(OpaqueFunction(function=_launch_setup))
    return ld
