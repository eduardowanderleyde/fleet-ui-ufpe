import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ConfigForm from './ConfigForm'

const cfg = {
  command: 'replay', robot: 'default', route: 'percurso_cbsoft', collect: true, topics: ['amcl_pose'],
  initial_pose: [1.022, 16.616, 0], points: [], return_to_start: [0, 0, 0], run_label: '',
}

describe('ConfigForm — replay', () => {
  it('lista os pontos da rota com a distância de cada trecho e o total', () => {
    render(<ConfigForm cfg={cfg} onChange={() => {}} routeNames={['percurso_cbsoft']} routesLoading={false}
      onRefreshRoutes={() => {}}
      routePoses={[[1.0216, 16.6163, 0], [-2.5491, -47.3437, 0], [-33.7169, -47.1188, 0]]} />)
    const list = screen.getByLabelText('Pontos da rota')
    expect(list).toHaveTextContent('início')
    expect(list).toHaveTextContent('+64.1 m')
    expect(list).toHaveTextContent('+31.2 m')
    expect(list).toHaveTextContent('total 95.2 m')
  })
})
