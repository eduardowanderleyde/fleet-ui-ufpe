const API_BASE = '/api'

export function apiPath(path) {
  return `${API_BASE}${path}`
}

async function readJson(response) {
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    const message = data?.message || data?.error || `HTTP ${response.status}`
    throw new Error(message)
  }
  return data
}

export async function getStatus(options = {}) {
  return readJson(await fetch(apiPath('/status'), options))
}

export async function getJob(jobId) {
  return readJson(await fetch(apiPath(`/job/${jobId}`)))
}

export async function runConfig(config) {
  return readJson(await fetch(apiPath('/run_config'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  }))
}

export async function getMap(robotId = '') {
  const params = new URLSearchParams()
  if (robotId && robotId !== 'default') params.set('robot_id', robotId)
  const qs = params.toString()
  return readJson(await fetch(apiPath(`/map${qs ? `?${qs}` : ''}`)))
}

export async function getSlamMapMeta(name = 'slam') {
  const qs = name && name !== 'slam' ? `?name=${encodeURIComponent(name)}` : ''
  return readJson(await fetch(apiPath(`/slam_map_meta${qs}`)))
}

export async function saveBackgroundMap() {
  return readJson(await fetch(apiPath('/save_background_map'), { method: 'POST' }))
}

export async function listMaps() {
  return readJson(await fetch(apiPath('/list_maps')))
}

export async function importMap({ name, yamlPath }) {
  return readJson(await fetch(apiPath('/import_map'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, yaml_path: yamlPath }),
  }))
}

export async function listRunHistory(limit = 50) {
  return readJson(await fetch(apiPath(`/runs?limit=${limit}`)))
}

export async function getRoutePoses(name, robotId = '') {
  const params = new URLSearchParams({ name })
  if (robotId && robotId !== 'default') params.set('robot_id', robotId)
  return readJson(await fetch(apiPath(`/route_poses?${params}`)))
}

export async function listRoutes(robotId = '') {
  const params = new URLSearchParams()
  if (robotId && robotId !== 'default') params.set('robot_id', robotId)
  const qs = params.toString()
  return readJson(await fetch(apiPath(`/list_routes${qs ? `?${qs}` : ''}`)))
}

export async function stopJob(jobId) {
  return readJson(await fetch(apiPath(`/job/${jobId}/stop`), { method: 'POST' }))
}

export async function goToPoint({ robotId = '', x = 0, y = 0, yaw = 0 }) {
  const params = new URLSearchParams({
    robot_id: robotId === 'default' ? '' : robotId,
    x,
    y,
    yaw,
  })
  return readJson(await fetch(apiPath(`/go_to_point?${params.toString()}`), { method: 'POST' }))
}

export async function discoverRobots({ subnet = '', signal } = {}) {
  const path = subnet.trim()
    ? `/discover_robots?subnet=${encodeURIComponent(subnet.trim())}`
    : '/discover_robots'
  return readJson(await fetch(apiPath(path), { signal }))
}

export async function testSsh({ host, user = 'ubuntu', port = 22 }) {
  return readJson(await fetch(apiPath('/test_ssh'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ host, user, port }),
  }))
}

export async function runAgentFleet(instructions, model) {
  return readJson(await fetch(apiPath('/agent/run_fleet'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ instructions, ...(model ? { model } : {}) }),
  }))
}

export async function getAgentFleetJob(jobId) {
  return readJson(await fetch(apiPath(`/agent/fleet_job/${jobId}`)))
}

export async function getSimulationOptions() {
  return readJson(await fetch(apiPath('/simulation/options')))
}

export async function getSimulationStatus() {
  return readJson(await fetch(apiPath('/simulation/status')))
}

export async function startSimulation({ mode, world, robots, sequentialNav = false }) {
  return readJson(await fetch(apiPath('/simulation/start'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, world, robots, sequential_nav: sequentialNav }),
  }))
}

export async function stopSimulation() {
  return readJson(await fetch(apiPath('/simulation/stop'), { method: 'POST' }))
}

export async function activateRobot(robotId) {
  const params = new URLSearchParams({ robot_id: robotId })
  return readJson(await fetch(apiPath(`/simulation/activate_robot?${params.toString()}`), { method: 'POST' }))
}

export async function deactivateRobot(robotId) {
  const params = new URLSearchParams({ robot_id: robotId })
  return readJson(await fetch(apiPath(`/simulation/deactivate_robot?${params.toString()}`), { method: 'POST' }))
}
