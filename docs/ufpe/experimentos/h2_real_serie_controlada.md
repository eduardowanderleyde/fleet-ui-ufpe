# Protocolo: Série Controlada Curta — Critério H2-real

**Pré-registro:** 9 de novembro de 2026  
**Execução planejada:** 10 de novembro de 2026  
**Responsáveis:** Bia, Fernanda (colaboradoras), Eduardo (supervisor)  
**Local:** Corredor já mapeado no CIn-UFPE (mapa `hall_cin_v4`)

---

## 1. Objetivo

Medir a **repetibilidade do record–replay** no TurtleBot4 real.

### Critérios de aceitação (definidos ANTES do teste)

| Critério | Valor |
|----------|-------|
| Número mínimo de replays | N ≥ 5 (alvo 10) |
| Fonte da trajetória | `/amcl_pose` no frame `map` |
| Dispersão da pose inicial | < 10 cm entre replays |
| H2-real atendida se | RMSE médio < 25 cm **e** CV da duração < 10% |

> **Por que `/amcl_pose` e não `/odom`?**  
> No robô real, `/odom` reinicia perto de (0, 0) a cada boot ou localização. A pose do AMCL reflete a localização corrigida no mapa fixo `hall_cin_v4`, dando uma referência comparável entre execuções.

---

## 2. Rota

- **Trecho curto:** ~1,5 a 3 m, reto ou com uma curva suave
- **Local:** corredor já mapeado (`hall_cin_v4`)
- **Marca de partida:** fita no chão com seta indicando a orientação do robô (frente do TurtleBot4 alinhada à seta)

A rota é criada pelo comando `record` do `experiment_repeatability.py` ou pela interface web (aba **Gravar**), que gera um arquivo YAML em `routes/default/<nome_da_rota>.yaml`.

---

## 3. Preparação

### 3.1 Ligar o robô e conectar

```bash
# No PC com o Fleet UI (dentro do repositório)
make robot-up
```

Isso abre a interface em `http://localhost:5173` no modo **robô real** (domínio ROS 0, CycloneDDS).

No painel **Robô real** à esquerda:
1. Inserir o **IP do robô** (ex.: `192.168.50.11`, confira na telinha do robô ou no roteador)
2. Clicar **▶ Conectar**
3. Aguardar a checagem pré-voo e a inicialização do Nav2 (~25 s)
4. Status esperado: **✓ Robô conectado**

### 3.2 Verificar mapa e pose inicial

O `make robot-up` carrega o mapa `hall_cin_v4` com AMCL no ponto START. Confira no cabeçalho da interface:
- **Nav2:** ON
- **x, y, yaw:** próximos da pose onde o robô está fisicamente

Se a pose estiver errada (robô num lugar diferente do marcador no mapa), use o campo **Pose inicial** na interface para informar ao AMCL a posição real do robô, ou reposicione o robô no START.

### 3.3 Esperar `/amcl_pose` estabilizar

Depois de conectar:
1. Aguarde alguns segundos até a posição no cabeçalho (x, y) parar de mudar
2. Se necessário, use `ros2 topic echo /amcl_pose --once` para confirmar que o AMCL está publicando

---

## 4. Baseline (gravação da rota)

### 4.1 Criar a rota pela interface web

1. Na interface, selecionar **⏺ Gravar**
2. Em **Nome da rota**, digitar um nome descritivo (ex.: `h2_real_curta_baseline`)
3. Em **Waypoints**, clicar no mapa para adicionar os pontos do percurso
   - Ou digitar as coordenadas manualmente nos campos x, y, yaw
4. Marcar **Gravar bag** para coletar os dados sensoriais
5. Os tópicos gravados no modo robô real são: `scan`, `odom`, `amcl_pose`
6. Clicar **▶ Executar record**

### 4.2 Ou criar pelo terminal (dentro do container)

```bash
docker compose exec backend bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash

python3 scripts/experiment_repeatability.py record \
  --single-robot \
  --route h2_real_curta_baseline \
  --points "x1,y1,yaw1;x2,y2,yaw2" \
  --topics scan odom amcl_pose \
  --initial-pose x0,y0,yaw0 \
  --export runs/baseline.json
```

Substitua `x1,y1,yaw1` etc. pelas coordenadas reais dos waypoints e da pose inicial.

