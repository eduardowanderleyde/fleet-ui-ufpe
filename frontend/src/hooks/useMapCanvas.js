import { useState, useRef, useEffect, useCallback } from 'react'
import { getMap, getSlamMapMeta, saveBackgroundMap, listMaps, importMap } from '../api/fleetApi'

// Mapa pré-construído do warehouse (turtlebot4_navigation/maps/warehouse.pgm)
// Metadados exactos do warehouse.yaml — alinhamento perfeito com o mundo Gazebo
export const WAREHOUSE_MAP = {
  resolution: 0.03,
  origin_x:   -15.1,
  origin_y:   -25.0,
  width:       1006,
  height:      1674,
  src:         '/warehouse_map.png',
}

export const HOUSE_WORLD = { x0: -5.0, y0: -5.0, x1: 7.0, y1: 7.0 }

const OTHER_ROBOT_COLORS = ['#93c5fd', '#fbbf24', '#f472b6', '#a78bfa', '#5eead4']

// Folga pro mapa SLAM, que costuma enxergar um pouco além das paredes da planta.
const FLOOR_FIT_MARGIN_M = 5

// A planta só faz sentido sobre um mapa ao vivo do mesmo lugar: se o mapa ao
// vivo não cabe na área da planta, é outro mundo (ex.: cbsoft_open) e
// desenhar a planta por cima só confunde.
function floorFitsLive(plan, live) {
  if (!plan || !live) return true
  const bounds = m => [m.origin_x, m.origin_y, m.origin_x + m.width * m.resolution, m.origin_y + m.height * m.resolution]
  const [px0, py0, px1, py1] = bounds(plan)
  const [lx0, ly0, lx1, ly1] = bounds(live)
  return lx0 >= px0 - FLOOR_FIT_MARGIN_M && ly0 >= py0 - FLOOR_FIT_MARGIN_M
      && lx1 <= px1 + FLOOR_FIT_MARGIN_M && ly1 <= py1 + FLOOR_FIT_MARGIN_M
}

// Folga ao checar se um ponto da rota cai dentro da área conhecida.
const ROUTE_FIT_MARGIN_M = 1

function mapBounds(m) {
  return [m.origin_x, m.origin_y, m.origin_x + m.width * m.resolution, m.origin_y + m.height * m.resolution]
}

// Quantos pontos da rota caem fora da área conhecida (mapa ao vivo, mais a
// planta quando ela é do mesmo lugar). null = ainda não há mapa pra comparar.
// Pega rota de outro mundo (ex.: percurso_cbsoft com o armazém aberto), que
// mandaria o robô pra fora do mapa.
function countOutside(points, live, plan) {
  const refs = [live, plan].filter(Boolean).map(mapBounds)
  if (!refs.length) return null
  const inside = ([x, y]) => refs.some(([x0, y0, x1, y1]) =>
    x >= x0 - ROUTE_FIT_MARGIN_M && x <= x1 + ROUTE_FIT_MARGIN_M &&
    y >= y0 - ROUTE_FIT_MARGIN_M && y <= y1 + ROUTE_FIT_MARGIN_M)
  return points.filter(p => !inside(p)).length
}

