import { useCallback, useEffect, useState } from 'react'
import { listRunHistory } from '../api/fleetApi'

export function useRunHistory() {
  const [runs, setRuns]       = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [selected, setSelected] = useState([])   // até 2 job_id pra comparar

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await listRunHistory(50)
      setRuns(data.runs || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const toggleSelect = useCallback(jobId => {
    setSelected(prev => {
      if (prev.includes(jobId)) return prev.filter(id => id !== jobId)
      if (prev.length >= 2) return [prev[1], jobId]   // mantém só as 2 últimas escolhas
      return [...prev, jobId]
    })
  }, [])

  return { runs, loading, error, refresh, selected, toggleSelect }
}