### 4.3 Anotar

- Nome da rota gravada: _____________________
- Hora do início: _____________________
- Hora do fim: _____________________
- Observações: _____________________

---

## 5. Replays (N ≥ 5, alvo 10)

Para cada replay:

### 5.1 Recolocar o robô na marca de partida

1. Desligar a navegação se ainda estiver ativa (botão **■ Parar** na interface, se necessário)
2. Reposicionar o robô **fisicamente** na marca de fita, alinhando a frente à seta
3. Conferir que `/amcl_pose` está a < 10 cm da pose inicial da baseline

### 5.2 Verificar dispersão da pose inicial

Na interface, os campos **x, y** no cabeçalho mostram a pose atual do AMCL.

- Anotar **x**, **y**, **yaw** na tabela do caderno de campo
- Conferir que a distância euclidiana até a pose inicial da baseline é < 10 cm:
  
  ```
  dist = sqrt((x - x_baseline)² + (y - y_baseline)²)
  ```

Se dist ≥ 10 cm, reposicionar o robô e aguardar o AMCL estabilizar.

### 5.3 Disparar o replay

1. Na interface, selecionar **▶ Reproduzir**
2. Em **Rota para replay**, escolher a rota gravada (ex.: `h2_real_curta_baseline`)
3. Marcar **Gravar bag**
4. Em **Pose inicial**, inserir a pose exata da baseline (garante que o AMCL seja reinicializado no mesmo ponto antes de navegar)
5. Clicar **▶ Executar replay**

Ou pelo terminal:

```bash
python3 scripts/experiment_repeatability.py replay \
  --single-robot \
  --route h2_real_curta_baseline \
  --topics scan odom amcl_pose \
  --initial-pose x0,y0,yaw0 \
  --export runs/replay_01.json
```

### 5.4 Não intervir

- Não atravessar a frente do robô
- Não bloquear o laser
- Deixar o replay completar sozinho
- Anotar se houve **falha**, **parada** ou **timeout**

---

## 6. Ambiente

| Requisito | Verificação |
|-----------|-------------|
| Ninguém cruza a frente do robô durante a execução | ☐ Confirmado |
| Sem obstáculos novos no corredor | ☐ Confirmado |
| Mesma iluminação (ou variação mínima) | ☐ Confirmado |
| Portas em posição consistente | ☐ Confirmado |

Se houver **interferência** (pessoa cruzou, objeto caiu, robô travou):
1. Marcar a execução como **inválida** no caderno de campo
2. Registrar o **motivo**
3. Refazer o replay (conta como tentativa extra, não substitui)

---

## 7. Dados

### 7.1 Onde ficam os bags

Todos os rosbags são salvos automaticamente em:

```
fleet_ws/collections/default/<timestamp>_<hash>/
```

Exemplo: `fleet_ws/collections/default/2026-11-10_14-32-57_a1b2c3d4/`

Cada execução gera também um JSON de resumo (quando `--export` é usado), ex.: `runs/baseline.json`, `runs/replay_01.json`.

### 7.2 O que guardar

- **Todos os bags** (baseline + todos os replays, incluindo falhas)
- **JSONs de execução** (`--export`)
- **`summary.json`** gerado pela análise
- **Cópia do arquivo YAML da rota:** `routes/default/<nome_da_rota>.yaml`
- **Este protocolo**

### 7.3 Estrutura sugerida de arquivamento

```
results/h2_real_serie_controlada_2026-11-10/
├── protocolo.md                          # cópia deste documento
├── rota.yaml                             # routes/default/h2_real_curta_baseline.yaml
├── bags/
│   ├── baseline_2026-11-10_14-32-57/     # bag da baseline
│   ├── replay_01_2026-11-10_14-45-12/    # bag do replay 1
│   ├── replay_02_2026-11-10_14-58-33/    # ...
│   └── ...
├── runs/
│   ├── baseline.json
│   ├── replay_01.json
│   └── ...
├── analysis/
│   ├── summary.json
│   ├── trajectory_overlay.png
│   └── trajectories_csv/
└── caderno_de_campo.md
```

---

## 8. Caderno de Campo — Tabela-Modelo

Copiar e preencher durante o experimento:

