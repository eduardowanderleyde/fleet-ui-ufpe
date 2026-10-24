import { useCallback, useEffect, useRef, useState } from 'react'
import { getAgentFleetJob, runAgentFleet } from '../api/fleetApi'

export function useAgentFleet() {
  const [jobId, setJobId] = useState(null)
  const [job, setJob] = useState(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
    setRunning(false)
  }, [])

  const startPolling = useCallback((id) => {
    if (pollRef.current) clearInterval(pollRef.current)
    setJobId(id)
    setRunning(true)
    pollRef.current = setInterval(async () => {
      try {
        const data = await getAgentFleetJob(id)
        setJob(data)
        if (!data.running) stopPolling()
      } catch {
        // Keep polling: transient backend/network failures are recoverable.
      }
    }, 700)
  }, [stopPolling])

  const dispatch = useCallback(async (instructions, model) => {
    setError(null)
    setJob(null)
    try {
      const data = await runAgentFleet(instructions, model)
      if (!data?.job_id) {
        setError(data?.message || 'Erro ao disparar agentes')
        return
      }
      startPolling(data.job_id)
    } catch (e) {
      setError(e.message)
    }
  }, [startPolling])

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current)
  }, [])

  return { jobId, job, running, error, dispatch, stopPolling }
}
