import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import MapView from './MapView'

// backend sempre offline nos testes: as rotas de mapa resolvem como
// "sem mapa disponível" pra não precisar simular uma imagem SLAM carregando.
vi.mock('../api/fleetApi', () => ({
  getMap:            vi.fn().mockResolvedValue({ available: false }),
  getSlamMapMeta:    vi.fn().mockResolvedValue({ available: false }),
  saveBackgroundMap: vi.fn(),
  listMaps:          vi.fn().mockResolvedValue({ maps: [] }),
  importMap:         vi.fn(),
}))

describe('MapView', () => {
  it('clicar no mapa chama onAddWaypoint com as coordenadas do clique', () => {
    const onAddWaypoint = vi.fn()
    render(<MapView robotId="tb1" poses={{}} waypoints={[]} onAddWaypoint={onAddWaypoint} />)

    const canvas = screen.getByRole('img', { name: /clique adiciona um waypoint/i })
    fireEvent.click(canvas, { clientX: 150, clientY: 120 })

    expect(onAddWaypoint).toHaveBeenCalledTimes(1)
    const [x, y] = onAddWaypoint.mock.calls[0]
    expect(typeof x).toBe('number')
    expect(typeof y).toBe('number')
  })

  // Esta é a regressão real: App.jsx já passou `onNavigateTo` (um no-op) no
  // lugar de `onAddWaypoint` pra MapView — o clique no mapa não fazia nada,
  // em silêncio, sem erro nenhum. useMapCanvas.onClick já trata esse caso
  // (`if (!onAddWaypoint) return`), então sem a prop o clique não deve
  // disparar nenhum callback.
  it('sem onAddWaypoint, clicar no mapa não quebra e não chama nada', () => {
    const onAddWaypoint = vi.fn()
    render(<MapView robotId="tb1" poses={{}} waypoints={[]} onAddWaypoint={undefined} />)

    const canvas = screen.getByRole('img')
    expect(() => fireEvent.click(canvas, { clientX: 150, clientY: 120 })).not.toThrow()
    expect(onAddWaypoint).not.toHaveBeenCalled()
  })
})
