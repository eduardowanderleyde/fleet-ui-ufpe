#!/usr/bin/env python3
"""Gera o mundo aberto `cbsoft_open` (Gazebo SDF + mapa PGM/YAML para AMCL).

Reproduz, em simulação, o percurso do experimento BLE do CBSoft'26
(ver nav_3points.py) num espaço aberto:
chão plano, paredes só na borda e pilares espaçados que dão referência ao
LiDAR (alcance 20 m) sem ficar no caminho do robô. O frame `map` coincide
com o frame do mundo Gazebo, então as coordenadas originais do script
(mapa hall_cin_v4) valem sem conversão.

Uso (a partir da raiz do repo):
    python3 fleet_ws/scripts/cbsoft/gen_open_world.py
"""
import math
import os

ROUTE = [
    (1.0216323137283325, 16.61626625061035),    # Ponto_Inicial
    (-2.5490856170654297, -47.34372329711914),  # Ponto_Medio
    (-33.71685791015625, -47.11880874633789),   # Ponto_Final
]

X_MIN, X_MAX = -42.0, 10.0
Y_MIN, Y_MAX = -56.0, 26.0
WALL_T = 0.2
WALL_H = 1.0
PILLAR_SIZE = 0.3
PILLAR_H = 1.0
PILLAR_SPACING = 7.0
PATH_CLEARANCE = 2.5
EDGE_CLEARANCE = 2.0
RESOLUTION = 0.1

PKG_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'src', 'fleet_orchestrator')
WORLD_NAME = 'cbsoft_open'


def _dist_point_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _dist_to_route(px, py):
    return min(
        _dist_point_segment(px, py, *ROUTE[i], *ROUTE[i + 1])
        for i in range(len(ROUTE) - 1)
    )


def _boxes():
    """(nome, cx, cy, sx, sy, sz) de cada obstáculo estático."""
    cx, cy = (X_MIN + X_MAX) / 2, (Y_MIN + Y_MAX) / 2
    w, h = X_MAX - X_MIN, Y_MAX - Y_MIN
    boxes = [
        ('wall_south', cx, Y_MIN, w + WALL_T, WALL_T, WALL_H),
        ('wall_north', cx, Y_MAX, w + WALL_T, WALL_T, WALL_H),
        ('wall_west', X_MIN, cy, WALL_T, h + WALL_T, WALL_H),
        ('wall_east', X_MAX, cy, WALL_T, h + WALL_T, WALL_H),
    ]
    n = 0
    x = X_MIN + EDGE_CLEARANCE
    while x <= X_MAX - EDGE_CLEARANCE:
        y = Y_MIN + EDGE_CLEARANCE
        while y <= Y_MAX - EDGE_CLEARANCE:
            if _dist_to_route(x, y) >= PATH_CLEARANCE:
                boxes.append((f'pillar_{n:03d}', x, y, PILLAR_SIZE, PILLAR_SIZE, PILLAR_H))
                n += 1
            y += PILLAR_SPACING
        x += PILLAR_SPACING
    return boxes


def _box_model(name, x, y, sx, sy, sz):
    geom = f'<box><size>{sx:.3f} {sy:.3f} {sz:.3f}</size></box>'
    return f"""
    <model name="{name}">
      <static>true</static>
      <pose>{x:.3f} {y:.3f} {sz / 2:.3f} 0 0 0</pose>
      <link name="link">
        <collision name="collision"><geometry>{geom}</geometry></collision>
        <visual name="visual">
          <geometry>{geom}</geometry>
          <material><ambient>0.6 0.6 0.65 1</ambient><diffuse>0.6 0.6 0.65 1</diffuse></material>
        </visual>
      </link>
    </model>"""