| # | Tipo | Hora | Pose inicial (x, y, yaw) | Dist. ao START (cm) | Concluiu? | Bateria (%) | Observações |
|---|------|------|--------------------------|---------------------|-----------|-------------|-------------|
| 0 | baseline | | | — | | | |
| 1 | replay | | | | | | |
| 2 | replay | | | | | | |
| 3 | replay | | | | | | |
| 4 | replay | | | | | | |
| 5 | replay | | | | | | |
| 6 | replay | | | | | | |
| 7 | replay | | | | | | |
| 8 | replay | | | | | | |
| 9 | replay | | | | | | |
| 10 | replay | | | | | | |

**Legenda:**
- **Dist. ao START:** distância euclidiana entre a pose inicial anotada e a pose da baseline
- **Concluiu?:** Sim / Não / Parcial (indicar waypoint onde parou)
- **Bateria:** nível no início da execução
- **Observações:** qualquer interferência, erro, comportamento inesperado

---

## 9. Análise

### 9.1 Script de análise

O script `fleet_ws/scripts/analyze_runs.py` calcula métricas de repetibilidade entre execuções.

**Uso básico:**

```bash
# Dentro do container ou com o workspace ROS 2 sourceado
source /opt/ros/jazzy/setup.bash
source install/setup.bash

python3 scripts/analyze_runs.py \
  collections/default/<bag_baseline> \
  collections/default/<bag_replay_01> \
  collections/default/<bag_replay_02> \
  collections/default/<bag_replay_03> \
  collections/default/<bag_replay_04> \
  collections/default/<bag_replay_05> \
  --trajectory-topic amcl_pose \
  --output-dir analysis \
  --labels baseline replay_01 replay_02 replay_03 replay_04 replay_05
```

### 9.2 Opção `--trajectory-topic`

| Valor | Comportamento |
|-------|---------------|
| `auto` (padrão) | Prefere `/amcl_pose` se existir com mensagens, senão `/pose` (SLAM Toolbox), senão `/odom` |
| `amcl_pose` | **Obriga** uso de `/amcl_pose`; erro se não houver mensagens |
| `odom` | Usa `/odom` (deriva sem correção — **não recomendado** para comparação no robô real) |

**Para este protocolo, usar `--trajectory-topic amcl_pose`** para garantir que a análise usa a pose corrigida no frame do mapa.

### 9.3 Saídas do analyze_runs.py

| Arquivo | Conteúdo |
|---------|----------|
| `summary.json` | Métricas: duração, comprimento, RMSE entre pares, `vs_reference` |
| `trajectory_overlay.png` | Sobreposição visual das trajetórias |
| `trajectories_csv/*.csv` | Série temporal `t_sec, x_m, y_m` por execução |

### 9.4 Métricas no `summary.json`

O primeiro bag passado é a **referência**. As métricas `vs_reference` incluem:

- `rmse_vs_ref_m`: RMSE da trajetória vs. a referência (em metros)
- `mean_pointwise_distance_vs_ref_m`: distância média ponto a ponto
- `final_endpoint_error_m`: erro no ponto final
- `duration_ratio_vs_ref`: razão da duração (ex.: 1.05 = 5% mais lento)

### 9.5 Calcular CV da duração

O coeficiente de variação (CV) da duração mede a consistência temporal entre replays:

```
CV = (desvio_padrão / média) × 100%
```

O `summary.json` inclui `duration_sec` para cada run em `vs_reference`. Calcular manualmente ou com um script simples:

```python
import json
import statistics

with open('analysis/summary.json') as f:
    data = json.load(f)

durations = [r['duration_sec'] for r in data['vs_reference'] if r['label'] != 'baseline']
mean_dur = statistics.mean(durations)
std_dur = statistics.stdev(durations) if len(durations) > 1 else 0
cv_percent = (std_dur / mean_dur) * 100 if mean_dur > 0 else 0

print(f"Duração média: {mean_dur:.2f} s")
print(f"Desvio padrão: {std_dur:.2f} s")
print(f"CV: {cv_percent:.2f}%")
```

### 9.6 Calcular RMSE médio

