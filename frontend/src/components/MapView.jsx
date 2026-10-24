import { useMapCanvas } from '../hooks/useMapCanvas'
import MapToolbar from './MapToolbar'
import { color } from '../styles/tokens'

export default function MapView({ robotId, poses, waypoints, onAddWaypoint, onRouteOutsideChange }) {
  const map = useMapCanvas({ robotId, poses, waypoints, onRouteOutsideChange })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '0.5rem' }}>
      <MapToolbar
        showFloor={map.showFloor}
        floorMismatch={map.floorMismatch}
        onToggleFloor={() => map.setShowFloor(v => !v)}
        savedMapMeta={map.savedMapMeta}
        floorOpacity={map.floorOpacity}
        onFloorOpacityChange={v => { map.setFloorOpacity(v); map.draw() }}
        mapOk={map.mapOk}
        savingMap={map.savingMap}
        saveMsg={map.saveMsg}
        onSave={map.saveBackground}
        onCenter={() => { map.fitMap(); map.draw() }}
        hoverCoord={map.hoverCoord}
        mapName={map.mapName}
        setMapName={map.setMapName}
        mapOptions={map.mapOptions}
        importingMap={map.importingMap}
        importMsg={map.importMsg}
        onImportMap={map.importMap}
      />

      {/* Interação é mouse-only (clique adiciona waypoint, scroll dá zoom,
          botão direito arrasta) — sem equivalente por teclado hoje. Gap de
          acessibilidade real, não resolvido aqui: precisaria de um modo
          alternativo (ex.: campo x/y + botão "adicionar") pra quem não usa
          mouse, o que é mudança de interação, não só de marcação. O
          ConfigForm já tem um "+ Waypoint" acessível por teclado que cobre
          parte do caso (adicionar ponto editável), mas não o fluxo
          espacial de apontar no mapa. */}
      <canvas
        ref={map.canvasRef}
        role="img"
        aria-label={`Mapa ao vivo do robô ${robotId}${onAddWaypoint ? '. Clique adiciona um waypoint na rota.' : '.'}`}
        onClick={e => map.onClick(e, onAddWaypoint)}
        onMouseDown={map.onMouseDown}
        onMouseMove={map.onMouseMove}
        onMouseUp={map.onMouseUp}
        onMouseLeave={map.onMouseLeave}
        onContextMenu={e => e.preventDefault()}
        style={{
          flex: 1,
          width: '100%',
          borderRadius: '10px',
          border: `1px solid ${color.borderDark}`,
          boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
          cursor: 'cell',
          display: 'block',
        }}
      />
    </div>
  )
}
