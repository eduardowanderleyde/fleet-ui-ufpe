import React from 'react'

// id = nome do tópico ROS2 gravado (bate 1:1 com o que o backend aceita,
// ver backend/main.py); desc = explicação curta pra quem não é de robótica.
const ALL_TOPICS = [
  { id: 'scan',     desc: 'LiDAR — mapa dos obstáculos ao redor' },
  { id: 'odom',     desc: 'rodas — posição estimada contando giros' },
  { id: 'imu',      desc: 'inercial — aceleração e rotação' },
  { id: 'pose',     desc: 'posição corrigida pelo SLAM (mais precisa que odom)' },
  { id: 'amcl_pose', desc: 'posição no mapa pronto (AMCL) — modo do robô real e do mundo CBSoft' },
  { id: 'ground_truth_pose_clean', desc: 'posição real exata, sem erro de estimativa — só na simulação' },
  { id: 'ble_rssi', desc: 'força do sinal Bluetooth (BLE) — precisa do nó ble_rssi_publisher rodando' },
]

const S = {
  label:    { fontSize: '0.72rem', fontWeight: 600, color: '#8b92a8', marginBottom: '0.3rem', display: 'block' },
  input:    { background: '#0d0f14', border: '1px solid #2a3142', borderRadius: '6px', color: '#e6e9ef', padding: '0.4rem 0.6rem', fontSize: '0.85rem', outline: 'none', fontFamily: 'monospace', width: '100%', boxSizing: 'border-box' },
  numInput: { background: '#0d0f14', border: '1px solid #2a3142', borderRadius: '6px', color: '#e6e9ef', padding: '0.4rem 0.5rem', fontSize: '0.82rem', outline: 'none', fontFamily: 'monospace', width: '70px', textAlign: 'center' },
  select:   { background: '#0d0f14', border: '1px solid #2a3142', borderRadius: '6px', color: '#e6e9ef', padding: '0.4rem 0.6rem', fontSize: '0.85rem', outline: 'none', width: '100%', boxSizing: 'border-box' },
  section:  { background: '#161a22', border: '1px solid #2a3142', borderRadius: '8px', padding: '0.85rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.65rem' },
  row:      { display: 'flex', flexWrap: 'wrap', gap: '0.75rem', alignItems: 'flex-start' },
  field:    { display: 'flex', flexDirection: 'column', flex: 1 },
}

function btn(bg, color, disabled = false) {
  return { background: bg, color, border: `1px solid ${color}`, borderRadius: '8px', padding: '0.45rem 0.9rem', fontSize: '0.85rem', fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.55 : 1, fontFamily: 'inherit' }
}

function CmdToggle({ value, onChange }) {
  const base = { padding: '0.4rem 1.2rem', fontSize: '0.85rem', fontWeight: 600, border: 'none', cursor: 'pointer', fontFamily: 'inherit' }
  const labels = { record: 'Gravar', replay: 'Reproduzir' }
  return (
    <div style={{ display: 'flex', flexShrink: 0, borderRadius: '8px', overflow: 'hidden', border: '1px solid #2a3142', alignSelf: 'flex-start' }}>
      {['record', 'replay'].map(cmd => (
        <button key={cmd} onClick={() => onChange(cmd)}
          style={{ ...base, background: value === cmd ? '#065f46' : '#161a22', color: value === cmd ? '#6ee7b7' : '#8b92a8' }}>
          {cmd === 'record' ? '⏺' : '▶'} {labels[cmd]}
        </button>
      ))}
    </div>
  )
}

function WaypointList({ points, onChange }) {
  const update = (i, j, val) => onChange(points.map((p, pi) => pi === i ? p.map((v, vi) => vi === j ? parseFloat(val) || 0 : v) : p))
  const add    = ()  => onChange([...points, [0, 0, 0]])
  const remove = i   => onChange(points.filter((_, pi) => pi !== i))
  const move   = (i, delta) => {
    const next = [...points]
    const j = i + delta
    if (j < 0 || j >= next.length) return
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
      {points.map((p, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.75rem', color: '#6366f1', width: '20px', textAlign: 'right', fontWeight: 700 }}>#{i + 1}</span>
          {['x', 'y', 'yaw'].map((lbl, j) => (
            <div key={lbl} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.1rem' }}>
              <span style={{ fontSize: '0.65rem', color: '#4b5563' }}>{lbl}</span>
              <input type="number" step="0.1" value={p[j]} onChange={e => update(i, j, e.target.value)} style={S.numInput} />
            </div>
          ))}
          <div style={{ display: 'flex', gap: '0.2rem', marginTop: '0.9rem' }}>
            <button onClick={() => move(i, -1)} disabled={i === 0} style={{ ...btn('#161a22', '#2a3142', i === 0), padding: '0.2rem 0.45rem', fontSize: '0.75rem' }}>↑</button>
            <button onClick={() => move(i, 1)} disabled={i === points.length - 1} style={{ ...btn('#161a22', '#2a3142', i === points.length - 1), padding: '0.2rem 0.45rem', fontSize: '0.75rem' }}>↓</button>
            <button onClick={() => remove(i)} style={{ ...btn('#3a1a1a', '#f87171'), padding: '0.2rem 0.5rem', fontSize: '0.8rem' }}>✕</button>
          </div>
        </div>
      ))}
      <button onClick={add} style={{ ...btn('#161a22', '#6366f1'), padding: '0.3rem 0.75rem', fontSize: '0.8rem', alignSelf: 'flex-start', marginTop: '0.2rem' }}>
        + Waypoint
      </button>
    </div>
  )
}

