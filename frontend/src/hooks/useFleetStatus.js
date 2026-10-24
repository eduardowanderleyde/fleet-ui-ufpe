import { useEffect, useState } from 'react'
import { getStatus } from '../api/fleetApi'

const EMPTY_STATUS = { robots: [], pose: { x: 0, y: 0, yaw: 0, valid: false } }

export function useFleetStatus(intervalMs = 300) {
  const [status, setStatus] = useState(EMPTY_STATUS)

  useEffect(() => {
    let alive = true

    const refresh = async () => {
      try {
        const data = await getStatus()
        if (alive && data) setStatus(data)
      } catch {
        // Backend can be offline while the simulator is starting.
      }
    }

    refresh()
    const timer = setInterval(refresh, intervalMs)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [intervalMs])

  return status
}
