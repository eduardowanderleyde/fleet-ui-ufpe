import { useCallback, useEffect, useRef, useState } from 'react'
import {
  activateRobot, deactivateRobot, getSimulationOptions, getSimulationStatus,
  getStatus, goToPoint, startSimulation, stopSimulation,
} from '../api/fleetApi'

const EMPTY_STATUS = { running: false, ready: false, mode: null, world: null, robots: [], lines: [], error: null }

// Formações: 1 ponto por robô, 3 robôs fixos — o clássico "pixel voador"
// de show de drone, só que com 3 pontos em vez de milhares.
export const SHAPES = {
  L:  { label: 'L',  points: [[0, 0, 0], [0, 1.5, 0], [1.5, 1.5, 0]] },
  I:  { label: 'I',  points: [[0, 0, 0], [0, 1.5, 0], [0, 3.0, 0]] },
  V:  { label: 'V',  points: [[0, 1.5, 0], [0.75, 0, 0], [1.5, 1.5, 0]] },
  '\\': { label: '\\', points: [[0, 0, 0], [0.75, -0.75, 0], [1.5, -1.5, 0]] },
}
// 2 robôs por padrão — mesmo par validado como estável no resto do app
// (FLEET_ROBOTS). 3 robôs sobrecarrega o Nav2/DDS nesta máquina: testado ao
// vivo em 2026-09-25, tb2 e tb3 ficaram presos indefinidamente esperando
// serviços do lifecycle_manager que nunca respondem. SHAPES já tem um ponto
// a mais que isso (pensadas pra até 3), o dispatch só usa os N primeiros.
export const ROBOTS = ['tb1', 'tb2']
const sleep = (ms) => new Promise(r => setTimeout(r, ms))

// Navegação de 1 robô por vez (ver "Opção B" / "Resolvido na máquina Linux
// nativa" no orquestracion.md) — rodar N pilhas de Nav2 completas ao mesmo
// tempo faz o /clock simulado saltar pra trás sob a carga combinada. Testado
// ao vivo: o robô ATIVADO leva até ~12s pra ficar pronto (rajada de ~15-18
// nós), e depois de ativar/desativar precisa de ~15s de assentamento no
// backend (_ROBOT_NAV_SETTLE_SECONDS) antes do próximo.
//
// Timeout deliberadamente curto, não generoso: testado ao vivo que os
// casos que travam (484 avisos de jump-back, ou sob carga alta da
// máquina) não parecem se resolver esperando mais — ou converge rápido
// (6-12s) ou fica preso mesmo, sem meio-termo visto. Preferível falhar
// rápido e deixar tentar de novo do que o usuário olhando pra tela parada
// por minutos sem essa espera extra realmente ajudar.
const NAV_READY_TIMEOUT_MS = 60000
const NAV_READY_POLL_MS = 2000
const TRAVEL_DWELL_MS = 18000  // tempo pro robô realmente percorrer o trecho antes de desativar

async function waitForRobotNavReady(robotId) {
  const deadline = Date.now() + NAV_READY_TIMEOUT_MS
  while (Date.now() < deadline) {
    const s = await getStatus().catch(() => null)
    if (s?.nav2_ready_robots?.includes(robotId)) return true
    await sleep(NAV_READY_POLL_MS)
  }
  return false
}