function XYYaw({ value, onChange, label }) {
  const update = (i, val) => { const next = [...value]; next[i] = parseFloat(val) || 0; onChange(next) }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
      {label && <span style={S.label}>{label}</span>}
      <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
        {['x', 'y', 'yaw'].map((lbl, i) => (
          <div key={lbl} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.1rem' }}>
            <span style={{ fontSize: '0.65rem', color: '#4b5563' }}>{lbl}</span>
            <input type="number" step="0.1" value={value[i]} onChange={e => update(i, e.target.value)} style={S.numInput} />
          </div>
        ))}
      </div>
    </div>
  )
}

export default function ConfigForm({
  cfg,
  onChange,
  currentPose,
  routeNames = [],
  routesLoading = false,
  routesError = null,
  onRefreshRoutes,
}) {
  const set = (key, val) => onChange({ ...cfg, [key]: val })

  const toggleTopic = t => {
    const next = cfg.topics.includes(t) ? cfg.topics.filter(x => x !== t) : [...cfg.topics, t]
    set('topics', next)
  }

  const usarPoseAtual = () => {
    if (!currentPose?.valid) return
    set('initial_pose', [
      parseFloat(currentPose.x.toFixed(3)),
      parseFloat(currentPose.y.toFixed(3)),
      parseFloat(currentPose.yaw.toFixed(3)),
    ])
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>

      <div style={S.section}>
        <div style={S.row}>
          <div style={S.field}>
            <span style={S.label}>Comando</span>
            <CmdToggle value={cfg.command} onChange={v => set('command', v)} />
          </div>
          <div style={{ ...S.field, flex: '0 0 110px' }}>
            <span style={S.label}>Robô</span>
            <select value={cfg.robot} onChange={e => set('robot', e.target.value)} style={S.select}>
              <option value="default">único</option>
              <option value="tb1">tb1</option>
              <option value="tb2">tb2</option>
            </select>
          </div>
        </div>
        <div style={S.field}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={S.label}>{cfg.command === 'replay' ? 'Rota para replay' : 'Nome da rota'}</span>
            {cfg.command === 'replay' && (
              <button onClick={onRefreshRoutes} disabled={routesLoading}
                style={{ background: 'none', border: 'none', color: routesLoading ? '#4b5563' : '#6366f1', cursor: routesLoading ? 'not-allowed' : 'pointer', fontSize: '0.72rem', padding: 0 }}>
                {routesLoading ? 'carregando...' : 'atualizar'}
              </button>
            )}
          </div>
          {cfg.command === 'replay' ? (
            <>
              <select value={cfg.route} onChange={e => set('route', e.target.value)} style={S.select}>
                <option value="">{routeNames.length ? 'selecione uma rota' : 'nenhuma rota encontrada'}</option>
                {cfg.route && !routeNames.includes(cfg.route) && <option value={cfg.route}>{cfg.route} (manual)</option>}
                {routeNames.map(route => <option key={route} value={route}>{route}</option>)}
              </select>
              {routesError && <span style={{ color: '#fbbf24', fontSize: '0.72rem' }}>Rotas indisponíveis: {routesError}</span>}
            </>
          ) : (
            <input value={cfg.route} onChange={e => set('route', e.target.value)} placeholder="percurso_initial" style={S.input} />
          )}
        </div>
      </div>

      <div style={S.section}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
          <input type="checkbox" checked={cfg.collect} onChange={e => set('collect', e.target.checked)} style={{ accentColor: '#6ee7b7', width: 16, height: 16 }} />
          <span style={{ fontSize: '0.85rem', color: cfg.collect ? '#6ee7b7' : '#8b92a8', fontWeight: 600 }}>Gravar bag</span>
        </label>
        {cfg.collect && (
          <div>
            <span style={S.label}>Tópicos</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
              {ALL_TOPICS.map(({ id, desc }) => (
                <label key={id} title={desc} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer',
                  background: cfg.topics.includes(id) ? 'rgba(99,102,241,0.12)' : 'transparent',
                  border: `1px solid ${cfg.topics.includes(id) ? '#6366f1' : '#2a3142'}`,
                  borderRadius: '6px', padding: '0.3rem 0.65rem' }}>
                  <input type="checkbox" checked={cfg.topics.includes(id)} onChange={() => toggleTopic(id)} style={{ accentColor: '#6366f1', margin: 0, flexShrink: 0 }} />
                  <span style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                    <span style={{ fontSize: '0.82rem', color: cfg.topics.includes(id) ? '#e6e9ef' : '#8b92a8', fontFamily: 'monospace', overflowWrap: 'anywhere' }}>{id}</span>
                    <span style={{ fontSize: '0.72rem', color: '#4b5563' }}>{desc}</span>
                  </span>
                </label>
              ))}
            </div>
            {cfg.topics.includes('ble_rssi') && (
              <div style={{ marginTop: '0.5rem' }}>
                <span style={S.label}>Endereço BLE alvo</span>
                <input value={cfg.ble_target_address || ''} onChange={e => set('ble_target_address', e.target.value)}
                  placeholder="AA:BB:CC:DD:EE:FF" style={{ ...S.input, fontFamily: 'monospace' }} />
                <span style={{ fontSize: '0.68rem', color: '#4b5563' }}>
                  Seta via ros2 param set antes de rodar — ble_rssi_publisher já precisa estar de pé.
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      <div style={S.section}>
        <span style={S.label}>Rótulo da execução <span style={{ color: '#4b5563', fontWeight: 400 }}>— opcional</span></span>
        <input value={cfg.run_label || ''} onChange={e => set('run_label', e.target.value)}
          placeholder="ex.: moto-moto, homogênea" style={S.input} />
      </div>

      <div style={S.section}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={S.label}>Pose inicial</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            {currentPose?.valid && (
              <span style={{ fontSize: '0.7rem', color: '#4b5563', fontFamily: 'monospace' }}>
                ({currentPose.x.toFixed(2)}, {currentPose.y.toFixed(2)})
              </span>
            )}
            <button onClick={usarPoseAtual} disabled={!currentPose?.valid}
              style={{ ...btn('#161a22', currentPose?.valid ? '#6366f1' : '#2a3142', !currentPose?.valid), fontSize: '0.72rem', padding: '0.2rem 0.55rem' }}>
              ⊕ Pose atual
            </button>
          </div>
        </div>
        <XYYaw value={cfg.initial_pose} onChange={v => set('initial_pose', v)} />
      </div>

      <div style={S.section}>
        {cfg.command === 'record' ? (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={S.label}>Waypoints <span style={{ color: '#6366f1', fontWeight: 400 }}>— clica no mapa</span></span>
              <button onClick={() => set('points', [])}
                style={{ background: 'none', border: 'none', color: '#6b7280', cursor: 'pointer', fontSize: '0.72rem', padding: 0 }}>
                🗑 limpar
              </button>
            </div>

            <div>
              <span style={{ ...S.label, marginBottom: '0.4rem' }}>Percursos predefinidos</span>
              <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                {[
                  { label: 'Linha 1m',   pts: [[1,0,0],[2,0,0],[3,0,0]] },
                  { label: 'Linha 2m',   pts: [[0,1,0],[0,2,0],[0,3,0]] },
                  { label: 'Quadrado',   pts: [[1,0,0],[1,1,0],[0,1,0],[0,0,0]] },
                  { label: 'L',          pts: [[2,0,0],[4,0,0],[4,2,0]] },
                  { label: 'Zigzag',     pts: [[1,0,0],[2,1,0],[3,0,0],[4,1,0]] },
                ].map(({ label, pts }) => (
                  <button key={label} onClick={() => set('points', pts)}
                    style={{ background: '#0d0f14', border: '1px solid #2a3142', borderRadius: '6px',
                             color: '#8b92a8', cursor: 'pointer', fontSize: '0.72rem',
                             padding: '0.25rem 0.55rem', fontFamily: 'inherit' }}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <WaypointList points={cfg.points} onChange={v => set('points', v)} />
          </>
        ) : (
          <XYYaw label="Retornar ao início antes do replay" value={cfg.return_to_start} onChange={v => set('return_to_start', v)} />
        )}
      </div>
    </div>
  )
}
