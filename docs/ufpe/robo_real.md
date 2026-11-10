# Conectando o Fleet-UI ao TurtleBot4 Real (CIn-UFPE)

Este documento descreve como conectar o fleet-ui a um TurtleBot4 real no laboratório do CIn-UFPE.

## Configuração do Robô

O TurtleBot4 do CIn tem a seguinte configuração:
- **ROS 2 Humble** no robô (Raspberry Pi 4)
- **CycloneDDS** como middleware
- **Domínio ROS 0** (padrão)
- **Namespace `/tb1`**: todos os tópicos são publicados com prefixo `/tb1/` (ex.: `/tb1/scan`, `/tb1/odom`, `/tb1/tf`)
- **IP wlan0**: 192.168.50.11 (rede Wi-Fi do lab)
- **IP usb0**: 192.168.186.3 (conexão USB com a base Create3, inalcançável do PC)

## Uso Rápido

### Checagem pré-voo (sem mover o robô)

```bash
make robot-check ROBOT_NAMESPACE=tb1
```

Este comando verifica:
- Se o middleware é CycloneDDS
- Se os tópicos do robô estão sendo publicados (`/tb1/scan`, `/tb1/odom`, `/tb1/tf`, `/tb1/tf_static`)
- Se a taxa de publicação está adequada
- Se o relógio está sincronizado entre PC e robô
- Se o TF odom→base_link está disponível

### Subir o Fleet-UI contra o robô

```bash
make robot-up ROBOT_NAMESPACE=tb1 ROBOT_IP=192.168.50.11
```

O `ROBOT_IP` preenche o campo de IP na tela. Depois de subir:
1. Abra http://localhost:5173
2. No painel "Robô real", clique em "Conectar"
3. O fleet-ui roda a checagem pré-voo automaticamente
4. Se passar, sobe mapa + AMCL + Nav2 no PC

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

⚠️ **AVISO**: ROS 2 Humble (robô) e Jazzy (PC/fleet-ui) **não são oficialmente compatíveis**.

Na prática, funciona para a maioria dos casos porque:
- As mensagens de sensores (LaserScan, Odometry, TFMessage, Twist) não mudaram entre versões
- O DDS (CycloneDDS) é o mesmo

Mas pode haver problemas de descoberta DDS ou timing em alguns cenários.

### Fallback: Imagem Humble no PC

Se a checagem pré-voo falhar consistentemente com erros de descoberta ou tipos de mensagem, considere rodar o fleet-ui com uma imagem baseada em Humble em vez de Jazzy:

1. Altere o `Dockerfile` para usar `ros:humble` como base
2. Rebuild: `make docker-build`
3. Teste novamente

Isso não está implementado nesta branch, mas é um caminho de fallback documentado.

## Troubleshooting

### "Nenhum nó do robô descoberto"

Possíveis causas (em ordem de probabilidade):

1. **Namespace errado**: O robô publica em `/tb1/*` mas `ROBOT_NAMESPACE` não está definido
   - Solução: `make robot-check ROBOT_NAMESPACE=tb1`

2. **Incompatibilidade Humble/Jazzy**: Versões diferentes do DDS podem não se descobrir
   - Verifique se ambos usam CycloneDDS: `echo $RMW_IMPLEMENTATION`
   - Considere o fallback para imagem Humble

3. **Domínio ROS diferente**: O robô pode estar em outro domínio
   - Verifique no robô: `echo $ROS_DOMAIN_ID`
   - Use: `make robot-check ROBOT_NAMESPACE=tb1 ROBOT_DOMAIN=<n>`

4. **Rede**: PC e robô em redes diferentes
   - Verifique se consegue pingar o robô: `ping 192.168.50.11`

5. **Multicast bloqueado** (raro nesta rede): Se multicast não funcionar
   - Use Cyclone DDS com peers unicast (ver seção abaixo)

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