// Toda a lógica imperativa do mapa (desenho em canvas, carga de imagens,
// zoom/pan, conversão de coordenadas) — separada de MapView pra deixar o
// componente só com composição/JSX. Devolve refs + estado + handlers.
export function useMapCanvas({ robotId, poses, waypoints, onRouteOutsideChange }) {
  const canvasRef    = useRef(null)
  const imgRef       = useRef(null)   // SLAM PNG
  const floorImgRef  = useRef(null)   // Planta estática
  const mapMeta      = useRef(null)
  const scaleRef     = useRef(1)
  const panRef       = useRef({ x: 0, y: 0 })
  const dragRef      = useRef(null)

  const [mapOk, setMapOk]               = useState(false)
  const [showFloor, setShowFloor]       = useState(true)
  const [floorMismatch, setFloorMismatch] = useState(false)
  const floorMismatchRef = useRef(false)
  const routeOutsideRef = useRef(undefined)
  const onRouteOutsideRef = useRef(onRouteOutsideChange)
  onRouteOutsideRef.current = onRouteOutsideChange
  const [floorOpacity, setFloorOpacity] = useState(0.55)
  const [savedMapMeta, setSavedMapMeta] = useState(null)
  const [savingMap, setSavingMap]       = useState(false)
  const [saveMsg, setSaveMsg]           = useState(null)
  const [mapName, setMapName]           = useState('slam')   // 'slam' | 'warehouse' | nome importado
  const [mapOptions, setMapOptions]     = useState(['warehouse'])
  const [importingMap, setImportingMap] = useState(false)
  const [importMsg, setImportMsg]       = useState(null)
  const [hoverCoord, setHoverCoord]     = useState(null)  // {x, y} em coords mundo
  const [floorOffset] = useState({ x: HOUSE_WORLD.x0, y: HOUSE_WORLD.y0 })
  const [floorScale]  = useState(HOUSE_WORLD.x1 - HOUSE_WORLD.x0)

  // Usa SLAM se disponível, senão usa o mapa estático do warehouse
  const activeMap = useCallback(() => mapMeta.current || WAREHOUSE_MAP, [])

  // Converte coords mundo → canvas
  const worldToCanvas = useCallback((wx, wy) => {
    const m = activeMap()
    const px = (wx - m.origin_x) / m.resolution
    const py = m.height - (wy - m.origin_y) / m.resolution
    return {
      x: px * scaleRef.current + panRef.current.x,
      y: py * scaleRef.current + panRef.current.y,
    }
  }, [activeMap])

  // Converte canvas → coords mundo
  const canvasToWorld = useCallback((cx, cy) => {
    const m = activeMap()
    const px = (cx - panRef.current.x) / scaleRef.current
    const py = (cy - panRef.current.y) / scaleRef.current
    return {
      x: parseFloat((m.origin_x + px * m.resolution).toFixed(3)),
      y: parseFloat((m.origin_y + (m.height - py) * m.resolution).toFixed(3)),
    }
  }, [activeMap])

  // Desenha tudo no canvas
  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width, H = canvas.height
    ctx.clearRect(0, 0, W, H)

    // ── Fundo com grid pontilhada ─────────────────────────────────────────────
    ctx.fillStyle = '#0f1117'
    ctx.fillRect(0, 0, W, H)
    ctx.fillStyle = 'rgba(255,255,255,0.04)'
    const gridStep = 24
    for (let gx = 0; gx < W; gx += gridStep)
      for (let gy = 0; gy < H; gy += gridStep) {
        ctx.beginPath(); ctx.arc(gx, gy, 0.8, 0, Math.PI * 2); ctx.fill()
      }

    const m = activeMap()  // SLAM ou WAREHOUSE_MAP

    const mismatch = !floorFitsLive(savedMapMeta, mapMeta.current)
    if (mismatch !== floorMismatchRef.current) {
      floorMismatchRef.current = mismatch
      setFloorMismatch(mismatch)
    }
    const drawFloor = showFloor && !mismatch

    const outside = countOutside(waypoints, mapMeta.current, mismatch ? null : savedMapMeta)
    if (outside !== routeOutsideRef.current) {
      routeOutsideRef.current = outside
      onRouteOutsideRef.current?.(outside)
    }

    // ── Planta de fundo (warehouse ou slam_map guardado) ──────────────────────
    if (drawFloor && floorImgRef.current?.complete) {
      const fi = floorImgRef.current
      ctx.globalAlpha = floorOpacity
      ctx.imageSmoothingEnabled = true
      if (savedMapMeta) {
        // Alinhamento via metadados: usa o sistema de coordenadas activo
        const sm = savedMapMeta
        const mapW_world = sm.width  * sm.resolution
        const mapH_world = sm.height * sm.resolution
        const cx0 = (sm.origin_x - m.origin_x) / m.resolution * scaleRef.current + panRef.current.x
        const cy0 = ((m.height) - (sm.origin_y - m.origin_y) / m.resolution - mapH_world / m.resolution) * scaleRef.current + panRef.current.y
        const cw  = mapW_world / m.resolution * scaleRef.current
        const ch  = mapH_world / m.resolution * scaleRef.current
        ctx.drawImage(fi, cx0, cy0, cw, ch)
      } else {
        const s = Math.min(W / fi.naturalWidth, H / fi.naturalHeight) * 0.88
        ctx.drawImage(fi, (W - fi.naturalWidth * s) / 2, (H - fi.naturalHeight * s) / 2,
                      fi.naturalWidth * s, fi.naturalHeight * s)
      }
      ctx.globalAlpha = 1
    }

    // ── Mapa SLAM ao vivo (sobreposto ao fundo) ───────────────────────────────
    if (mapMeta.current && imgRef.current?.complete) {
      ctx.imageSmoothingEnabled = false
      ctx.globalAlpha = drawFloor ? 0.82 : 1
      ctx.drawImage(imgRef.current,
        panRef.current.x, panRef.current.y,
        mapMeta.current.width * scaleRef.current,
        mapMeta.current.height * scaleRef.current)
      ctx.globalAlpha = 1
    }

    if (!mapMeta.current && (!showFloor || !floorImgRef.current?.complete)) {
      ctx.fillStyle = '#6b7280'
      ctx.font = '13px system-ui'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText('⏳ Aguardando mapa SLAM…', W / 2, H / 2)
    }

    // ── Linha de percurso entre waypoints ─────────────────────────────────────
    const wps = waypoints.map(wp => worldToCanvas(wp[0], wp[1])).filter(Boolean)
    if (wps.length > 1) {
      ctx.beginPath()
      ctx.moveTo(wps[0].x, wps[0].y)
      wps.slice(1).forEach(c => ctx.lineTo(c.x, c.y))
      ctx.strokeStyle = 'rgba(99,102,241,0.4)'
      ctx.lineWidth = 2
      ctx.setLineDash([6, 4])
      ctx.stroke()
      ctx.setLineDash([])
    }

    // ── Waypoints ─────────────────────────────────────────────────────────────
    wps.forEach((c, i) => {
      // Halo exterior
      ctx.beginPath()
      ctx.arc(c.x, c.y, 13, 0, Math.PI * 2)
      ctx.fillStyle = 'rgba(99,102,241,0.18)'
      ctx.fill()
      // Círculo principal
      ctx.beginPath()
      ctx.arc(c.x, c.y, 9, 0, Math.PI * 2)
      ctx.fillStyle = '#6366f1'
      ctx.fill()
      ctx.strokeStyle = '#a5b4fc'
      ctx.lineWidth = 1.5
      ctx.stroke()
      // Número
      ctx.fillStyle = '#fff'
      ctx.font = 'bold 9px monospace'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillText(String(i + 1), c.x, c.y)
    })

    // ── Robôs (todos os poses conhecidos; o selecionado no dropdown se
    //    destaca em verde com anel/seta maior — os demais ficam num tom
    //    próprio + rótulo com o id, pra dar pra distinguir tb1/tb2/tb3 no
    //    mesmo mapa) ────────────────────────────────────────────────────
    Object.entries(poses || {}).forEach(([rid, p], i) => {
      if (!p?.valid) return
      const c = worldToCanvas(p.x, p.y)
      if (!c) return
      const isActive = rid === robotId
      const color = isActive ? '#6ee7b7' : OTHER_ROBOT_COLORS[i % OTHER_ROBOT_COLORS.length]

      ctx.save()
      ctx.translate(c.x, c.y)
      ctx.rotate(-p.yaw)
      if (isActive) {
        // Anel exterior pulsante — só no robô selecionado, pra não poluir com vários
        ctx.beginPath()
        ctx.arc(0, 0, 18, 0, Math.PI * 2)
        ctx.fillStyle = 'rgba(110,231,183,0.12)'
        ctx.fill()
        ctx.strokeStyle = 'rgba(110,231,183,0.35)'
        ctx.lineWidth = 1.5
        ctx.stroke()
      }
      // Corpo
      const radius = isActive ? 11 : 8
      ctx.shadowColor = color
      ctx.shadowBlur = isActive ? 14 : 6
      ctx.beginPath()
      ctx.arc(0, 0, radius, 0, Math.PI * 2)
      ctx.fillStyle = isActive ? '#065f46' : '#111827'
      ctx.fill()
      ctx.strokeStyle = color
      ctx.lineWidth = 2
      ctx.stroke()
      ctx.shadowBlur = 0
      // Seta de direção
      const tip = isActive ? 14 : 10
      ctx.beginPath()
      ctx.moveTo(tip, 0)
      ctx.lineTo(-tip * 0.36, -5.5)
      ctx.lineTo(-tip * 0.36, 5.5)
      ctx.closePath()
      ctx.fillStyle = color
      ctx.fill()
      ctx.restore()

      // Rótulo com o robot_id (sem rotação, sempre legível)
      ctx.fillStyle = color
      ctx.font = isActive ? 'bold 11px monospace' : '10px monospace'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'bottom'
      ctx.fillText(rid, c.x, c.y - radius - 6)
    })

    // ── Barra de escala ───────────────────────────────────────────────────────
    if (mapMeta.current) {
      const m = mapMeta.current
      const metersPerPixel = m.resolution / scaleRef.current
      // Escolhe um valor "bonito" para a escala
      const targets = [0.1, 0.25, 0.5, 1, 2, 5, 10]
      const targetPx = 80
      const target = targets.reduce((best, t) =>
        Math.abs(t / metersPerPixel - targetPx) < Math.abs(best / metersPerPixel - targetPx) ? t : best
      , targets[0])
      const barPx = target / metersPerPixel
      const bx = 16, by = H - 22
      ctx.fillStyle = 'rgba(0,0,0,0.5)'
      ctx.fillRect(bx - 4, by - 10, barPx + 8, 18)
      ctx.strokeStyle = '#6ee7b7'
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(bx, by); ctx.lineTo(bx + barPx, by)
      ctx.moveTo(bx, by - 4); ctx.lineTo(bx, by + 4)
      ctx.moveTo(bx + barPx, by - 4); ctx.lineTo(bx + barPx, by + 4)
      ctx.stroke()
      ctx.fillStyle = '#6ee7b7'
      ctx.font = '10px monospace'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'bottom'
      ctx.fillText(`${target < 1 ? target * 100 + 'cm' : target + 'm'}`, bx + barPx / 2, by - 3)
    }
  }, [poses, robotId, waypoints, worldToCanvas, activeMap, showFloor, floorOpacity, floorOffset, floorScale, savedMapMeta])

  // Lista mapas disponíveis (warehouse sempre presente + o que o backend
  // tiver salvo: 'slam' se já rodou SLAM, ou qualquer mapa importado via
  // /api/import_map — ex.: o hall_cin_v4 do CIn).
  useEffect(() => {
    listMaps()
      .then(d => setMapOptions(['warehouse', ...(d.maps || []).filter(n => n !== 'warehouse')]))
      .catch(() => {})
  }, [])

  // Carrega fundo pelo mapName actual: 'warehouse' usa o PNG pré-construído
  // direto; qualquer outro nome busca os metadados salvos no backend
  // (slam_map.json ou <nome>_map.json) e cai pro warehouse se não existir.
  useEffect(() => {
    const loadWarehouse = () => {
      const img = new Image()
      img.src = WAREHOUSE_MAP.src + '?t=' + Date.now()
      img.onload = () => {
        floorImgRef.current = img
        setSavedMapMeta(WAREHOUSE_MAP)
        fitMap()
        draw()
      }
    }
    if (mapName === 'warehouse') { loadWarehouse(); return }

    const prefix = mapName === 'slam' ? 'slam_map' : `${mapName}_map`
    getSlamMapMeta(mapName)
      .then(d => {
        if (!d.available) { loadWarehouse(); return }
        const img = new Image()
        img.src = `/${prefix}.png?t=` + Date.now()
        img.onload = () => {
          floorImgRef.current = img
          setSavedMapMeta(d)
          fitMap()
          draw()
        }
      })
      .catch(loadWarehouse)
    // Só [mapName]: draw muda de identidade a cada poll de status/pose (não
    // tem nada a ver com qual mapa está selecionado) — depender de draw
    // aqui faz o efeito recarregar o fundo (fetch + decode de imagem) a
    // cada ~300ms pra sempre, num loop que nunca estabiliza porque poses é
    // recriado a cada resposta de /api/status. draw() já é chamado
    // manualmente nos callbacks acima pra repintar depois do load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapName])

  const doImportMap = async ({ name, yamlPath }) => {
    setImportingMap(true); setImportMsg(null)
    try {
      const d = await importMap({ name, yamlPath })
      setImportMsg(d.success ? 'ok' : (d.message || 'erro'))
      if (d.success) {
        const d2 = await listMaps()
        setMapOptions(['warehouse', ...(d2.maps || []).filter(n => n !== 'warehouse')])
        setMapName(name)
      }
    } catch (e) { setImportMsg(e.message || 'erro') }
    finally { setImportingMap(false); setTimeout(() => setImportMsg(null), 5000) }
  }

  // Busca mapa periodicamente (do robô selecionado — cada robô tem seu
  // próprio SLAM, não um mapa global). Troca de robô limpa o mapa anterior
  // na hora: cada um roda SLAM independente, então a pose de um nunca faz
  // sentido sobre o mapa do outro, nem por um instante.
  useEffect(() => {
    mapMeta.current = null
    imgRef.current = null
    setMapOk(false)
  }, [robotId])

  useEffect(() => {
    let alive = true
    const fetchMap = async () => {
      try {
        const data = await getMap(robotId)
        if (!alive || !data.available) return
        mapMeta.current = {
          resolution: data.resolution,
          origin_x:   data.origin_x,
          origin_y:   data.origin_y,
          width:       data.width,
          height:      data.height,
        }
        if (!imgRef.current) imgRef.current = new Image()
        const dataUrl = `data:image/png;base64,${data.png_b64}`
        if (imgRef.current.src !== dataUrl) {
          imgRef.current.src = dataUrl
          imgRef.current.onload = () => {
            fitMap()
            setMapOk(true)
            draw()
          }
        } else {
          draw()
        }
      } catch { /* backend offline */ }
    }
    fetchMap()
    const t = setInterval(fetchMap, 1500)
    return () => { alive = false; clearInterval(t) }
  }, [draw, robotId])

  // Redesenha quando pose ou waypoints mudam
  useEffect(() => { draw() }, [draw, poses, robotId, waypoints])

  // Ajusta escala/pan para caber o mapa activo (SLAM ou warehouse estático)
  const fitMap = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const m = activeMap()
    const W = canvas.width  || canvas.offsetWidth  || 600
    const H = canvas.height || canvas.offsetHeight || 500
    if (!W || !H) return
    const s = Math.min(W / m.width, H / m.height) * 0.95
    scaleRef.current = s
    panRef.current   = { x: (W - m.width * s) / 2, y: (H - m.height * s) / 2 }
  }, [activeMap])

  // Redimensiona canvas ao container e re-centra o mapa
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ro = new ResizeObserver(() => {
      canvas.width  = canvas.offsetWidth
      canvas.height = canvas.offsetHeight
      if (mapMeta.current) fitMap()
      draw()
    })
    // Inicializa dimensões imediatamente
    canvas.width  = canvas.offsetWidth  || 600
    canvas.height = canvas.offsetHeight || 500
    ro.observe(canvas)
    return () => ro.disconnect()
  }, [draw, fitMap])

  // Zoom com scroll
  const onWheel = useCallback(e => {
    e.preventDefault()
    const canvas = canvasRef.current
    const rect   = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15
    const newScale = Math.max(0.04, Math.min(scaleRef.current * factor, 80))
    panRef.current = {
      x: mx - (mx - panRef.current.x) * (newScale / scaleRef.current),
      y: my - (my - panRef.current.y) * (newScale / scaleRef.current),
    }
    scaleRef.current = newScale
    draw()
  }, [draw])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.addEventListener('wheel', onWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', onWheel)
  }, [onWheel])

  // Pan com botão direito ou middle
  const onMouseDown = e => {
    if (e.button === 1 || e.button === 2 || e.altKey) {
      dragRef.current = { x: e.clientX - panRef.current.x, y: e.clientY - panRef.current.y }
      e.preventDefault()
    }
  }
  const onMouseMove = (e, onHover) => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (rect) {
      const w = canvasToWorld(e.clientX - rect.left, e.clientY - rect.top)
      setHoverCoord(w)
    }
    if (!dragRef.current) return
    panRef.current = { x: e.clientX - dragRef.current.x, y: e.clientY - dragRef.current.y }
    draw()
  }
  const onMouseLeave = () => { dragRef.current = null; setHoverCoord(null) }
  const onMouseUp    = () => { dragRef.current = null }

  // Clique → calcula coords mundo (quem decide se vira waypoint é MapView,
  // via onAddWaypoint — esse hook só traduz canvas→mundo e ignora cliques
  // que façam parte de um arrasto).
  const onClick = (e, onAddWaypoint) => {
    if (dragRef.current || !onAddWaypoint) return
    const rect = canvasRef.current.getBoundingClientRect()
    const world = canvasToWorld(e.clientX - rect.left, e.clientY - rect.top)
    if (!world) return
    onAddWaypoint(world.x, world.y)
  }

  const saveBackground = async () => {
    setSavingMap(true); setSaveMsg(null)
    try {
      const d = await saveBackgroundMap()
      setSaveMsg(d.success ? 'ok' : 'erro')
      if (d.success) {
        setMapOptions(prev => prev.includes('slam') ? prev : [...prev, 'slam'])
        if (mapName === 'slam') {
          const img = new Image()
          img.src = '/slam_map.png?t=' + Date.now()
          img.onload = () => {
            floorImgRef.current = img
            getSlamMapMeta('slam').then(d => {
              if (d.available) setSavedMapMeta(d); draw()
            })
          }
        } else {
          setMapName('slam')
        }
      }
    } catch { setSaveMsg('erro') }
    finally { setSavingMap(false); setTimeout(() => setSaveMsg(null), 4000) }
  }

  return {
    canvasRef,
    mapOk, showFloor, setShowFloor, floorMismatch, floorOpacity, setFloorOpacity,
    savedMapMeta, savingMap, saveMsg, hoverCoord,
    mapName, setMapName, mapOptions, importingMap, importMsg, importMap: doImportMap,
    fitMap, draw, saveBackground,
    onWheelBound: onWheel,
    onMouseDown, onMouseMove, onMouseLeave, onMouseUp, onClick,
  }
}
