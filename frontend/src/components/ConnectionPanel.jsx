import { color, btn } from '../styles/tokens'

export const ROBOT_PROFILES = [
  { id: 'custom', label: 'Custom (simulação local)', type: 'local' },
  { id: 'tb3_1',  label: 'TurtleBot3 #1',           type: 'ssh', host: '192.168.1.101' },
  { id: 'tb3_2',  label: 'TurtleBot3 #2',           type: 'ssh', host: '192.168.1.102' },
]

const connLightColor = { idle: color.textFaint, connecting: color.warning, connected: color.success, error: color.danger }

export default function ConnectionPanel({
  containerRef, isOpen, onToggle,
  profiles, extraProfiles, selectedProfile, onSelectProfile,
  connStatus, connMsg, onConnect, onDisconnect,
}) {
  const connLight = connLightColor[connStatus]

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <button onClick={onToggle} aria-expanded={isOpen} aria-haspopup="true"
        style={{ ...btn(color.bgPanel, color.indigo), display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <span aria-hidden="true" style={{ width: 10, height: 10, borderRadius: '50%', background: connLight, display: 'inline-block', boxShadow: connStatus === 'connected' ? `0 0 6px ${connLight}` : 'none' }} />
        Conectar robô <span aria-hidden="true" style={{ fontSize: '0.7rem', opacity: 0.7 }}>{isOpen ? '▲' : '▼'}</span>
      </button>
      {isOpen && (
        <div style={{ position: 'absolute', top: '2.5rem', left: 0, zIndex: 100, background: color.bgPanel, border: `1px solid ${color.border}`, borderRadius: '10px', padding: '1rem', width: '320px', boxShadow: '0 8px 32px rgba(0,0,0,0.5)' }}>
          <div style={{ fontSize: '0.78rem', fontWeight: 600, color: color.textMuted, marginBottom: '0.75rem' }}>Selecionar robô</div>
          <div role="radiogroup" aria-label="Robô a conectar" style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '1rem' }}>
            {profiles.map(p => {
              const isSelected = selectedProfile === p.id
              const isExtra    = !!extraProfiles.find(ep => ep.id === p.id)
              return (
                <label key={p.id}
                  style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.5rem 0.85rem', borderRadius: '8px', border: `1px solid ${isSelected ? color.indigo : color.border}`, background: isSelected ? 'rgba(99,102,241,0.1)' : 'transparent', cursor: 'pointer' }}>
                  <input type="radio" name="rp" checked={isSelected} onChange={() => onSelectProfile(p.id)} style={{ accentColor: color.indigo, margin: 0 }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: '0.85rem', color: isSelected ? color.text : color.textMuted2, fontWeight: isSelected ? 600 : 400 }}>{p.label}</div>
                    <div style={{ fontSize: '0.72rem', color: color.textFaint, marginTop: '0.1rem' }}>
                      {isExtra ? `SSH ${p.host} · descoberto` : p.type === 'ssh' ? `SSH ${p.host} · em breve` : 'localhost:8000'}
                    </div>
                  </div>
                </label>
              )
            })}
          </div>
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            <button onClick={onConnect} disabled={connStatus === 'connecting'} style={{ ...btn(color.successDark, color.success), flex: 1 }}>
              {connStatus === 'connecting' ? '⏳ Conectando…' : 'Conectar'}
            </button>
            {connStatus === 'connected' && (
              <button onClick={onDisconnect} style={btn(color.dangerBg, color.danger)}>Desconectar</button>
            )}
          </div>
          {connMsg && <div role="status" style={{ marginTop: '0.6rem', fontSize: '0.78rem', color: connStatus === 'error' ? color.danger : color.success }}>{connMsg}</div>}
        </div>
      )}
    </div>
  )
}
