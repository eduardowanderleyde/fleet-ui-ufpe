import React, { useState } from 'react'
import { useAgentFleet } from '../hooks/useAgentFleet'

const S = {
  panel: {
    position: 'absolute', top: '2.5rem', left: 0, zIndex: 100,
    background: '#161a22', border: '1px solid #2a3142', borderRadius: '10px',
    padding: '1rem', width: '640px', maxHeight: '70vh', overflowY: 'auto',
    boxShadow: '0 8px 32px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', gap: '0.75rem',
  },
  title: { fontSize: '0.78rem', fontWeight: 600, color: '#8b92a8' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.6rem' },
  card: { background: '#0d0f14', border: '1px solid #2a3142', borderRadius: '8px', padding: '0.6rem', display: 'flex', flexDirection: 'column', gap: '0.4rem' },
  textarea: {
    background: '#0d0f14', border: '1px solid #2a3142', borderRadius: '6px', color: '#e6e9ef',
    padding: '0.4rem 0.5rem', fontSize: '0.78rem', outline: 'none', fontFamily: 'inherit',
    resize: 'vertical', minHeight: '52px', width: '100%', boxSizing: 'border-box',
  },
  step: { fontSize: '0.68rem', color: '#8b92a8', fontFamily: 'monospace', borderLeft: '2px solid #2a3142', paddingLeft: '0.4rem' },
}

const STATUS_STYLE = {
  idle:    { label: '—',          color: '#4b5563' },
  running: { label: '⏳ rodando',  color: '#fbbf24' },
  done:    { label: '✓ concluído', color: '#6ee7b7' },
  error:   { label: '✗ erro',      color: '#f87171' },
}

function robotStatus(state) {
  if (!state) return 'idle'
  if (state.running) return 'running'
  if (state.error) return 'error'
  return 'done'
}

function RobotAgentCard({ robotId, instruction, onInstructionChange, state, disabled }) {
  const status = robotStatus(state)
  const st = STATUS_STYLE[status]

  return (
    <div style={S.card}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '0.82rem', fontWeight: 700, color: '#a5b4fc', fontFamily: 'monospace' }}>{robotId || 'único'}</span>
        <span style={{ fontSize: '0.7rem', color: st.color, fontWeight: 600 }}>{st.label}</span>
      </div>
      <textarea
        value={instruction}
        onChange={e => onInstructionChange(e.target.value)}
        disabled={disabled}
        placeholder="ex: vá até o ponto (1, 2) e pare"
        style={S.textarea}
      />
      {status === 'error' && <div style={{ fontSize: '0.7rem', color: '#f87171' }}>{state.error}</div>}
      {state?.final_text && <div style={{ fontSize: '0.75rem', color: '#e6e9ef' }}>{state.final_text}</div>}
      {state?.steps?.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
          {state.steps.map((s, i) => (
            <div key={i} style={S.step}>{s.tool_name}({Object.keys(s.tool_input || {}).length ? JSON.stringify(s.tool_input) : ''})</div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function AgentFleetPanel({ robotIds = ['tb1', 'tb2', 'tb3'] }) {
  const [instructions, setInstructions] = useState(() => Object.fromEntries(robotIds.map(id => [id, ''])))
  const { job, running, error, dispatch, stopPolling } = useAgentFleet()

  const setInstruction = (robotId, value) => setInstructions(prev => ({ ...prev, [robotId]: value }))

  const readyCount = robotIds.filter(id => instructions[id]?.trim()).length

  const fire = () => {
    const payload = Object.fromEntries(
      robotIds.filter(id => instructions[id]?.trim()).map(id => [id, instructions[id].trim()])
    )
    if (!Object.keys(payload).length) return
    dispatch(payload)
  }

  return (
    <div style={S.panel}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={S.title}>Agentes de IA — 1 por robô</span>
        <span style={{ fontSize: '0.7rem', color: '#4b5563' }}>escreva uma instrução por robô e dispare</span>
      </div>

      {robotIds.length === 0 && (
        <div role="status" style={{ fontSize: '0.78rem', color: '#8b92a8' }}>
          Nenhum robô visível no backend ainda — suba a simulação ou conecte o robô.
        </div>
      )}

      <div style={S.grid}>
        {robotIds.map(robotId => (
          <RobotAgentCard
            key={robotId}
            robotId={robotId}
            instruction={instructions[robotId]}
            onInstructionChange={v => setInstruction(robotId, v)}
            state={job?.robots?.[robotId]}
            disabled={running}
          />
        ))}
      </div>

      {error && <div style={{ fontSize: '0.78rem', color: '#f87171' }}>{error}</div>}

      <div style={{ display: 'flex', gap: '0.6rem' }}>
        <button
          onClick={fire}
          disabled={running || readyCount === 0}
          style={{
            background: running || readyCount === 0 ? '#1a3a2a' : '#065f46',
            color: '#6ee7b7', border: '1px solid #6ee7b7', borderRadius: '8px',
            padding: '0.45rem 0.9rem', fontSize: '0.85rem', fontWeight: 600,
            cursor: running || readyCount === 0 ? 'not-allowed' : 'pointer',
            opacity: running || readyCount === 0 ? 0.55 : 1, fontFamily: 'inherit',
          }}>
          {running ? '⏳ Agentes rodando…' : `▶ Disparar ${readyCount || ''} agente(s)`}
        </button>
        {running && (
          <button onClick={stopPolling}
            style={{ background: '#3a1a1a', color: '#f87171', border: '1px solid #f87171', borderRadius: '8px', padding: '0.45rem 0.9rem', fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
            ■ Parar de acompanhar
          </button>
        )}
      </div>
    </div>
  )
}