export function useSimulation(intervalMs = 2000) {
  const [options, setOptions] = useState({ worlds: [], robots: [], roles: {} })
  const [status, setStatus] = useState(EMPTY_STATUS)
  const [actionError, setActionError] = useState(null)
  const [starting, setStarting] = useState(false)
  const [shape, setShape] = useState('L')
  const [dispatch, setDispatch] = useState({})  // robotId -> 'pending' | 'ok' | 'error: ...'
  const dispatchedRef = useRef(false)

  const points = SHAPES[shape].points

  // Assim que a simulação fica pronta, manda cada robô pro seu ponto da
  // formação, em sequência (um de cada vez, com uma pequena pausa entre —
  // não precisa ser simultâneo) — só uma vez por sessão de simulação
  // (dispatchedRef reseta quando ela para).
  useEffect(() => {
    if (!status.running) {
      dispatchedRef.current = false
      setDispatch({})
      return
    }
    if (!status.ready || dispatchedRef.current) return
    dispatchedRef.current = true
    const activeRobots = status.robots?.length ? status.robots : ROBOTS

    // Só robôs com papel MUUT (Mobile Unit Under Tasking) em roles.yaml
    // aceitam comando de movimento — FUUT (sensor fixo) e SU (unidade de
    // suporte) ficam de fora, mesmo que estejam na simulação. Papel
    // desconhecido (roles.yaml não carregou ainda) trata como móvel, pra
    // não quebrar o comportamento de quem não tem essa config.
    const roles = options.roles || {}
    const movable = activeRobots.filter(id => (roles[id] || 'MUUT') === 'MUUT')
    const skipped = activeRobots.filter(id => !movable.includes(id))
    if (skipped.length) {
      setDispatch(d => {
        const next = { ...d }
        skipped.forEach(id => { next[id] = `skip: papel ${roles[id]} não é móvel` })
        return next
      })
    }

    ;(async () => {
      for (let i = 0; i < movable.length; i++) {
        const robotId = movable[i]
        const [x, y, yaw] = points[i] || [0, 0, 0]
        try {
          setDispatch(d => ({ ...d, [robotId]: 'ativando navegação…' }))
          const actRes = await activateRobot(robotId)
          if (!actRes.success) throw new Error(actRes.message || 'falha ao ativar navegação')

          const gotReady = await waitForRobotNavReady(robotId)
          if (!gotReady) throw new Error('navegação não ficou pronta a tempo')

          setDispatch(d => ({ ...d, [robotId]: 'pending' }))
          const result = await goToPoint({ robotId, x, y, yaw })
          if (!result.success) throw new Error(result.message || 'falhou sem detalhe')
          setDispatch(d => ({ ...d, [robotId]: 'ok' }))
          await sleep(TRAVEL_DWELL_MS)  // dá tempo dele percorrer o trecho antes de desligar a navegação dele
        } catch (e) {
          setDispatch(d => ({ ...d, [robotId]: `error: ${e.message}` }))
        } finally {
          await deactivateRobot(robotId).catch(() => {})  // sempre libera o robô, mesmo se algo acima falhou
        }
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.running, status.ready])

  useEffect(() => {
    getSimulationOptions().then(setOptions).catch(() => {})
  }, [])

  useEffect(() => {
    let alive = true
    const refresh = async () => {
      try {
        const data = await getSimulationStatus()
        if (alive && data) setStatus(data)
      } catch {
        // Backend pode estar offline; painel só mostra o último status conhecido.
      }
    }
    refresh()
    const timer = setInterval(refresh, intervalMs)
    return () => { alive = false; clearInterval(timer) }
  }, [intervalMs])

  const start = useCallback(async ({ mode, world, robots }) => {
    setActionError(null)
    setStarting(true)
    try {
      // sequentialNav sempre ligado no modo multi: sobe só Gazebo + robôs
      // spawnados, sem Nav2 de ninguém — a navegação de cada um liga sob
      // demanda no loop de dispatch acima, 1 por vez.
      await startSimulation({ mode, world, robots, sequentialNav: mode === 'multi' })
      const data = await getSimulationStatus()
      setStatus(data)
    } catch (e) {
      setActionError(e.message)
    } finally {
      setStarting(false)
    }
  }, [])

  const stop = useCallback(async () => {
    setActionError(null)
    try {
      await stopSimulation()
      setStatus(EMPTY_STATUS)
    } catch (e) {
      setActionError(e.message)
    }
  }, [])

  return {
    options, status, actionError, starting, start, stop,
    shape, setShape, dispatch,
  }
}
