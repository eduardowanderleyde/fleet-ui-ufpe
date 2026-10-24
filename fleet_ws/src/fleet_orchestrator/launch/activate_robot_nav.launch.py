#!/usr/bin/env python3
"""
Liga SLAM Toolbox + Nav2 pra UM robô só, contra uma simulação que já está
de pé (Gazebo + modelos spawnados via turtlebot4_multi_sim.launch.py
bringup_nav:=false) — não sobe Gazebo nem spawna robô nenhum.

Existe pra dar suporte ao modo "1 robô ativo por vez" da Missão Coordenada:
rodar N pilhas de Nav2 completas ao mesmo tempo faz o /clock simulado saltar
pra trás sob a carga combinada ("Detected jump back in time", ver
orquestracion.md) — mas os robôs continuam todos visíveis/parados na cena
o tempo todo, só a navegação de cada um liga/desliga por vez.

Uso:
  ros2 launch fleet_orchestrator activate_robot_nav.launch.py namespace:=tb2

Pra desligar: mata o processo group inteiro (SIGTERM/SIGKILL) — não tem
comando "unload" de lifecycle nodes aqui, é o mesmo padrão que o resto do
projeto já usa pra parar a simulação inteira (ver _stop_simulation em
backend/main.py).
"""
import tempfile

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.actions import IncludeLaunchDescription
from launch.substitutions import LaunchConfiguration
import os


def _make_nav2_params(_ctx):
    """Cópia do helper de turtlebot4_multi_sim.launch.py — mesmo ajuste de
    frequência de costmap pra não pesar tanto por robô (ver lá o porquê)."""
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

    try:
        lc = cfg['local_costmap']['local_costmap']['ros__parameters']
        lc['update_frequency'] = 3.0
        lc['publish_frequency'] = 1.0
    except KeyError:
        pass

    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='_nav2_activate.yaml', delete=False)
    yaml.safe_dump(cfg, tmp)
    tmp.close()
    return tmp.name


ARGUMENTS = [
    DeclareLaunchArgument("namespace", description="Namespace do robô (ex.: tb1, tb2) — obrigatório."),
]


def generate_launch_description():
    pkg_nav4 = get_package_share_directory('turtlebot4_navigation')
    orchestrator_launch_dir = os.path.join(
        get_package_share_directory('fleet_orchestrator'), 'launch'
    )
    namespace = LaunchConfiguration('namespace')
    nav2_params_file = _make_nav2_params(None)

    slam = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(pkg_nav4, 'launch', 'slam.launch.py')),
        launch_arguments=[('namespace', namespace), ('use_sim_time', 'true'), ('sync', 'true')],
    )
    # nav2_minimal.launch.py (nosso, não o nav2.launch.py do vendor) — sobe só
    # os servidores que go_to_point usa de verdade, cortando ~30% da rajada
    # de nós por robô (ver docstring do arquivo pro porquê).
    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(orchestrator_launch_dir, 'nav2_minimal.launch.py')),
        launch_arguments=[
            ('namespace', namespace),
            ('use_sim_time', 'true'),
            ('params_file', nav2_params_file),
        ],
    )

    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(slam)
    ld.add_action(nav2)
    return ld
