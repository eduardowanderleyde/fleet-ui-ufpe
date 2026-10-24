from setuptools import setup
import os
from glob import glob

package_name = 'fleet_orchestrator'


def _urdf_data_files():
    """data_files não suporta árvores aninhadas de forma nativa (ament_python):
    gera uma entrada (dest_dir, [files]) por subdiretório de urdf/."""
    entries = []
    for root, _dirs, files in os.walk('urdf'):
        xacro_files = [os.path.join(root, f) for f in files if f.endswith('.xacro')]
        if xacro_files:
            entries.append((os.path.join('share', package_name, root), xacro_files))
    return entries


setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml') + glob('config/*.rviz')),
        (os.path.join('share', package_name, 'worlds'), glob('worlds/*.sdf')),
        (os.path.join('share', package_name, 'maps'), glob('maps/*.yaml') + glob('maps/*.pgm')),
        *_urdf_data_files(),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Eduardo',
    maintainer_email='eduardo@example.com',
    description='Orquestrador de frota: record/save/play rotas e Nav2 por robot_id.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'fleet_orchestrator = fleet_orchestrator.main:main',
            'ground_truth_filter = fleet_orchestrator.ground_truth_filter:main',
            'ble_rssi_publisher = fleet_orchestrator.ble_rssi_publisher:main',
            'ble_rssi_sim_bridge = fleet_orchestrator.ble_rssi_sim_bridge:main',
        ],
    },
)
