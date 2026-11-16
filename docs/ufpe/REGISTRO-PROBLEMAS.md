# Registro de problemas: testes no CIn com Bia e Fernanda

Aqui entra **todo problema** que aparecer nos testes. Ele vai para a dissertação.
Marque sempre de onde o problema veio:

- **FLEET UI**: falha do software (bug, travou, perdeu dado, tela confusa, comando do roteiro errado).
- **PROJETO**: falha no projeto ou ambiente do teste BLE (robô, rede, celulares, script do Windows, configuração do TurtleBot4).

Regra: anote na hora, mesmo que pareça pequeno. Depois a gente classifica.

---

## Antes de cada sessão

- [ ] `git pull` e anotar o commit: `git log -1 --oneline`
- [ ] Usar os comandos **Humble** (`make robot-build-humble`, `make robot-check-humble ROBOT_NAMESPACE=tb1`, `make robot-up-humble ROBOT_NAMESPACE=tb1 ROBOT_IP=...`). O `Roteiro_teste_CIn.pdf` da 1ª semana ainda mostra `make robot-check` e `make robot-up`, que não funcionam com o robô (ver P01).
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
| P01 | 10/11/2026 | FLEET UI | O container Jazzy do PC não descobria o robô Humble via DDS. `ros2 topic list` mostrava só `/parameter_events` e `/rosout`, embora o multicast funcionasse. | Teste com o robô real não andou | Contornado: imagem `fleet-ui:humble` e alvos `*-humble` (commit 486bfdd). Detalhes em `robo_real.md`, seção "Caderno de Campo" |
| P02 | 10/11/2026 | PROJETO | O TurtleBot4 do CIn publica com namespace `/tb1/` (`/tb1/scan`, `/tb1/odom`), e o Fleet UI esperava tópicos sem prefixo. | Checagem pré-voo e Nav2 sem dados | Corrigido: `ROBOT_NAMESPACE=tb1` (commit a2d5643) |
| P03 | semana de 09/11/2026 | FLEET UI | O roteiro em PDF entregue às testadoras ficou desatualizado depois de P01/P02: os comandos e o passo do Nav2 Humble mudaram. | Risco de seguir o caminho antigo | Aberto: atualizar o PDF |
| P04 | semana de 09/11/2026 | FLEET UI | As conversas com os agentes sumiram quando o PC/aplicação fechou. Causas: `agent_runs` não era volume no Docker (`docker compose down` apagava) e a conversa só era gravada ao terminar. | Perda de dados do teste | Corrigido na branch `fix/salvar-conversas-agente` |
| P05 | semana de 09/11/2026 | FLEET UI | A tela não mostra conversas antigas. O backend tem `/api/agent/history`, mas nenhuma tela usa. Fechou a aba, a conversa some da tela. | Usuária acha que perdeu tudo | Aberto |
| P06 | | | *(completar com os outros problemas da 1ª semana)* | | |

---

## Sessões de teste

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
