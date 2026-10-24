import React from 'react'
import { ROBOTS, SHAPES } from '../hooks/useSimulation'

const S = {
  box:    { background: '#161a22', border: '1px solid #2a3142', borderRadius: '8px', padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' },
  title:  { fontSize: '0.8rem', fontWeight: 600, color: '#8b92a8' },
  select: { background: '#0d0f14', border: '1px solid #2a3142', borderRadius: '6px', color: '#e6e9ef', padding: '0.4rem 0.6rem', fontSize: '0.85rem', outline: 'none', width: '100%', boxSizing: 'border-box' },
  log:    { background: '#0d0f14', border: '1px solid #2a3142', borderRadius: '6px', padding: '0.4rem 0.55rem', fontSize: '0.68rem', fontFamily: 'monospace', color: '#8b92a8', maxHeight: '110px', overflowY: 'auto', whiteSpace: 'pre-wrap' },
}

function btn(bg, color, disabled = false) {
  return { background: bg, color, border: `1px solid ${color}`, borderRadius: '8px', padding: '0.45rem 0.9rem', fontSize: '0.85rem', fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.55 : 1, fontFamily: 'inherit', width: '100%' }
}

function statusLine(status) {
  if (status.error) return { label: '✗ erro', color: '#f87171' }
  if (status.running && status.ready) return { label: '✓ pronta', color: '#6ee7b7' }
  if (status.running) return { label: '⏳ subindo…', color: '#fbbf24' }
  return null
}

// externalSim: Nav2 de pé sem ter sido iniciado por este painel (Docker,
// run_all.sh). Iniciar outra simulação aqui sobreporia as duas no mesmo ROS.
export default function SimulationPanel({ sim, externalSim = false }) {
  const { status, actionError, starting, start, stop, shape, setShape, dispatch } = sim
  const st = statusLine(status)
  const activeRobots = status.robots?.length ? status.robots : ROBOTS

  return (
    <div style={S.box}>
      <span style={S.title}>Missão Coordenada</span>

      {!status.running && (
        <select value={shape} onChange={e => setShape(e.target.value)} style={S.select}>
          {Object.entries(SHAPES).map(([key, { label }]) => (
            <option key={key} value={key}>Formação — {label}</option>
          ))}
        </select>
      )}

      {!status.running && (
        <div style={{ fontSize: '0.68rem', color: '#8b92a8' }}>
          {ROBOTS.length} robôs ({ROBOTS.join('+')}) — par validado como estável nesta máquina.
        </div>
      )}

      {actionError && <div style={{ fontSize: '0.78rem', color: '#f87171' }}>{actionError}</div>}

      {externalSim && !status.running && (
        <div role="status" style={{ fontSize: '0.72rem', color: '#fbbf24' }}>
          Já há uma simulação rodando (Docker ou run_all.sh). Pare-a antes de iniciar outra aqui.
        </div>
      )}

      <button
        onClick={() => status.running ? stop() : start({ mode: 'multi', world: 'warehouse', robots: ROBOTS })}
        disabled={starting || (externalSim && !status.running)}
        style={status.running ? btn('#3a1a1a', '#f87171') : btn('#7A3E12', '#F2994A', starting || externalSim)}>
        {starting ? '⏳ Iniciando…' : status.running ? '■ Parar simulação' : `▶ Iniciar simulação — ${SHAPES[shape].label}`}
      </button>

      {status.running && (
        <>
          {st && <div style={{ fontSize: '0.78rem', color: st.color, fontWeight: 600 }}>{st.label}</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
            {activeRobots.map(id => {
              const d = dispatch[id]
              const color = d === 'ok' ? '#6ee7b7' : (d === 'pending' || d === 'ativando navegação…') ? '#fbbf24' : d?.startsWith('error') ? '#f87171' : d?.startsWith('skip') ? '#8b92a8' : '#4b5563'
              const label = d === 'ok' ? '✓ chegou' : d === 'pending' ? '⏳ indo…' : d === 'ativando navegação…' ? '⏳ ativando…' : d?.startsWith('error') ? '✗ erro' : d?.startsWith('skip') ? '○ não-móvel' : '— aguardando'
              return (
                <div key={id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontFamily: 'monospace' }}>
                  <span style={{ color: '#a0aec0' }}>{id}</span>
                  <span style={{ color }}>{label}</span>
                </div>
              )
            })}
          </div>
          <div style={S.log}>
            {status.lines.slice(-8).map((l, i) => <div key={i}>{l}</div>)}
          </div>
        </>
      )}
    </div>
  )
}
