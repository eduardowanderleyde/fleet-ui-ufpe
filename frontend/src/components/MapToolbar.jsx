import { useState } from 'react'
import { color } from '../styles/tokens'

export default function MapToolbar({
  showFloor, floorMismatch, onToggleFloor, savedMapMeta,
  floorOpacity, onFloorOpacityChange,
  mapOk, savingMap, saveMsg, onSave,
  onCenter, hoverCoord,
  mapName, setMapName, mapOptions, importingMap, importMsg, onImportMap,
}) {
  const [showImport, setShowImport] = useState(false)
  const [importName, setImportName] = useState('')
  const [importPath, setImportPath] = useState('')

  const submitImport = () => {
    if (!importName.trim() || !importPath.trim()) return
    onImportMap({ name: importName.trim(), yamlPath: importPath.trim() })
    setShowImport(false)
    setImportName(''); setImportPath('')
  }

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.5rem', flexShrink: 0,
                  background: color.bgPanel, borderRadius: '8px', padding: '0.4rem 0.7rem',
                  border: `1px solid ${color.border}` }}>

      {/* Clique no mapa → sempre adiciona waypoint */}
      <span style={{ fontSize: '0.72rem', color: color.textFaint, fontFamily: 'monospace' }}>
        clique = ＋waypoint
      </span>

      <div style={{ width: '1px', height: '20px', background: color.border, margin: '0 0.2rem' }} />

      {/* Centrar — disponível sempre */}
      <button onClick={onCenter}
        style={{ background: 'transparent', color: color.textFaint2, border: `1.5px solid ${color.border}`,
                 borderRadius: '6px', padding: '0.3rem 0.65rem', fontSize: '0.75rem',
                 fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
        ⊞ Centrar
      </button>

      {/* Planta / Salvar */}
      <button onClick={onToggleFloor} disabled={floorMismatch} aria-pressed={showFloor && !floorMismatch}
        title={floorMismatch ? 'A planta é de outro lugar: o mapa ao vivo não cabe nela.' : undefined}
        style={{ background: showFloor && !floorMismatch ? 'rgba(110,231,183,0.1)' : 'transparent',
                 color: showFloor && !floorMismatch ? color.success : color.textFaint2,
                 border: `1.5px solid ${showFloor && !floorMismatch ? color.success : color.border}`,
                 borderRadius: '6px', padding: '0.3rem 0.65rem', fontSize: '0.75rem',
                 fontWeight: 600, cursor: floorMismatch ? 'not-allowed' : 'pointer', fontFamily: 'inherit' }}>
        🏭 {savedMapMeta ? 'Planta' : 'Mapa'}{floorMismatch ? ' · outro mapa' : ''}
      </button>

      {mapOptions && (
        <select value={mapName} onChange={e => setMapName(e.target.value)}
          aria-label="Mapa de fundo"
          style={{ background: color.bgApp, color: color.textMuted2, border: `1.5px solid ${color.border}`,
                   borderRadius: '6px', padding: '0.28rem 0.4rem', fontSize: '0.75rem', fontFamily: 'inherit', cursor: 'pointer' }}>
          {mapOptions.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
      )}

      {onImportMap && (
        <button onClick={() => setShowImport(v => !v)}
          title="Importar mapa real (.yaml + .pgm)"
          style={{ background: 'transparent', color: color.indigo, border: `1.5px solid ${color.indigo}`,
                   borderRadius: '6px', padding: '0.3rem 0.5rem', fontSize: '0.75rem',
                   fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
          📥
        </button>
      )}

      {showImport && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
          <input value={importName} onChange={e => setImportName(e.target.value)} placeholder="nome (ex.: hall_cin_v4)"
            style={{ background: color.bgApp, border: `1px solid ${color.border}`, borderRadius: '5px',
                     color: color.text, padding: '0.25rem 0.45rem', fontSize: '0.72rem', width: '150px', fontFamily: 'inherit' }} />
          <input value={importPath} onChange={e => setImportPath(e.target.value)} placeholder="caminho do .yaml"
            style={{ background: color.bgApp, border: `1px solid ${color.border}`, borderRadius: '5px',
                     color: color.text, padding: '0.25rem 0.45rem', fontSize: '0.72rem', width: '220px', fontFamily: 'monospace' }} />
          <button onClick={submitImport} disabled={importingMap}
            style={{ background: 'transparent', color: color.success, border: `1.5px solid ${color.success}`,
                     borderRadius: '5px', padding: '0.25rem 0.55rem', fontSize: '0.72rem', fontWeight: 600,
                     cursor: importingMap ? 'not-allowed' : 'pointer', fontFamily: 'inherit' }}>
            {importingMap ? '⏳' : 'Importar'}
          </button>
        </div>
      )}

      {importMsg && (
        <span style={{ fontSize: '0.7rem', color: importMsg === 'ok' ? color.success : color.danger }}>
          {importMsg === 'ok' ? '✓ importado' : importMsg}
        </span>
      )}

      {showFloor && (
        <input type="range" min="0" max="1" step="0.05" value={floorOpacity}
          aria-label="Opacidade da planta de fundo"
          onChange={e => onFloorOpacityChange(parseFloat(e.target.value))}
          style={{ width: '56px', accentColor: color.success, cursor: 'pointer' }} />
      )}

      {mapOk && (
        <button onClick={onSave} disabled={savingMap}
          style={{ background: 'transparent',
                   color: saveMsg === 'ok' ? color.success : saveMsg === 'erro' ? color.danger : color.indigo,
                   border: `1.5px solid ${saveMsg === 'ok' ? color.success : saveMsg === 'erro' ? color.danger : color.indigo}`,
                   borderRadius: '6px', padding: '0.3rem 0.65rem', fontSize: '0.75rem',
                   fontWeight: 600, cursor: savingMap ? 'not-allowed' : 'pointer',
                   opacity: savingMap ? 0.6 : 1, fontFamily: 'inherit' }}>
          {savingMap ? '⏳' : saveMsg === 'ok' ? '✓ Salvo' : saveMsg === 'erro' ? '✗ Erro' : '💾 Salvar'}
        </button>
      )}

      {/* Coordenadas de hover */}
      <div style={{ marginLeft: 'auto', fontFamily: 'monospace', fontSize: '0.72rem',
                    color: hoverCoord ? color.blue : color.textFaint3, minWidth: '120px', textAlign: 'right' }}>
        {hoverCoord
          ? `x ${hoverCoord.x.toFixed(2)}  y ${hoverCoord.y.toFixed(2)}`
          : mapOk ? 'scroll=zoom  btn2=pan' : <span style={{ color: color.warning }}>⏳ aguardando SLAM…</span>
        }
      </div>
    </div>
  )
}
