# Registro de problemas: testes no CIn com Bia e Fernanda

Aqui entra **todo problema** que aparecer nos testes. Ele vai para a dissertação.
Marque sempre de onde o problema veio:

- **FLEET UI**: falha do software (bug, travou, perdeu dado, tela confusa, comando do roteiro errado).
- **PROJETO**: falha no projeto ou ambiente do teste BLE (robô, rede, celulares, script do Windows, configuração do TurtleBot4).

Regra: anote na hora, mesmo que pareça pequeno. Depois a gente classifica.

---

## Antes de cada sessão

- [ ] `git pull` e anotar o commit: `git log -1 --oneline`
- [ ] Usar os comandos **Humble**, sempre com `ROBOT_IP` (`make robot-build-humble`, `make robot-check-humble ROBOT_NAMESPACE=tb1 ROBOT_IP=...`, `make robot-up-humble ROBOT_NAMESPACE=tb1 ROBOT_IP=...`). O `Roteiro_teste_CIn.pdf` da 1ª semana ainda mostra `make robot-check` e `make robot-up`, que não funcionam com o robô (ver P01).
- [ ] Conferir que o IP deste PC está em `<Peers>` no `/etc/turtlebot4/cyclonedds_rpi.xml` do robô (ver P10)
- [ ] Anotar: data, quem testou, PC/sistema
- [ ] Gravar a tela (OBS ou gravador do sistema). Se tudo falhar, é o backup

## Depois de cada sessão

- [ ] Antes do `make docker-down`, conferir se `fleet_ws/agent_runs/` tem arquivos (conversas com os agentes)
- [ ] Copiar `fleet_ws/collections/` **e** `fleet_ws/agent_runs/` para pendrive ou nuvem
- [ ] Preencher a sessão abaixo

---

## Problemas conhecidos

| # | Data | Tipo | O que aconteceu | Impacto | Status |
|---|------|------|-----------------|---------|--------|
| P01 | 10/11/2026 | FLEET UI | O container Jazzy do PC não descobria o robô Humble via DDS. `ros2 topic list` mostrava só `/parameter_events` e `/rosout`, embora o multicast funcionasse. | Teste com o robô real não andou | Contornado: imagem `fleet-ui:humble` e alvos `*-humble` (commit 486bfdd). Detalhes em `robo_real.md`, seção "Caderno de Campo". Em 19/11 o mesmo sintoma voltou com Humble (P10): a causa pode ter sido a descoberta por multicast, não a versão |
| P02 | 10/11/2026 | PROJETO | O TurtleBot4 do CIn publica com namespace `/tb1/` (`/tb1/scan`, `/tb1/odom`), e o Fleet UI esperava tópicos sem prefixo. | Checagem pré-voo e Nav2 sem dados | Corrigido: `ROBOT_NAMESPACE=tb1` (commit a2d5643) |
| P03 | semana de 09/11/2026 | FLEET UI | O roteiro em PDF entregue às testadoras ficou desatualizado depois de P01/P02: os comandos e o passo do Nav2 Humble mudaram. | Risco de seguir o caminho antigo | Corrigido em 16/11/2026: roteiro novo na main (0ef640a) |
| P04 | semana de 09/11/2026 | FLEET UI | As conversas com os agentes sumiram quando o PC/aplicação fechou. Causas: `agent_runs` não era volume no Docker (`docker compose down` apagava) e a conversa só era gravada ao terminar. | Perda de dados do teste | Corrigido na main em 15/11/2026 (c5ba7ce) |
| P05 | semana de 09/11/2026 | FLEET UI | A tela não mostra conversas antigas. O backend tem `/api/agent/history`, mas nenhuma tela usa. Fechou a aba, a conversa some da tela. | Usuária acha que perdeu tudo | Aberto |
| P06 | | | *(completar com os outros problemas da 1ª semana)* | | |
| P07 | 19/11/2026 | FLEET UI | `git pull` falhou por permissão em `fleet_ws`: pastas criadas pelo Docker ficam do root. Resolvido com `chown`. | Atraso no começo da sessão | Contornado na hora; aberto: criar as pastas com o usuário do PC |
| P08 | 19/11/2026 | PROJETO | Disco cheio no PC do lab durante o `make robot-build-humble`. As duas imagens somam ~12 GB (dev 7,7 GB, humble 4,4 GB). Liberado com `docker builder prune`. | Build parou | Contornado na hora |
| P09 | 19/11/2026 | FLEET UI | `make robot-up` (alvo antigo, Jazzy) falhou com `/opt/ros/humble/setup.bash: No such file`. Com os alvos `*-humble` passou. | Confusão entre alvos antigos e novos | Aberto: o alvo antigo devia avisar e apontar o `*-humble` |
| P10 | 19/11/2026 | PROJETO + FLEET UI | Com Humble, a checagem continuou sem achar nenhum nó do robô (10 FALHAs). Ping e `ros2 multicast` OK nos dois sentidos, robô publicando todos os `/tb1/...`, `ufw` inativo. A descoberta do DDS por multicast não chega do robô ao PC nessa rede; com unicast nos dois lados (cada um com o outro como peer) o PC recebeu as mensagens. PROJETO: rede/config DDS do robô. FLEET UI: não tinha unicast automático (a doc dizia que o Makefile gerava o XML, mas não gerava). | Teste com o robô real não andou de novo | PC: corrigido na branch `fix/dds-unicast-robo` (XML gerado a partir do `ROBOT_IP`). Robô: falta pôr o IP do PC em `<Peers>`, com backup (`robo_real.md`) |
| P11 | 19/11/2026 | PROJETO | Relógio do robô atrasado; acertado via SSH. | Checagem de relógio falharia | Contornado na hora |

---

## Sessões de teste

### Sessão 2026-11-19: Bia

- Commit do Fleet UI: 0ef640a (main)
- PC / sistema: pc044, Ubuntu, Wi-Fi TurtleLab 192.168.50.102; robô 192.168.50.11 (Humble, Cyclone, domínio 0, `/tb1`)
- Corridas feitas / concluídas: 0 (o PC não descobriu o robô; ver P10)
- Diagnóstico feito com o agente do Fleet UI: P07, P08, P09, P10, P11
- Arquivos em `agent_runs` e `collections` copiados? onde: (preencher)

Copie este bloco para cada sessão.

### Sessão AAAA-MM-DD: NOMES

- Commit do Fleet UI:
- PC / sistema:
- Corridas feitas / concluídas:
- Como o robô foi posto no START (marca, direção):
- Arquivos em `agent_runs` e `collections` copiados? onde:

| Hora | Tipo (FLEET UI / PROJETO) | Passo do roteiro | O que esperava | O que aconteceu | Print/vídeo |
|------|---------------------------|------------------|----------------|-----------------|-------------|
| | | | | | |

Frases das testadoras (entre aspas):
