"""Configuração de namespace do robô para modo robô real.

Este módulo centraliza:
- Resolução de nomes de tópicos com/sem namespace (ROBOT_NAMESPACE)
- Helpers para frames TF

ROBOT_NAMESPACE é o namespace do robô TurtleBot4 (ex.: "tb1" para /tb1/scan).
O TurtleBot4 do CIn-UFPE publica com namespace /tb1.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict


@dataclass
class RobotNamespaceConfig:
    """Configuração de namespace do robô."""
    namespace: str
    
    @classmethod
    def from_env(cls) -> "RobotNamespaceConfig":
        ns = os.environ.get("ROBOT_NAMESPACE", "").strip()
        ns = ns.strip("/")
        return cls(namespace=ns)
    
    def topic(self, base_topic: str) -> str:
        """Retorna o nome completo do tópico com namespace.
        
        >>> RobotNamespaceConfig("tb1").topic("scan")
        '/tb1/scan'
        >>> RobotNamespaceConfig("").topic("scan")
        '/scan'
        """
        base = base_topic.lstrip("/")
        if self.namespace:
            return f"/{self.namespace}/{base}"
        return f"/{base}"
    
    def topics(self, base_topics: Dict[str, str]) -> Dict[str, str]:
        """Retorna dict com todos os tópicos prefixados.
        
        >>> cfg = RobotNamespaceConfig("tb1")
        >>> cfg.topics({"/scan": "LaserScan", "/odom": "Odometry"})
        {'/tb1/scan': 'LaserScan', '/tb1/odom': 'Odometry'}
        """
        return {self.topic(t.lstrip("/")): v for t, v in base_topics.items()}
    
    def frame(self, base_frame: str, prefix_frames: bool = False) -> str:
        """Retorna o nome do frame TF com ou sem namespace.
        
        TurtleBot4 Humble com namespace: os frames NÃO têm prefixo por padrão
        (base_link, odom, não tb1/base_link). Isso é configurável via
        frame_prefix no robot_state_publisher, mas o default é sem prefixo.
        
        prefix_frames=True força o prefixo (para configs não-padrão).
        """
        if prefix_frames and self.namespace:
            return f"{self.namespace}/{base_frame}"
        return base_frame
    
    @property
    def has_namespace(self) -> bool:
        return bool(self.namespace)


def get_namespace() -> str:
    """Retorna o namespace do robô (ROBOT_NAMESPACE), sem barras."""
    return os.environ.get("ROBOT_NAMESPACE", "").strip().strip("/")


def topic_with_namespace(base_topic: str, namespace: str = "") -> str:
    """Adiciona namespace ao tópico se definido.
    
    >>> topic_with_namespace("scan", "tb1")
    '/tb1/scan'
    >>> topic_with_namespace("scan", "")
    '/scan'
    >>> topic_with_namespace("/scan", "tb1")
    '/tb1/scan'
    """
    ns = namespace or get_namespace()
    base = base_topic.lstrip("/")
    if ns:
        return f"/{ns}/{base}"
    return f"/{base}"


def expected_robot_topics(namespace: str = "") -> Dict[str, str]:
    """Retorna os tópicos esperados do robô com namespace aplicado.
    
    Estes são os tópicos que o TurtleBot4 publica e que o fleet-ui precisa
    receber para funcionar (sensores, odometria, TF).
    """
    ns = namespace or get_namespace()
    base = {
        "scan": "sensor_msgs/msg/LaserScan",
        "odom": "nav_msgs/msg/Odometry",
        "tf": "tf2_msgs/msg/TFMessage",
        "tf_static": "tf2_msgs/msg/TFMessage",
        "imu": "sensor_msgs/msg/Imu",
        "cmd_vel": "geometry_msgs/msg/Twist",
    }
    return {topic_with_namespace(t, ns): typ for t, typ in base.items()}
