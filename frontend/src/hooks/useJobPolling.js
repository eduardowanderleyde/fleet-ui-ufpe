import { useCallback, useEffect, useRef, useState } from 'react'
import { getJob } from '../api/fleetApi'

export function useJobPolling() {
  const [jobId, setJobId] = useState(null)
  const [job, setJob] = useState(null)
  const [running, setRunning] = useState(false)
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
        const data = await getJob(id)
        setJob(data)
        if (!data.running) stopPolling()
      } catch {
        // Keep polling: transient backend startup/network failures are recoverable.
      }
    }, 500)
  }, [stopPolling])

  const resetJob = useCallback(() => {
    setJob(null)
    setJobId(null)
    setRunning(false)
  }, [])

  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current)
  }, [])

  return { jobId, job, running, setRunning, startPolling, stopPolling, resetJob }
}
