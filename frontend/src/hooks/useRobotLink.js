import { useCallback, useEffect, useState } from 'react'
import { connectRobot, disconnectRobot, getRobotStatus } from '../api/fleetApi'

const IP_KEY = 'fleet-robot-ip'
const EMPTY = { robot_mode: false, default_ip: '', phase: 'idle', ip: null, message: '', checks: [], lines: [], clock_command: null }

// Estado da ligação com o robô real (backend/robot_link.py). robot_mode só
// vem true com `make robot-up`; fora dele a tela segue no modo simulação.
export function useRobotLink(intervalMs = 1500) {
  const [status, setStatus] = useState(EMPTY)
  const [ip, setIpState] = useState(() => {
    try { return localStorage.getItem(IP_KEY) || '' } catch { return '' }
  })
  const [actionError, setActionError] = useState(null)
  const [pending, setPending] = useState(false)

  const setIp = useCallback(value => {
    setIpState(value)
    try { localStorage.setItem(IP_KEY, value) } catch { /* modo privado */ }
  }, [])

  useEffect(() => {
    let alive = true
    const poll = () => getRobotStatus()
      .then(s => { if (alive) setStatus({ ...EMPTY, ...s }) })
      .catch(() => {})
    poll()
    const id = setInterval(poll, intervalMs)
    return () => { alive = false; clearInterval(id) }
  }, [intervalMs])

  // Campo vazio na primeira vez: usa o ROBOT_IP do make robot-up, se houver.
  useEffect(() => {
    if (!ip && status.default_ip) setIp(status.default_ip)
  }, [ip, status.default_ip, setIp])

  const connect = useCallback(async () => {
    setActionError(null)
    setPending(true)
    try {
      const s = await connectRobot(ip.trim())
      setStatus(prev => ({ ...prev, ...s }))
    } catch (e) {
      setActionError(e.message)
    } finally {
      setPending(false)
    }
  }, [ip])

  const disconnect = useCallback(async () => {
    setActionError(null)
    setPending(true)
    try {
      await disconnectRobot()
      setStatus(prev => ({ ...prev, phase: 'idle', message: '', checks: [], lines: [] }))
    } catch (e) {
      setActionError(e.message)
    } finally {
      setPending(false)
    }
  }, [])

  return { status, ip, setIp, connect, disconnect, pending, actionError }
}