def write_sdf(boxes, path):
    models = ''.join(_box_model(*b) for b in boxes)
    sdf = f"""<?xml version="1.0"?>
<!-- Gerado por fleet_ws/scripts/cbsoft/gen_open_world.py — não editar à mão. -->
<sdf version="1.6" xmlns:xacro="http://www.ros.org/wiki/xacro">
  <xacro:arg name="headless" default="true"/>
  <world name="{WORLD_NAME}">
    <scene><grid>false</grid></scene>
    <physics name="1ms" type="ode">
      <max_step_size>0.003</max_step_size>
      <real_time_update_rate>1000.0</real_time_update_rate>
      <real_time_factor>1.0</real_time_factor>
    </physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <!-- Sempre, mesmo headless: publica /world/<w>/dynamic_pose/info, de onde
         sai o ground truth (ground_truth_pose_clean). Os mundos do vendor só o
         carregam com GUI. -->
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>

    <light type="directional" name="sun">
      <cast_shadows>false</cast_shadows>
      <pose>0 0 10 0 0 0</pose>
      <diffuse>0.9 0.9 0.9 1</diffuse>
      <specular>0.2 0.2 0.2 1</specular>
      <direction>-0.5 0.1 -0.9</direction>
    </light>

    <model name="ground_plane">
      <static>true</static>
      <link name="link">
        <collision name="collision">
          <geometry><plane><normal>0 0 1</normal><size>200 200</size></plane></geometry>
        </collision>
        <visual name="visual">
          <geometry><plane><normal>0 0 1</normal><size>200 200</size></plane></geometry>
          <material><ambient>0.8 0.8 0.8 1</ambient><diffuse>0.8 0.8 0.8 1</diffuse></material>
        </visual>
      </link>
    </model>
{models}
  </world>
</sdf>
"""
    with open(path, 'w') as f:
        f.write(sdf)


def write_map(boxes, pgm_path, yaml_path):
    width = int(round((X_MAX - X_MIN + 2.0) / RESOLUTION))
    height = int(round((Y_MAX - Y_MIN + 2.0) / RESOLUTION))
    origin_x, origin_y = X_MIN - 1.0, Y_MIN - 1.0
    grid = bytearray([254]) * (width * height)
    for _name, cx, cy, sx, sy, _sz in boxes:
        x0 = int(math.floor((cx - sx / 2 - origin_x) / RESOLUTION))
        x1 = int(math.ceil((cx + sx / 2 - origin_x) / RESOLUTION))
        y0 = int(math.floor((cy - sy / 2 - origin_y) / RESOLUTION))
        y1 = int(math.ceil((cy + sy / 2 - origin_y) / RESOLUTION))
        for gy in range(max(0, y0), min(height, y1)):
            row = (height - 1 - gy) * width
            for gx in range(max(0, x0), min(width, x1)):
                grid[row + gx] = 0
    with open(pgm_path, 'wb') as f:
        f.write(f'P5\n{width} {height}\n255\n'.encode())
        f.write(bytes(grid))
    with open(yaml_path, 'w') as f:
        f.write(
            f'image: {os.path.basename(pgm_path)}\n'
            'mode: trinary\n'
            f'resolution: {RESOLUTION}\n'
            f'origin: [{origin_x}, {origin_y}, 0.0]\n'
            'negate: 0\n'
            'occupied_thresh: 0.65\n'
            'free_thresh: 0.25\n'
        )


def main():
    boxes = _boxes()
    worlds_dir = os.path.join(PKG_DIR, 'worlds')
    maps_dir = os.path.join(PKG_DIR, 'maps')
    os.makedirs(worlds_dir, exist_ok=True)
    os.makedirs(maps_dir, exist_ok=True)
    write_sdf(boxes, os.path.join(worlds_dir, f'{WORLD_NAME}.sdf'))
    write_map(boxes, os.path.join(maps_dir, f'{WORLD_NAME}.pgm'), os.path.join(maps_dir, f'{WORLD_NAME}.yaml'))
    pillars = sum(1 for b in boxes if b[0].startswith('pillar'))
    closest = min(_dist_to_route(b[1], b[2]) for b in boxes if b[0].startswith('pillar'))
    print(f'{WORLD_NAME}: {pillars} pilares, obstáculo mais próximo do percurso a {closest:.2f} m')


if __name__ == '__main__':
    main()
