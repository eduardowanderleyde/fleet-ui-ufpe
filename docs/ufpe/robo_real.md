# Conectando o Fleet-UI ao TurtleBot4 Real (CIn-UFPE)

Este documento descreve como conectar o fleet-ui a um TurtleBot4 real no laboratório do CIn-UFPE.

## ⚠️ IMPORTANTE: Use a Imagem HUMBLE para o Robô Real

**O robô usa ROS 2 Humble e NÃO é compatível com Jazzy via DDS.**

Diagnóstico de campo (10/11/2026): o container Jazzy no PC não consegue descobrir o robô Humble, mesmo com multicast funcionando. A incompatibilidade é no nível do DDS entre versões diferentes do ROS 2.

**Solução**: usar a imagem `fleet-ui:humble` para conectar ao robô real.

## Configuração do Robô

O TurtleBot4 do CIn tem a seguinte configuração:
- **ROS 2 Humble** no robô (Raspberry Pi 4)
- **CycloneDDS** como middleware
- **Domínio ROS 0** (padrão)
- **Namespace `/tb1`**: todos os tópicos são publicados com prefixo `/tb1/` (ex.: `/tb1/scan`, `/tb1/odom`, `/tb1/tf`)
- **IP wlan0**: 192.168.50.11 (rede Wi-Fi do lab)
- **IP usb0**: 192.168.186.3 (conexão USB com a base Create3, inalcançável do PC)

## Uso Rápido (Comandos para Rodar Agora)

### 1. Atualizar o código (se necessário)

```bash
cd ~/fleet-ui-ufpe   # ou onde estiver o repositório
git fetch origin
git checkout cursor/turtlebot4-real-namespace-5a9d
git pull origin cursor/turtlebot4-real-namespace-5a9d
```

### 2. Build da imagem Humble (primeira vez, ~15-20 min)

```bash
make robot-build-humble
```

### 3. Checagem pré-voo (sem mover o robô)

```bash
make robot-check-humble ROBOT_NAMESPACE=tb1
```

Este comando verifica:
- Se o middleware é CycloneDDS
- Se os tópicos do robô estão sendo publicados (`/tb1/scan`, `/tb1/odom`, `/tb1/tf`, `/tb1/tf_static`)
- Se a taxa de publicação está adequada
- Se o relógio está sincronizado entre PC e robô
- Se o TF odom→base_link está disponível

### 4. Subir o Fleet-UI contra o robô

```bash
make robot-up-humble ROBOT_NAMESPACE=tb1 ROBOT_IP=192.168.50.11
```

O `ROBOT_IP` preenche o campo de IP na tela. Depois de subir:
1. Abra http://localhost:5173
2. No painel "Robô real", clique em "Conectar"
3. O fleet-ui roda a checagem pré-voo automaticamente
4. Se passar, sobe mapa + AMCL + Nav2 no PC

## Comandos Resumidos

| Ação | Comando |
|------|---------|
| Build Humble (1x) | `make robot-build-humble` |
| Checagem | `make robot-check-humble ROBOT_NAMESPACE=tb1` |
| Subir UI | `make robot-up-humble ROBOT_NAMESPACE=tb1 ROBOT_IP=192.168.50.11` |

## Por que Humble?

A imagem Jazzy (padrão) é usada para **simulação**. Para o **robô real**, use Humble porque:

1. O TurtleBot4 roda ROS 2 Humble
2. O DDS do Jazzy não consegue descobrir nós Humble (incompatibilidade confirmada em campo)
3. As mensagens (LaserScan, Odometry, TF) são compatíveis entre versões
4. Só a descoberta DDS falha entre versões diferentes

## Como Funciona

### Namespace e Remapeamentos

O robô publica tópicos com namespace `/tb1/`, mas o AMCL/Nav2 esperam tópicos globais (`/scan`, `/tf`, etc.). O `turtlebot4_real.launch.py` cria **relays** que republicam os tópicos:

| Robô publica       | Fleet-UI escuta | Direção        |
|--------------------|-----------------|----------------|
| `/tb1/scan`        | `/scan`         | robô → PC      |
| `/tb1/odom`        | `/odom`         | robô → PC      |
| `/tb1/tf`          | `/tf`           | robô → PC      |
| `/tb1/tf_static`   | `/tf_static`    | robô → PC      |
| `/tb1/imu`         | `/imu`          | robô → PC      |
| `/cmd_vel`         | `/tb1/cmd_vel`  | PC → robô      |

### Frames TF

No TurtleBot4 Humble com namespace, os **frames TF NÃO têm prefixo** por padrão. Ou seja:
- O frame é `base_link`, não `tb1/base_link`
- O frame é `odom`, não `tb1/odom`

Isso é o comportamento padrão do `robot_state_publisher`. Se o robô estiver configurado diferente (com `frame_prefix`), os frames teriam prefixo e seria necessário ajustar.

## Compatibilidade Humble ↔ Jazzy

⚠️ **CONFIRMADO EM CAMPO (10/11/2026)**: ROS 2 Humble (robô) e Jazzy (PC) **NÃO conseguem se descobrir via DDS**.

