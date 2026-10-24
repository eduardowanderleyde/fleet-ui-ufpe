import { useCallback, useEffect, useState } from 'react'
import { getRoutePoses, listRoutes } from '../api/fleetApi'

export function useRoutePoses(name, robotId) {
  const [poses, setPoses] = useState([])

  useEffect(() => {
    if (!name) { setPoses([]); return }
    let alive = true
    getRoutePoses(name, robotId)
      .then(d => { if (alive) setPoses(d.poses || []) })
      .catch(() => { if (alive) setPoses([]) })
    return () => { alive = false }
  }, [name, robotId])

  return poses
}

export function useRoutes(robotId) {
  const [routes, setRoutes] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const refreshRoutes = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listRoutes(robotId)
      setRoutes(data.route_names || [])
    } catch (err) {
      setRoutes([])
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [robotId])

  useEffect(() => {
    refreshRoutes()
  }, [refreshRoutes])

  return { routes, loading, error, refreshRoutes }
}
