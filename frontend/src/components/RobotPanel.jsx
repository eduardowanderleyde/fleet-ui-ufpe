import React, { useState } from 'react'
import { color, btn, S as T } from '../styles/tokens'

const S = {
  box:   { background: color.bgPanel, border: `1px solid ${color.border}`, borderRadius: '8px', padding: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' },
  title: { fontSize: '0.8rem', fontWeight: 600, color: color.textMuted },
  hint:  { fontSize: '0.7rem', color: color.textMuted },
  code:  { background: color.bgApp, border: `1px solid ${color.border}`, borderRadius: '6px', padding: '0.35rem 0.5rem', fontSize: '0.68rem', fontFamily: 'monospace', color: color.text, wordBreak: 'break-all' },
  log:   { background: color.bgApp, border: `1px solid ${color.border}`, borderRadius: '6px', padding: '0.4rem 0.55rem', fontSize: '0.66rem', fontFamily: 'monospace', color: color.textMuted, maxHeight: '110px', overflowY: 'auto', whiteSpace: 'pre-wrap' },
}

const PHASE = {
  idle:     { label: null, color: color.textMuted },
  checking: { label: '⏳ Checando…', color: color.warning },
  starting: { label: '⏳ Ligando Nav2…', color: color.warning },
  ready:    { label: '✓ Robô conectado', color: color.success },
  error:    { label: '✗ Não conectou', color: color.danger },
}

// Giro de "conectado" (backend/robot_link.py → robot_wiggle.py).
const SIGNAL = {
  sending: { label: '↺ Girando um pouquinho para sinalizar…', color: color.warning },
  ok:      { label: '↺ O robô girou um pouquinho: conexão confirmada.', color: color.success },
  failed:  { label: '⚠ O giro de sinal não foi enviado (veja as linhas abaixo).', color: color.warning },
}

const MARK = {
  ok:   { icon: '✓', color: color.success },
  warn: { icon: '⚠', color: color.warning },
  fail: { icon: '✗', color: color.danger },
}

function CopyLine({ text }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }, () => {})
  }
  return (
    <div style={{ display: 'flex', gap: '0.35rem', alignItems: 'stretch' }}>
      <code style={{ ...S.code, flex: 1 }}>{text}</code>
      <button type="button" onClick={copy} style={{ ...btn(color.bgPanel, color.textMuted2), fontSize: '0.68rem', padding: '0.2rem 0.5rem' }}>
        {copied ? 'Copiado' : 'Copiar'}
      </button>
    </div>
  )
}

function CheckList({ checks }) {
  return (
    <ul aria-label="Checagem" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '0.15rem' }}>
      {checks.map((c, i) => {
        const m = MARK[c.status] || MARK.warn
        return (
          <li key={i} style={{ display: 'grid', gridTemplateColumns: '1rem minmax(0, 1fr)', gap: '0.3rem', fontSize: '0.7rem' }}>
            <span style={{ color: m.color }}>{m.icon}</span>
            <span style={{ color: color.textMuted2, overflowWrap: 'anywhere' }}>
              <b style={{ color: color.text, fontWeight: 600 }}>{c.name}</b> — {c.detail}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

// Painel do modo robô real (make robot-up): substitui o de simulação.
// Conectar = rede + checagem pré-voo + mapa/AMCL/Nav2 no PC; Reconectar
// desliga tudo e refaz com o IP do campo.
export default function RobotPanel({ link }) {
  const { status, ip, setIp, connect, disconnect, pending, actionError } = link
  const phase = PHASE[status.phase] || PHASE.idle
  const busy = pending || status.phase === 'checking' || status.phase === 'starting'
  const active = status.phase !== 'idle'
  const ipValid = /^\d{1,3}(\.\d{1,3}){3}$/.test(ip.trim())
  const showLog = (status.phase === 'starting' || status.phase === 'error' || status.signal === 'failed') && status.lines.length > 0

  return (
    <section aria-label="Robô real" style={S.box}>
      <span style={S.title}>Robô real</span>

      <label style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
        <span style={S.hint}>IP do robô (na telinha do robô ou na página do roteador)</span>
        <input
          value={ip}
          onChange={e => setIp(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && ipValid && !busy) connect() }}
          placeholder="ex.: 192.168.50.11"
          inputMode="decimal"
          disabled={busy}
          style={T.input}
        />
      </label>

      <div style={{ display: 'flex', gap: '0.4rem' }}>
        <button type="button" onClick={connect} disabled={busy || !ipValid}
          style={{ ...btn(color.brandDark, color.brand, busy || !ipValid), flex: 1 }}>
          {busy ? '⏳ Aguarde…' : active ? '↻ Reconectar' : '▶ Conectar'}
        </button>
        {active && (
          <button type="button" onClick={disconnect} disabled={pending}
            style={btn(color.dangerBg, color.danger, pending)}>
            Desconectar
          </button>
        )}
      </div>

      {actionError && <div role="alert" style={{ fontSize: '0.78rem', color: color.danger }}>{actionError}</div>}

      {active && (
        <div role="status" style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
          {phase.label && <span style={{ fontSize: '0.8rem', fontWeight: 600, color: phase.color }}>{phase.label}</span>}
          {status.message && <span style={{ fontSize: '0.74rem', color: color.textMuted2 }}>{status.message}</span>}
          {SIGNAL[status.signal] && <span style={{ fontSize: '0.72rem', color: SIGNAL[status.signal].color }}>{SIGNAL[status.signal].label}</span>}
        </div>
      )}

      {status.checks.length > 0 && status.phase === 'ready' && (
        <details>
          <summary style={{ fontSize: '0.72rem', color: color.textMuted2, cursor: 'pointer' }}>
            Checagem: {status.checks.filter(c => c.status === 'ok').length} de {status.checks.length} OK
          </summary>
          <CheckList checks={status.checks} />
        </details>
      )}
      {status.checks.length > 0 && status.phase !== 'ready' && <CheckList checks={status.checks} />}

      {status.clock_command && status.phase !== 'ready' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
          <span style={S.hint}>Relógio do robô (passo 8, no terminal do PC; pede a senha do robô):</span>
          <CopyLine text={status.clock_command} />
        </div>
      )}

      {showLog && (
        <div style={S.log}>
          {status.lines.slice(-8).map((l, i) => <div key={i}>{l}</div>)}
        </div>
      )}
    </section>
  )
}
