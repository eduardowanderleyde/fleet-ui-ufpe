import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const FIXTURES = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures')
const fixture = name => JSON.parse(readFileSync(path.join(FIXTURES, `${name}.json`), 'utf8'))

export const JOB_ID = 'e2e00001'

// Respostas gravadas de GET /api/<caminho> no backend real (stack CBSoft).
const GET_FIXTURES = {
  '/api/list_maps': 'list_maps',
  '/api/slam_map_meta': 'slam_map_meta',
  '/api/status': 'status',
  '/api/route_poses': 'route_poses_name_percurso_cbsoft',
  '/api/simulation/options': 'simulation_options',
  '/api/simulation/status': 'simulation_status',
  '/api/runs': 'runs_limit_50',
  '/api/list_routes': 'list_routes',
  '/api/map': 'map',
}

// Intercepta toda chamada /api/**. `overrides` troca a resposta de um caminho:
// { '/api/route_poses': {...} } devolve esse JSON; uma função recebe a route.
export async function mockApi(page, overrides = {}) {
  const calls = { runConfig: [], jobPolls: 0 }
  const jobDone = fixture('job_done')

  // Só caminhos que começam em /api/: um glob '**/api/**' também pegaria o
  // módulo /src/api/fleetApi.js servido pelo Vite e quebraria a página.
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const url = new URL(route.request().url())
    const p = url.pathname
    const override = overrides[p]
    if (typeof override === 'function') return override(route)
    if (override !== undefined) return route.fulfill({ json: override })

    if (p === '/api/run_config' && route.request().method() === 'POST') {
      calls.runConfig.push(route.request().postDataJSON())
      return route.fulfill({ json: { job_id: JOB_ID } })
    }
    if (p === `/api/job/${JOB_ID}`) {
      calls.jobPolls += 1
      // Primeira consulta: ainda rodando; depois, o job real terminado.
      if (calls.jobPolls === 1) return route.fulfill({ json: { ...jobDone, running: true, result: null, exit_code: null } })
      return route.fulfill({ json: jobDone })
    }
    const name = GET_FIXTURES[p]
    if (name) return route.fulfill({ json: fixture(name) })
    return route.fulfill({ status: 404, json: { detail: `sem mock para ${p}` } })
  })
  return calls
}
