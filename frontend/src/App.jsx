import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import ConfigForm from './components/ConfigForm'
import AgentFleetPanel from './components/AgentFleetPanel'
import SimulationPanel from './components/SimulationPanel'
import MapView from './components/MapView'
import ConnectionPanel, { ROBOT_PROFILES } from './components/ConnectionPanel'
import DiscoveryPanel from './components/DiscoveryPanel'
import RunHistoryPanel from './components/RunHistoryPanel'
import { color, btn } from './styles/tokens'
import {
  discoverRobots as fetchDiscoveredRobots,
  getStatus,
  goToPoint,
  runConfig,
  stopJob,
  testSsh,
} from './api/fleetApi'
import { useFleetStatus } from './hooks/useFleetStatus'
import { useJobPolling } from './hooks/useJobPolling'
import { useRoutePoses, useRoutes } from './hooks/useRoutes'
import { useRunHistory } from './hooks/useRunHistory'
import { useSimulation } from './hooks/useSimulation'

// Agentes de IA fora do escopo atual (saíram da dissertação): escondidos da
// tela, código mantido. Religar com VITE_SHOW_AGENTS=true no build.
const SHOW_AGENTS = import.meta.env.VITE_SHOW_AGENTS === 'true'

const DEFAULT_CFG = {
  command:         'replay',
  robot:           'default',
  route:           'percurso_cbsoft',
  collect:         true,
  // pose (SLAM) e amcl_pose (mapa pronto): só um existe em cada modo, o outro
  // grava 0 mensagens; ground truth idem fora da simulação.
  topics:          ['scan', 'odom', 'pose', 'amcl_pose', 'ground_truth_pose_clean'],
  initial_pose:    [0, 0, 0],
  points:          [[0.5, 0.0, 0.0], [1.0, 0.0, 0.0]],
  return_to_start: [0, 0, 0],
  run_label:          '',
  ble_target_address: '',
}

// Pose de spawn de cada robô no mundo Gazebo compartilhado — tem que bater
// com DEFAULT_POSES em turtlebot4_multi_sim.launch.py. Usado só pra alinhar
// os marcadores de múltiplos robôs num mesmo mapa (ver allPoses); não afeta
// navegação nem SLAM, que continuam 100% independentes por robô.
const SPAWN_OFFSETS = { tb1: [0, 0], tb2: [0, 2], tb3: [0, 4] }

