import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import RobotPanel from './RobotPanel'

function link(overrides = {}) {
  return {
    status: { phase: 'idle', message: '', checks: [], lines: [], clock_command: null },
    ip: '192.168.50.11',
    setIp: vi.fn(),
    connect: vi.fn(),
    disconnect: vi.fn(),
    pending: false,
    actionError: null,
    ...overrides,
  }
}

describe('RobotPanel', () => {
  it('Conectar chama connect com um IP válido', () => {
    const l = link()
    render(<RobotPanel link={l} />)
    fireEvent.click(screen.getByRole('button', { name: /conectar/i }))
    expect(l.connect).toHaveBeenCalledTimes(1)
  })

  it('IP incompleto deixa Conectar desabilitado', () => {
    render(<RobotPanel link={link({ ip: '192.168.50' })} />)
    expect(screen.getByRole('button', { name: /conectar/i })).toBeDisabled()
  })

  it('FALHA da checagem aparece linha a linha, com o comando do relógio', () => {
    render(<RobotPanel link={link({
      status: {
        phase: 'error', message: '1 item(ns) com FALHA: resolver antes de mover o robô.',
        checks: [
          { status: 'ok', name: 'rede', detail: '192.168.50.11 responde na rede' },
          { status: 'fail', name: 'relógio /scan', detail: 'defasagem mediana +2.10 s' },
        ],
        lines: [], clock_command: "ssh ubuntu@192.168.50.11 \"sudo date -s '@$(date +%s.%N)'\"",
      },
    })} />)
    expect(screen.getByText(/não conectou/i)).toBeInTheDocument()
    expect(screen.getByText('relógio /scan')).toBeInTheDocument()
    expect(screen.getByText(/ssh ubuntu@192.168.50.11/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reconectar/i })).toBeEnabled()
  })

  it('pronto: mostra conectado e permite desconectar', () => {
    const l = link({ status: { phase: 'ready', message: 'Robô conectado: Nav2 ativo.', checks: [], lines: [], clock_command: 'x' } })
    render(<RobotPanel link={l} />)
    expect(screen.getByText('✓ Robô conectado')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /desconectar/i }))
    expect(l.disconnect).toHaveBeenCalledTimes(1)
  })

  it('durante a checagem não deixa clicar de novo', () => {
    render(<RobotPanel link={link({ status: { phase: 'checking', message: 'Procurando…', checks: [], lines: [], clock_command: null } })} />)
    expect(screen.getByRole('button', { name: /aguarde/i })).toBeDisabled()
  })
})