```python
rmse_values = [r['rmse_vs_ref_m'] for r in data['vs_reference'] if r['label'] != 'baseline']
mean_rmse = statistics.mean(rmse_values)

print(f"RMSE médio vs. baseline: {mean_rmse:.4f} m ({mean_rmse*100:.2f} cm)")
```

### 9.7 Verificação do critério H2-real

```python
h2_rmse_ok = mean_rmse < 0.25  # < 25 cm
h2_cv_ok = cv_percent < 10     # < 10%
h2_real_atendido = h2_rmse_ok and h2_cv_ok

print(f"RMSE < 25 cm: {'SIM' if h2_rmse_ok else 'NÃO'} ({mean_rmse*100:.2f} cm)")
print(f"CV < 10%: {'SIM' if h2_cv_ok else 'NÃO'} ({cv_percent:.2f}%)")
print(f"H2-real atendido: {'SIM' if h2_real_atendido else 'NÃO'}")
```

---

## 10. Limitações conhecidas

1. **Frequência do `/amcl_pose`:** O AMCL publica com QoS `TRANSIENT_LOCAL` e só republica quando o robô se move. A análise usa reamostragem temporal para alinhar trajetórias de tamanhos diferentes, mas poucas amostras podem afetar a precisão do RMSE.

2. **Inicialização do AMCL:** Se o robô for ligado numa posição diferente de onde o AMCL espera, a localização pode levar alguns segundos (ou exigir movimento) para convergir. Sempre aguarde a pose estabilizar antes de iniciar o replay.

3. **Comparação usa subamostragem:** O `analyze_runs.py` usa interpolação temporal normalizada (padrão `--resample-mode time`) ou subamostragem por índice (`--resample-mode index`). Não é DTW; trajetórias muito diferentes em formato podem ter RMSE enganoso.

4. **Sem ground truth real:** No robô real, não há sistema externo de captura de movimento. O "ground truth" é o próprio AMCL, que tem erro de localização. Os resultados refletem repetibilidade aparente, não erro absoluto.

---

## 11. Fora do escopo deste protocolo

A **rota BLE em L** (estudo de caso de conectividade Bluetooth, ~95 m) usada no experimento CBSoft é uma **validação funcional da interface** e do pipeline de coleta de RSSI, **não** um teste de H2-real.

Este protocolo trata exclusivamente da **série controlada curta** para medir repetibilidade de navegação.

---

## 12. Resultados negativos

Resultados negativos (H2-real não atendido, CV > 10%, RMSE > 25 cm) **são reportados como medidos**, com os valores reais e uma análise das possíveis causas (ex.: localização instável, obstáculo inesperado, bateria baixa afetando velocidade).

Não descartar dados "ruins" — eles fazem parte do experimento.

---

## Anexo A: Referência rápida de comandos

```bash
# Subir interface no modo robô real
make robot-up

# Checagem pré-voo (só leitura, não publica nada)
make robot-check

# Entrar no container
docker compose exec backend bash

# Dentro do container: sourcear o workspace
source /opt/ros/jazzy/setup.bash
source install/setup.bash

# Listar rotas disponíveis
ls routes/default/*.yaml

# Listar bags gravados
ls -lt collections/default/

# Executar análise
python3 scripts/analyze_runs.py \
  collections/default/<bag1> collections/default/<bag2> ... \
  --trajectory-topic amcl_pose \
  --output-dir analysis \
  --labels baseline replay_01 replay_02 ...

# Verificar tópicos em um bag
ros2 bag info collections/default/<bag>

# Verificar se /amcl_pose tem mensagens
ros2 bag info collections/default/<bag> | grep amcl_pose
```

---

## Anexo B: Checklist pré-experimento

- [ ] Robô carregado (bateria ≥ 50%)
- [ ] Mapa `hall_cin_v4` carregado corretamente
- [ ] Marca de partida colocada no chão com fita e seta
- [ ] Corredor livre de obstáculos extras
- [ ] Interface funcionando (`http://localhost:5173`)
- [ ] Robô conectado (status "✓ Robô conectado")
- [ ] Nav2 ON
- [ ] `/amcl_pose` publicando (conferir cabeçalho x, y)
- [ ] Este protocolo impresso ou acessível
- [ ] Tabela do caderno de campo pronta

---

*Documento gerado em 10 de novembro de 2026 para a dissertação de mestrado (CIn-UFPE).*
