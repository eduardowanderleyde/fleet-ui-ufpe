import { color, btn } from '../styles/tokens'

// Mesmas chaves/rótulos do card de métricas em App.jsx — reaproveitado aqui
// pra lista e comparação lado a lado renderizarem os mesmos nomes.
const METRIC_LABELS = [
  ['wall_duration_s', 'Duração', s => `${s} s`],
  ['odom_path_length_m', 'Percurso', s => `${s} m`],
  ['odom_avg_speed_ms', 'Vel. média', s => `${s} m/s`],
  ['scan_avg_valid_points', 'Scan pts', s => `${s}`],
  ['imu_accel_mean_ms2', 'IMU accel', s => `${s} m/s²`],
  ['ble_rssi_mean_dbm', 'BLE RSSI', (s, m) => `${s} dBm (${m.ble_rssi_min_dbm}…${m.ble_rssi_max_dbm}, n=${m.ble_rssi_n})`],
]

function fmtTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function RunCard({ run, selected, onToggleSelect }) {
  const m = run.result?.bag_metrics || {}
  const ok = run.error == null && run.exit_code === 0
  const statusColor = run.error ? color.danger : ok ? color.success : color.warning
  return (
    <label style={{
      display: 'flex', gap: '0.5rem', alignItems: 'flex-start', cursor: 'pointer',
      background: selected ? 'rgba(99,102,241,0.12)' : color.bgApp,
      border: `1px solid ${selected ? color.indigo : color.border}`,
      borderRadius: '8px', padding: '0.5rem 0.65rem',
    }}>
      <input type="checkbox" checked={selected} onChange={() => onToggleSelect(run.job_id)}
        style={{ accentColor: color.indigo, marginTop: '0.15rem', flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem', alignItems: 'baseline' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: color.text, fontFamily: 'monospace' }}>
            {run.command === 'replay' ? '▶' : '●'} {run.route || run.job_id}
          </span>
          <span style={{ fontSize: '0.68rem', color: color.textFaint, flexShrink: 0 }}>{fmtTime(run.timestamp)}</span>
        </div>
        <div style={{ fontSize: '0.7rem', color: color.textMuted, marginTop: '0.1rem' }}>
          robô: {run.robot || 'default'}{run.run_label && <> · <span style={{ color: color.brand }}>{run.run_label}</span></>}
          {' · '}<span style={{ color: statusColor }}>{run.error ? 'erro' : ok ? 'ok' : `exit ${run.exit_code}`}</span>
        </div>
        {Object.keys(m).length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem', marginTop: '0.35rem' }}>
            {METRIC_LABELS.filter(([k]) => m[k] != null).map(([k, label, fmt]) => (
              <span key={k} style={{ fontSize: '0.68rem', fontFamily: 'monospace', color: color.textMuted2,
                background: color.bgPanel, border: `1px solid ${color.borderDark}`, borderRadius: '4px', padding: '0.1rem 0.4rem' }}>
                {label}: {fmt(m[k], m)}
              </span>
            ))}
          </div>
        )}
      </div>
    </label>
  )
}

function CompareTable({ runs }) {
  const keys = METRIC_LABELS.filter(([k]) => runs.some(r => r.result?.bag_metrics?.[k] != null))
  return (
    <div style={{ background: color.bgApp, border: `1px solid ${color.border}`, borderRadius: '8px', padding: '0.6rem', marginTop: '0.75rem' }}>
      <div style={{ fontSize: '0.72rem', fontWeight: 600, color: color.textMuted, marginBottom: '0.5rem' }}>Comparação</div>
      <table style={{ width: '100%', fontSize: '0.74rem', fontFamily: 'monospace', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left', color: color.textFaint, fontWeight: 400, paddingBottom: '0.3rem' }}>métrica</th>
            {runs.map(r => (
              <th key={r.job_id} style={{ textAlign: 'right', color: color.text, fontWeight: 600, paddingBottom: '0.3rem' }}>
                {r.route || r.job_id}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map(([k, label, fmt]) => (
            <tr key={k} style={{ borderTop: `1px solid ${color.borderDark}` }}>
              <td style={{ color: color.textMuted2, padding: '0.25rem 0' }}>{label}</td>
              {runs.map(r => {
                const m = r.result?.bag_metrics || {}
                return (
                  <td key={r.job_id} style={{ textAlign: 'right', color: color.text, padding: '0.25rem 0' }}>
                    {m[k] != null ? fmt(m[k], m) : '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function RunHistoryPanel({ containerRef, isOpen, onToggle, history }) {
  const { runs, loading, error, refresh, selected, toggleSelect } = history
  const selectedRuns = selected.map(id => runs.find(r => r.job_id === id)).filter(Boolean)

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <button onClick={onToggle} aria-expanded={isOpen} aria-haspopup="true"
        style={{ ...btn(color.bgPanel, color.blue2), display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        📊 Execuções <span aria-hidden="true" style={{ fontSize: '0.7rem', opacity: 0.7 }}>{isOpen ? '▲' : '▼'}</span>
      </button>
      {isOpen && (
        <div style={{ position: 'absolute', top: '2.5rem', left: 0, zIndex: 100, background: color.bgPanel, border: `1px solid ${color.border}`, borderRadius: '10px', padding: '1rem', width: '460px', maxHeight: '70vh', overflowY: 'auto', boxShadow: '0 8px 32px rgba(0,0,0,0.5)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
            <span style={{ fontSize: '0.78rem', fontWeight: 600, color: color.textMuted }}>
              Histórico de execuções {selected.length > 0 && <span style={{ color: color.indigo }}>({selected.length}/2 selecionadas)</span>}
            </span>
            <button onClick={refresh} disabled={loading}
              style={{ background: 'none', border: 'none', color: loading ? color.textFaint : color.blue2, cursor: loading ? 'not-allowed' : 'pointer', fontSize: '0.72rem', padding: 0 }}>
              {loading ? 'carregando…' : '🔄 atualizar'}
            </button>
          </div>

          {error && <div role="alert" style={{ color: color.danger, fontSize: '0.78rem', marginBottom: '0.5rem' }}>{error}</div>}
          {!loading && runs.length === 0 && !error && (
            <div style={{ fontSize: '0.78rem', color: color.textFaint }}>Nenhuma execução registrada ainda — rode um record ou replay.</div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            {runs.map(run => (
              <RunCard key={run.job_id} run={run} selected={selected.includes(run.job_id)} onToggleSelect={toggleSelect} />
            ))}
          </div>

          {selectedRuns.length === 2 && <CompareTable runs={selectedRuns} />}
        </div>
      )}
    </div>
  )
}
