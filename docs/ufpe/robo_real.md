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
git checkout main
git pull origin main   # o suporte a Humble e tb1 já está na main
```

### 2. Build da imagem Humble (primeira vez, ~15-20 min)

```bash
make robot-build-humble
```

### 3. Checagem pré-voo (sem mover o robô)

```bash
make robot-check-humble ROBOT_NAMESPACE=tb1 ROBOT_IP=192.168.50.11
```

O `ROBOT_IP` é necessário: com ele o PC procura o robô por unicast no DDS (ver
"Descoberta do DDS por unicast" abaixo). O robô também precisa conhecer o IP do
PC, uma configuração feita uma vez só, com backup.

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

O `ROBOT_IP` preenche o campo de IP na tela e liga a descoberta por unicast. Depois de subir:
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

4. **Descoberta por multicast não chega ao PC** (é o caso no CIn desde 19/11/2026)
   - Use `ROBOT_IP` e configure o robô: ver "Descoberta do DDS por unicast" abaixo

### Descoberta do DDS por unicast (necessária no CIn)

Em 19/11/2026 vimos que, na rede do TurtleBot4, a descoberta do DDS por
multicast não chega do robô ao PC. O ping e o `ros2 multicast` funcionam, mas
`ros2 topic list` no PC só mostra `/parameter_events` e `/rosout`. Com unicast
configurado nos dois lados, o PC recebeu as mensagens do robô. Ver o Caderno de
Campo de 19/11/2026.

**No PC: automático.** Com `ROBOT_IP` e CycloneDDS, o `docker/entrypoint.sh` gera
um XML com o IP do PC na rede do robô como interface e o robô como peer
(`fleet_ws/scripts/cyclone_unicast.py`). O painel "Robô real" refaz o XML se o IP
digitado na tela for outro. A pasta `docker/` e `fleet_ws/scripts/` vêm do
repositório no modo robô, então basta `git pull`: não precisa refazer a imagem.
Para voltar ao multicast: `ROBOT_DDS_UNICAST=false`. Para ver o XML:
`python3 fleet_ws/scripts/cyclone_unicast.py 192.168.50.11 --print`.

**No robô: manual, uma vez, com backup.** O robô também precisa do IP do PC como
peer. Isso só acrescenta o PC à descoberta: o multicast continua ligado e a
ligação com a base Create3 pela `usb0` não muda.

1. Ver o IP do PC na rede do robô (no PC): `ip -4 addr | grep 192.168.50`.
   O pc044 estava com 192.168.50.102 em 19/11/2026.
2. No robô (`ssh ubuntu@192.168.50.11`), guardar o arquivo original e olhar o conteúdo:
   ```bash
   sudo cp /etc/turtlebot4/cyclonedds_rpi.xml /etc/turtlebot4/cyclonedds_rpi.xml.bak-20261119
   cat /etc/turtlebot4/cyclonedds_rpi.xml
   ```
3. Editar com `sudo nano /etc/turtlebot4/cyclonedds_rpi.xml` e, dentro de
   `<Domain>`, acrescentar o bloco abaixo sem apagar nada. Se já houver um
   `<Discovery>`, coloque só o que falta dentro dele. Cada PC que for usar o
   Fleet UI ganha uma linha `<Peer>`:
   ```xml
   <Discovery>
     <Peers>
       <Peer address="192.168.50.102"/>
     </Peers>
     <ParticipantIndex>auto</ParticipantIndex>
     <MaxAutoParticipantIndex>100</MaxAutoParticipantIndex>
   </Discovery>
   ```
4. Conferir o XML (se o `xmllint` não existir, pule) e reiniciar:
   ```bash
   xmllint --noout /etc/turtlebot4/cyclonedds_rpi.xml
   sudo systemctl restart turtlebot4
   ros2 daemon stop
   ros2 topic list --no-daemon     # os /tb1/... têm de continuar aparecendo
   ```
5. No PC: `make robot-check-humble ROBOT_NAMESPACE=tb1 ROBOT_IP=192.168.50.11`.

Para desfazer:
```bash
sudo cp /etc/turtlebot4/cyclonedds_rpi.xml.bak-20261119 /etc/turtlebot4/cyclonedds_rpi.xml
sudo systemctl restart turtlebot4
```

Se o IP do PC mudar (DHCP), acrescente o novo em `<Peers>`; pode haver mais de um.

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
| `ROBOT_IP`        | IP do robô: campo da tela e descoberta unicast | `192.168.50.11` |
| `ROBOT_DDS_UNICAST` | `false` volta à descoberta por multicast     | `true`          |
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

### 19/11/2026 - Descoberta do DDS por multicast não chega ao PC

**Fato**: com a imagem Humble, `make robot-check-humble ROBOT_NAMESPACE=tb1`
continuou sem achar nenhum nó do robô. No PC (pc044, 192.168.50.102),
`ros2 topic list` só mostrava `/parameter_events` e `/rosout`, também com o PC
forçado para a própria interface e o robô como peer. No robô, `ros2 topic list`
mostrava todos os `/tb1/...`.

**Testes** (Bia, com o agente do Fleet UI):
- ping PC → robô: OK; `ufw` do PC inativo;
- `ros2 multicast` nos dois sentidos: OK;
- robô publicando `/chatter` com a config padrão, PC escutando: nada em 15 s;
- unicast nos dois lados (robô com o PC como peer, PC com o robô como peer):
  o PC recebeu `teste unicast` várias vezes.

**Conclusão**: a descoberta padrão do DDS (multicast) não chega do robô ao PC
nessa rede, embora o `ros2 multicast` passe. Com unicast nos dois lados funciona.
Isso também põe em dúvida a conclusão de 10/11 (versões Humble × Jazzy): o
sintoma era o mesmo e talvez a causa também.

**Solução**: unicast automático no PC a partir do `ROBOT_IP` e peer com o IP do
PC no `cyclonedds_rpi.xml` do robô (seção "Descoberta do DDS por unicast").