O diagnóstico mostrou que:
- Multicast funciona normalmente entre PC e robô
- O container Jazzy no PC só vê `/parameter_events` e `/rosout`
- O mesmo container descobre normalmente robôs ROS de outros grupos na rede do lab
- **Conclusão**: incompatibilidade de descoberta DDS entre versões

**Solução implementada**: imagem `fleet-ui:humble` para o robô real.

A imagem Jazzy continua sendo usada para simulação (Gazebo, Nav2 simulado).

## Troubleshooting

### "Nenhum nó do robô descoberto"

**Causa mais provável**: Você está usando a imagem **Jazzy** para conectar ao robô **Humble**.

**Solução**:
```bash
make robot-build-humble   # se ainda não fez
make robot-check-humble ROBOT_NAMESPACE=tb1
```

Outras causas possíveis:

1. **Namespace errado**: O robô publica em `/tb1/*` mas `ROBOT_NAMESPACE` não está definido
   - Solução: `make robot-check-humble ROBOT_NAMESPACE=tb1`

2. **Domínio ROS diferente**: O robô pode estar em outro domínio
   - Verifique no robô: `echo $ROS_DOMAIN_ID`
   - Use: `make robot-check-humble ROBOT_NAMESPACE=tb1 ROBOT_DOMAIN=<n>`

3. **Rede**: PC e robô em redes diferentes
   - Verifique se consegue pingar o robô: `ping 192.168.50.11`

4. **Multicast bloqueado** (raro nesta rede - confirmado que funciona)
   - Só se for um ambiente de rede diferente

### Cyclone DDS Unicast (opcional)

Se multicast realmente não funcionar na rede, configure peers unicast:

**No PC** (já incluído no Makefile quando ROBOT_IP é definido):
O Makefile pode gerar um XML de Cyclone automaticamente. Veja os comentários no Makefile.

**No robô** (manual):
```bash
# Backup
sudo cp /etc/turtlebot4/cyclonedds_rpi.xml /etc/turtlebot4/cyclonedds_rpi.xml.bak

# Edite e adicione um Peer com o IP do PC
sudo nano /etc/turtlebot4/cyclonedds_rpi.xml
```

Dentro de `<Discovery>`, adicione:
```xml
<Peers>
    <Peer address="192.168.50.103" />  <!-- IP do PC -->
</Peers>
```

Reinicie o serviço ROS:
```bash
sudo systemctl restart turtlebot4.service
```

### TF odom→base_link indisponível

O robô pode demorar alguns segundos para publicar todos os TFs após ligar. Se o erro persistir:

1. Verifique se o `robot_state_publisher` está rodando no robô
2. Verifique se `/tb1/tf_static` está sendo publicado: `ros2 topic echo /tb1/tf_static`

### Relógio dessincronizado

Se o erro de relógio for maior que 0.5s:

```bash
# No robô (via SSH):
ssh ubuntu@192.168.50.11 "sudo date -s '@$(date +%s.%N)'"
```

Ou use NTP se disponível na rede.

## Gravação e Análise

### Gravando dados do robô

Com o fleet-ui conectado:
1. Configure a rota no painel
2. Clique em "Gravar"
3. Os dados são salvos em `fleet_ws/collections/default/`

Tópicos gravados no modo robô real:
- `/scan` (LiDAR)
- `/odom` (odometria das rodas)
- `/amcl_pose` (posição estimada pelo AMCL)

### Análise dos bags

```bash
# Dentro do container
source /opt/ros/jazzy/setup.bash
source install/setup.bash
python3 scripts/analyze_runs.py collections/default/<bag1> collections/default/<bag2>
```

O `analyze_runs.py` reconhece automaticamente tópicos com namespace (procura por `/amcl_pose` ou `*/amcl_pose`).

## Variáveis de Ambiente

| Variável          | Descrição                                      | Exemplo         |
|-------------------|------------------------------------------------|-----------------|
| `ROBOT_NAMESPACE` | Namespace do robô (sem barras)                 | `tb1`           |
| `ROBOT_IP`        | IP do robô (para preencher campo na tela)      | `192.168.50.11` |
| `ROBOT_DOMAIN`    | Domínio ROS (default: 0)                       | `0`             |
| `ROBOT_RMW`       | Middleware ROS (default: rmw_cyclonedds_cpp)   | `rmw_cyclonedds_cpp` |
| `ROBOT_MAP`       | Mapa a usar (default: hall_cin_v4)             | `hall_cin_v4`   |
| `ROS_DISTRO`      | Distro ROS (humble para robô, jazzy para sim)  | `humble`        |

## Caderno de Campo

### 10/11/2026 - Diagnóstico de Compatibilidade

**Fato**: O container Jazzy não consegue descobrir o robô Humble via DDS.

**Teste realizado**:
- `ros2 topic list` no container Jazzy mostra apenas `/parameter_events` e `/rosout`
- O mesmo container descobre robôs de outros grupos na rede do lab
- Multicast entre PC e robô funciona (testado com `ros2 multicast send/receive`)

**Conclusão**: Incompatibilidade de descoberta DDS entre Humble e Jazzy.

**Solução**: Usar imagem `fleet-ui:humble` para o robô real.
