# syntax=docker/dockerfile:1
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    ROS_DISTRO=jazzy \
    FLEET_ROOT=/workspace

SHELL ["/bin/bash", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    locales \
    lsb-release \
    software-properties-common \
  && locale-gen en_US.UTF-8 \
  && add-apt-repository universe \
  && curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    -o /usr/share/keyrings/ros-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo "$UBUNTU_CODENAME") main" \
    > /etc/apt/sources.list.d/ros2.list \
  && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    nodejs \
    python3-colcon-common-extensions \
    python3-fastapi \
    python3-numpy \
    python3-pip \
    python3-uvicorn \
    python3-websockets \
    python3-yaml \
    ros-dev-tools \
    ros-${ROS_DISTRO}-desktop \
    ros-${ROS_DISTRO}-nav2-minimal-tb4-sim \
    ros-${ROS_DISTRO}-rmw-cyclonedds-cpp \
    ros-${ROS_DISTRO}-rosbag2-storage-mcap \
    ros-${ROS_DISTRO}-tf2-py \
    ros-${ROS_DISTRO}-tf2-ros \
    ros-${ROS_DISTRO}-turtlebot4-navigation \
  && rm -rf /var/lib/apt/lists/*

WORKDIR ${FLEET_ROOT}

# Análise do experimento BLE do CBSoft (fleet_ws/scripts/cbsoft/analise/).
# Camada separada pra não invalidar o cache da instalação do ROS acima.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pandas \
    python3-seaborn \
  && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.lock.txt ${FLEET_ROOT}/backend/requirements.lock.txt
# Versões travadas: com o requirements.txt solto (>=) a imagem pegou anthropic
# 1.15.0, que quebra os Agentes IA ("Connection error", TypeError interno).
RUN pip install --no-cache-dir --break-system-packages --ignore-installed -r backend/requirements.lock.txt
# O python3-brotli 1.1.0 do Ubuntu (vem com o ROS) não aceita output_buffer_limit,
# que o httpx2 passa ao descompressor: toda chamada à API da Anthropic falhava
# como "Connection error". Fora do Docker o venv não tem brotli e não sofre isso.
RUN pip install --no-cache-dir --break-system-packages --ignore-installed brotli==1.2.0

COPY frontend/package*.json ${FLEET_ROOT}/frontend/
RUN npm --prefix frontend ci

COPY . ${FLEET_ROOT}

RUN chmod +x docker/*.sh \
  && bash build.sh \
  && npm --prefix frontend run build

ENTRYPOINT ["/workspace/docker/entrypoint.sh"]
CMD ["bash"]