// ── App principal ─────────────────────────────────────────────────────────────
export default function App() {
  const [cfg, setCfg]               = useState(DEFAULT_CFG)
  const { jobId, job, running, setRunning, startPolling, stopPolling, resetJob } = useJobPolling()
  const [error, setError]           = useState(null)
  const [showResult, setShowResult] = useState(false)
  const status                      = useFleetStatus()
  const { routes, loading: routesLoading, error: routesError, refreshRoutes } = useRoutes(cfg.robot)
  const replayPoses = useRoutePoses(cfg.command === 'replay' ? cfg.route : '', cfg.robot)
  const [routeOutside, setRouteOutside] = useState(null)
  const replayOffMap = cfg.command === 'replay' && routeOutside > 0
  const [resetMsg, setResetMsg]     = useState(null)
  const [resetting, setResetting]   = useState(false)
  const sim                         = useSimulation()

  const [connPanel, setConnPanel]             = useState(false)
  const [selectedProfile, setSelectedProfile] = useState('custom')
  const [connStatus, setConnStatus]           = useState('idle')
  const [connMsg, setConnMsg]                 = useState('')
  const [discoverPanel, setDiscoverPanel]     = useState(false)
  const [agentPanel, setAgentPanel]           = useState(false)
  const [historyPanel, setHistoryPanel]       = useState(false)
  const runHistory                            = useRunHistory()
  const [discovering, setDiscovering]         = useState(false)
  const [discovered, setDiscovered]           = useState([])
  const [discoverError, setDiscoverError]     = useState(null)
  const [subnet, setSubnet]                   = useState('')
  const [testingSSH, setTestingSSH]           = useState({})
  const [sshUser, setSshUser]                 = useState('ubuntu')
  const [extraProfiles, setExtraProfiles]     = useState([])

  const outputRef   = useRef(null)
  const panelRef    = useRef(null)
  const discoverRef = useRef(null)
  const agentRef    = useRef(null)
  const historyRef  = useRef(null)

  // Fecha painéis ao clicar fora
  useEffect(() => {
    const h = e => {
      if (panelRef.current && !panelRef.current.contains(e.target))    setConnPanel(false)
      if (discoverRef.current && !discoverRef.current.contains(e.target)) setDiscoverPanel(false)
      if (agentRef.current && !agentRef.current.contains(e.target))    setAgentPanel(false)
      if (historyRef.current && !historyRef.current.contains(e.target)) setHistoryPanel(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  useEffect(() => {
    if (outputRef.current) outputRef.current.scrollTop = outputRef.current.scrollHeight
  }, [job?.lines?.length])

  useEffect(() => {
    if (job && !job.running && job.exit_code === 0) refreshRoutes()
  }, [job?.running, job?.exit_code, refreshRoutes])

  useEffect(() => {
    if (job && !job.running) runHistory.refresh()
  }, [job?.running, runHistory.refresh])

  // Navega pela rota definida sem gravar (teste rápido de percurso)
  const [navigating, setNavigating] = useState(false)
  const navigateRoute = useCallback(async () => {
    if (!cfg.points.length) return
    setNavigating(true)
    try {
      for (const [x, y, yaw] of cfg.points) {
        const d = await goToPoint({ robotId: cfg.robot, x, y, yaw })
        if (!d.success) break
        // Aguarda robot chegar (polling nav_state)
        await new Promise(res => {
          const t = setInterval(async () => {
            const s = await getStatus().catch(() => null)
            if (!s) return
            const nav = s.robots?.[0]?.nav_state
            if (nav === 'idle' || nav === 'failed') { clearInterval(t); res() }
          }, 800)
          setTimeout(() => { clearInterval(t); res() }, 120000)
        })
      }
    } finally { setNavigating(false) }
  }, [cfg.points, cfg.robot])

  // Clique no mapa → acrescenta um waypoint [x, y, yaw=0] ao fim da rota.
  const addWaypoint = useCallback((x, y) => {
    setCfg(c => ({ ...c, points: [...c.points, [x, y, 0]] }))
  }, [])

  const connectRobot = async () => {
    const profile = [...ROBOT_PROFILES, ...extraProfiles].find(p => p.id === selectedProfile)
    if (!profile) return
    if (profile.type === 'ssh') { setConnStatus('error'); setConnMsg(`SSH para ${profile.host} ainda não implementado.`); return }
    setConnStatus('connecting'); setConnMsg('')
    try {
      await getStatus({ signal: AbortSignal.timeout(4000) })
      setConnStatus('connected'); setConnMsg('Backend respondendo.'); setConnPanel(false)
    } catch (e) { setConnStatus('error'); setConnMsg(`Backend não respondeu: ${e.message}`) }
  }

  const discoverRobots = async () => {
    setDiscovering(true); setDiscovered([]); setDiscoverError(null)
    try {
      const data = await fetchDiscoveredRobots({ subnet, signal: AbortSignal.timeout(40000) })
      if (data.error) { setDiscoverError(data.error); return }
      setDiscovered(data.found || [])
      if (!data.found?.length) setDiscoverError(`Nenhum host encontrado em ${data.subnet_scanned || '(auto)'}.0/24`)
    } catch (e) { setDiscoverError(`Erro: ${e.message}`) }
    finally { setDiscovering(false) }
  }

  const testSSH = async ip => {
    setTestingSSH(prev => ({ ...prev, [ip]: 'testing' }))
    try {
      const data = await testSsh({ host: ip, user: sshUser })
      const st = data.success && data.has_ros2 ? 'ok' : data.success ? 'no_ros' : 'error'
      setTestingSSH(prev => ({ ...prev, [ip]: st }))
      if (st === 'ok') setExtraProfiles(prev => prev.find(p => p.host === ip) ? prev : [...prev, { id: `ssh_${ip}`, label: `SSH ${ip} (${sshUser})`, type: 'ssh', host: ip, user: sshUser }])
    } catch { setTestingSSH(prev => ({ ...prev, [ip]: 'error' })) }
  }

  // Parar de verdade: o backend encerra o experimento, cancela a meta do Nav2
  // (o que para o robô) e fecha a gravação. A tela continua acompanhando até o
  // job terminar, para mostrar o que aconteceu.
  const [stopping, setStopping] = useState(false)
  const stopRun = async () => {
    if (!jobId) { stopPolling(); return }
    setStopping(true)
    try {
      const data = await stopJob(jobId)
      if (!data?.cancel) setError('Execução encerrada, mas o cancelamento da navegação não foi confirmado: confira o robô.')
    } catch (e) {
      setError(`Não foi possível parar pelo servidor: ${e.message}. Pare o robô fisicamente.`)
      stopPolling()
    } finally { setStopping(false) }
  }

  const run = async () => {
    setError(null)
    if (!cfg.route.trim())                             { setError('Nome da rota vazio.'); return }
    if (cfg.command === 'record' && !cfg.points.length){ setError('Adiciona pelo menos 1 waypoint.'); return }
    if (cfg.collect && !cfg.topics.length)             { setError('Seleciona pelo menos 1 tópico.'); return }

    resetJob(); setRunning(true)
    try {
      const data = await runConfig(cfg)
      if (!data?.job_id) { setRunning(false); setError(data?.message || 'Erro ao iniciar job'); return }
      startPolling(data.job_id)
    } catch (e) {
      setRunning(false)
      setError(`Erro: ${e.message}`)
    }
  }

  const resetToOrigin = async () => {
    setResetting(true); setResetMsg(null)
    try {
      const data = await goToPoint({ robotId: cfg.robot, x: 0, y: 0, yaw: 0 })
      setResetMsg(data.success ? 'ok' : (data.message || 'erro'))
    } catch (e) { setResetMsg(`erro: ${e.message}`) }
    finally { setResetting(false); setTimeout(() => setResetMsg(null), 6000) }
  }

  // Robô cujo mapa/pose/status são exibidos: o selecionado no dropdown
  // "Robô" (cfg.robot), com fallback pro primeiro robô da frota reportado
  // por /api/status quando "único"/nenhum estiver selecionado ainda.
  // "??", não "||": robot_id="" é válido (modo single-robot, tópicos sem
  // prefixo) — "||" trataria essa string vazia como falsy e sempre cairia
  // em 'tb1', escondendo o robô único mesmo com pose/mapa já chegando do
  // backend.
  const effectiveRobotId = (cfg.robot && cfg.robot !== 'default')
    ? cfg.robot
    : (status.robots?.[0]?.robot_id ?? 'tb1')
  const pose   = status.poses?.[effectiveRobotId] || status.pose || {}
  // Todas as poses conhecidas (pro MapView desenhar os N robôs ao mesmo
  // tempo) — cai pra { <robô> : pose } em backends antigos sem status.poses.
  // Cada robô roda SLAM independente: (0,0) do mapa dele é a própria pose de
  // spawn no Gazebo (turtlebot4_multi_sim.launch.py DEFAULT_POSES), não um
  // referencial mundial compartilhado. Sem essa correção, o marcador de um
  // robô B desenhado sobre o mapa do robô A cai onde as coordenadas cruas de
  // B "por acaso" caem no sistema de A — visto ao vivo: tb2 aparecendo
  // colado no tb1 mesmo os dois nascendo 2 m separados de verdade. Corrige
  // somando a diferença entre o spawn de cada robô e o do robô cujo mapa
  // está sendo mostrado.
  const allPoses = useMemo(() => {
    const raw = status.poses || (status.pose ? { [effectiveRobotId]: status.pose } : {})
    const [refX, refY] = SPAWN_OFFSETS[effectiveRobotId] || [0, 0]
    const out = {}
    for (const [rid, p] of Object.entries(raw)) {
      if (!p?.valid) { out[rid] = p; continue }
      const [ox, oy] = SPAWN_OFFSETS[rid] || [0, 0]
      out[rid] = { ...p, x: p.x + (ox - refX), y: p.y + (oy - refY) }
    }
    return out
  }, [status.poses, status.pose, effectiveRobotId])
  const robot  = status.robots?.find(r => r.robot_id === effectiveRobotId) || status.robots?.[0] || {}
  const nav2Ok = status.nav2_ready === true
  const isConnected = connStatus === 'connected'

  const lineColor = line => {
    if (line.includes('[OK]'))     return color.success
    if (line.includes('[FALHOU]')) return color.danger
    if (line.includes('[TRACE]'))  return color.textMuted
    if (line.includes('Resumo'))   return color.warning
    if (line.includes('==='))      return color.blue
    return color.text
  }

  const deg = r => (r * 180 / Math.PI).toFixed(1)

  const openConnPanel     = () => { setConnPanel(v => !v); setDiscoverPanel(false); setAgentPanel(false); setHistoryPanel(false) }
  const openDiscoverPanel = () => { setDiscoverPanel(v => !v); setConnPanel(false); setAgentPanel(false); setHistoryPanel(false) }
  const openAgentPanel    = () => { setAgentPanel(v => !v); setConnPanel(false); setDiscoverPanel(false); setHistoryPanel(false) }
  const openHistoryPanel  = () => { setHistoryPanel(v => !v); setConnPanel(false); setDiscoverPanel(false); setAgentPanel(false) }

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', background: color.bgApp, color: color.text, height: '100vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.3rem 1rem', borderBottom: `1px solid ${color.border}`, flexShrink: 0 }}>
        <h1 style={{ margin: 0, fontSize: '1.1rem', color: color.brand, fontWeight: 700 }}>Fleet UI</h1>
        <div style={{ display: 'flex', flexWrap: 'wrap', fontSize: '0.78rem', fontFamily: 'monospace', alignItems: 'stretch', background: color.bgPanel, border: `1px solid ${color.border}`, borderRadius: '8px', overflow: 'hidden' }}>
          {[
            { label: 'Nav2',   value: nav2Ok ? 'ON' : 'OFF',           color: nav2Ok ? color.success : color.danger },
            { label: 'Nav',    value: robot.nav_state || '—',           color: robot.nav_state === 'navigating' ? color.success : robot.nav_state === 'failed' ? color.danger : color.text },
            { label: 'Coleta', value: robot.collection_on ? 'ON':'OFF', color: robot.collection_on ? color.success : color.textMuted },
            { label: 'x',      value: pose.valid ? pose.x.toFixed(3) : '—', color: pose.valid ? color.blue : color.textMuted },
            { label: 'y',      value: pose.valid ? pose.y.toFixed(3) : '—', color: pose.valid ? color.blue : color.textMuted },
            { label: 'yaw',    value: pose.valid ? `${deg(pose.yaw)}°` : '—', color: pose.valid ? color.blue : color.textMuted },
          ].map(({ label, value, color: statColor }) => (
            <div key={label} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '0.3rem 0.7rem', borderRight: `1px solid ${color.border}` }}>
              <span style={{ fontSize: '0.62rem', color: color.textFaint, fontWeight: 600 }}>{label}</span>
              <span style={{ color: statColor, fontWeight: 600, marginTop: '0.05rem' }}>{value}</span>
            </div>
          ))}
          <button onClick={resetToOrigin} disabled={resetting} aria-label="Enviar robô para a origem (0,0,0)" title="Envia robô para (0,0,0)"
            style={{ background: 'none', border: 'none', cursor: resetting ? 'not-allowed' : 'pointer', padding: '0.3rem 0.75rem', color: resetMsg === 'ok' ? color.success : resetMsg ? color.danger : color.indigo, fontWeight: 700, fontSize: '0.8rem', opacity: resetting ? 0.6 : 1 }}>
            {resetting ? '⏳' : resetMsg === 'ok' ? '✓' : resetMsg ? '✗' : '⟳ Origem'}
          </button>
        </div>
      </div>

      {/* ── Barra de conexão ─────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem 0.75rem', alignItems: 'center', padding: '0.3rem 1rem', borderBottom: `1px solid ${color.border}`, flexShrink: 0, position: 'relative' }}>

        <ConnectionPanel
          containerRef={panelRef}
          isOpen={connPanel}
          onToggle={openConnPanel}
          profiles={ROBOT_PROFILES}
          extraProfiles={extraProfiles}
          selectedProfile={selectedProfile}
          onSelectProfile={setSelectedProfile}
          connStatus={connStatus}
          connMsg={connMsg}
          onConnect={connectRobot}
          onDisconnect={() => { setConnStatus('idle'); setConnMsg(''); setConnPanel(false) }}
        />

        <DiscoveryPanel
          containerRef={discoverRef}
          isOpen={discoverPanel}
          onToggle={openDiscoverPanel}
          subnet={subnet}
          onSubnetChange={setSubnet}
          sshUser={sshUser}
          onSshUserChange={setSshUser}
          discovering={discovering}
          discovered={discovered}
          discoverError={discoverError}
          onDiscover={discoverRobots}
          testingSSH={testingSSH}
          onTestSSH={testSSH}
        />

        {SHOW_AGENTS && (
          <div ref={agentRef} style={{ position: 'relative' }}>
            <button onClick={openAgentPanel} aria-expanded={agentPanel} aria-haspopup="true"
              style={{ ...btn(color.bgPanel, color.purple), display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              🤖 Agentes IA <span aria-hidden="true" style={{ fontSize: '0.7rem', opacity: 0.7 }}>{agentPanel ? '▲' : '▼'}</span>
            </button>
            {agentPanel && <AgentFleetPanel robotIds={(status.robots || []).map(r => r.robot_id)} />}
          </div>
        )}

        <RunHistoryPanel
          containerRef={historyRef}
          isOpen={historyPanel}
          onToggle={openHistoryPanel}
          history={runHistory}
        />

        {isConnected && <span style={{ fontSize: '0.8rem', color: color.success, fontFamily: 'monospace' }}>● Conectado — {[...ROBOT_PROFILES, ...extraProfiles].find(p => p.id === selectedProfile)?.label}</span>}
        {connStatus === 'error' && <span style={{ fontSize: '0.8rem', color: color.danger, fontFamily: 'monospace' }}>✗ {connMsg}</span>}
      </div>

      {/* ── Layout 3 colunas ─────────────────────────────────────────────────── */}
      <div className="fleet-main-grid" style={{ display: 'grid', gap: '0.6rem', flex: 1, minHeight: 0, padding: '0.5rem 0.75rem 0.5rem' }}>

        {/* Coluna esquerda: formulário */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', overflowY: 'auto', paddingRight: '0.2rem', minHeight: 0 }}>
          <SimulationPanel sim={sim} externalSim={nav2Ok && !sim.status.running} />

          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: color.textMuted, flexShrink: 0 }}>Configuração</span>
          <ConfigForm
            cfg={cfg}
            onChange={setCfg}
            currentPose={pose}
            routeNames={routes}
            routesLoading={routesLoading}
            routesError={routesError}
            onRefreshRoutes={refreshRoutes}
          />

          {!isConnected && (
            <div role="status" style={{ color: color.warning, fontSize: '0.82rem', padding: '0.5rem 0.75rem', background: 'rgba(251,191,36,0.08)', borderRadius: '6px', border: '1px solid rgba(251,191,36,0.2)' }}>
              ⚠ Conecte um robô antes de executar.
            </div>
          )}
          {isConnected && !nav2Ok && (
            <div role="status" style={{ color: color.warning, fontSize: '0.82rem', padding: '0.5rem 0.75rem', background: 'rgba(251,191,36,0.08)', borderRadius: '6px', border: '1px solid rgba(251,191,36,0.2)' }}>
              ⚠ Nav2 offline — aguarda ~60s após o Terminal 2.
            </div>
          )}
          {error && <div role="alert" style={{ color: color.danger, fontSize: '0.82rem', padding: '0.5rem 0.75rem', background: 'rgba(248,113,113,0.1)', borderRadius: '6px' }}>{error}</div>}
          {replayOffMap && (
            <div role="status" style={{ color: color.warning, fontSize: '0.82rem', padding: '0.5rem 0.75rem', background: 'rgba(251,191,36,0.08)', borderRadius: '6px', border: '1px solid rgba(251,191,36,0.2)' }}>
              ⚠ {routeOutside} ponto(s) da rota “{cfg.route}” ficam fora do mapa atual — ela é de outro mundo. Escolha outra rota ou suba o mundo certo.
            </div>
          )}

          <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
            {/* Navegar rota — percorre waypoints sem gravar */}
            {cfg.command === 'record' && (
              <button onClick={navigateRoute}
                disabled={navigating || running || !isConnected || !cfg.points.length}
                title="Percorre os waypoints sem gravar bag — teste rápido"
                style={btn(
                  navigating || running || !isConnected || !cfg.points.length ? color.bgDisabled : color.indigoDark,
                  color.indigoLight,
                  navigating || running || !isConnected || !cfg.points.length
                )}>
                {navigating ? '⏳ Navegando…' : '→ Navegar rota'}
              </button>
            )}

            {/* Executar record/replay com coleta */}
            <button onClick={run} disabled={running || navigating || !isConnected || replayOffMap}
              style={btn(running || navigating || !isConnected || replayOffMap ? color.brandBg : color.brandDark, color.brand, running || navigating || !isConnected || replayOffMap)}>
              {running ? '⏳ A executar…' : `▶ Executar ${cfg.command}`}
            </button>
            {running && (
              <button onClick={stopRun} disabled={stopping}
                style={btn(color.dangerBg, color.danger)}>{stopping ? '⏳ Parando…' : '■ Parar'}</button>
            )}
          </div>
        </div>

        {/* Coluna central: mapa — ocupa todo o espaço disponível */}
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' }}>
          <MapView
            robotId={effectiveRobotId}
            poses={allPoses}
            waypoints={cfg.command === 'record' ? cfg.points : replayPoses}
            onAddWaypoint={cfg.command === 'record' ? addWaypoint : undefined}
            onRouteOutsideChange={setRouteOutside}
          />
        </div>

        {/* Coluna direita: output */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', minHeight: 0, overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: color.textMuted }}>
              Output {jobId && <span style={{ color: color.blue2, fontWeight: 400 }}>#{jobId}</span>}
            </span>
            {job && !job.running && (
              <span style={{ fontSize: '0.82rem', color: job.exit_code === 0 ? color.success : color.danger, fontWeight: 600 }}>
                {job.exit_code === 0 ? '✓ Sucesso' : `✗ exit ${job.exit_code}`}
              </span>
            )}
          </div>

          <div ref={outputRef} role="log" aria-label="Saída da execução" aria-live="polite" style={{ flex: 1, background: color.bgPanel, border: `1px solid ${color.border}`, borderRadius: '8px', padding: '0.6rem 0.85rem', overflowY: 'auto', fontFamily: 'JetBrains Mono, Consolas, monospace', fontSize: '0.75rem', lineHeight: 1.6 }}>
            {!job && !running && <span style={{ color: color.textMuted }}>Aguardando execução…</span>}
            {job?.lines?.map((line, i) => (
              <div key={i} style={{ color: lineColor(line), whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{line}</div>
            ))}
            {running && <div aria-hidden="true" style={{ color: color.textMuted, animation: 'blink 1s step-end infinite' }}>▌</div>}
          </div>

          {/* Métricas */}
          {job?.result?.bag_metrics && (() => {
            const m = job.result.bag_metrics
            const cards = [
              m.wall_duration_s      != null && { label: 'Duração',      value: `${m.wall_duration_s} s`,      color: color.blue },
              m.odom_path_length_m   != null && { label: 'Percurso',     value: `${m.odom_path_length_m} m`,   color: color.success },
              m.odom_avg_speed_ms    != null && { label: 'Vel. média',   value: `${m.odom_avg_speed_ms} m/s`,  color: color.success },
              m.scan_avg_valid_points!= null && { label: 'Scan pts',     value: `${m.scan_avg_valid_points}`,  color: color.warning },
              m.imu_accel_mean_ms2   != null && { label: 'IMU accel',    value: `${m.imu_accel_mean_ms2} m/s²`,color: color.purpleLight },
              m.ble_rssi_mean_dbm    != null && { label: 'BLE RSSI',     value: `${m.ble_rssi_mean_dbm} dBm (${m.ble_rssi_min_dbm}…${m.ble_rssi_max_dbm}, n=${m.ble_rssi_n})`, color: color.brand },
            ].filter(Boolean)
            return cards.length > 0 && (
              <div style={{ background: color.bgPanel, border: `1px solid ${color.border}`, borderRadius: '8px', padding: '0.6rem 0.85rem', flexShrink: 0 }}>
                <div style={{ fontSize: '0.68rem', color: color.textMuted, fontWeight: 600, marginBottom: '0.4rem' }}>Métricas</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.35rem' }}>
                  {cards.map(({ label, value, color: cardColor }) => (
                    <div key={label} style={{ background: color.bgApp, borderRadius: '5px', padding: '0.3rem 0.5rem' }}>
                      <div style={{ fontSize: '0.62rem', color: color.textMuted }}>{label}</div>
                      <div style={{ fontSize: '0.78rem', fontWeight: 700, color: cardColor, fontFamily: 'monospace' }}>{value}</div>
                    </div>
                  ))}
                </div>
              </div>
            )
          })()}

          {job?.result && (
            <button onClick={() => setShowResult(true)} style={{ ...btn(color.bgPanel, color.border), fontSize: '0.75rem', flexShrink: 0 }}>
              ▸ Ver resultado JSON
            </button>
          )}
        </div>
      </div>

      {/* Modal JSON */}
      {showResult && job?.result && (
        <div onClick={() => setShowResult(false)} role="presentation"
          style={{ position: 'fixed', inset: 0, zIndex: 200, background: 'rgba(0,0,0,0.75)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '2rem' }}>
          <div onClick={e => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Resultado JSON da execução"
            style={{ background: color.bgPanel, border: `1px solid ${color.border}`, borderRadius: '12px', width: '100%', maxWidth: '800px', maxHeight: '80vh', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem 1.25rem', borderBottom: `1px solid ${color.border}` }}>
              <span style={{ fontSize: '0.82rem', fontWeight: 600, color: color.textMuted }}>Resultado JSON</span>
              <button onClick={() => setShowResult(false)} aria-label="Fechar" style={{ background: 'none', border: 'none', color: color.textMuted, cursor: 'pointer', fontSize: '1.1rem' }}>✕</button>
            </div>
            <pre style={{ flex: 1, overflowY: 'auto', margin: 0, padding: '1rem', fontFamily: 'monospace', fontSize: '0.8rem', lineHeight: 1.6, color: color.text }}>
              {JSON.stringify(job.result, null, 2)}
            </pre>
          </div>
        </div>
      )}

      <style>{`@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }`}</style>
    </div>
  )
}
