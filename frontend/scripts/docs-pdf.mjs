// Gera os PDFs do manual e do roteiro do teste no CIn a partir das páginas em docs/ufpe/.
// Uso: npm --prefix frontend run docs:pdf   (saída em docs/ufpe/*.pdf)
import { chromium } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const DOCS = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../docs/ufpe')
const PRINT_CSS = `
  @page { size: A4; margin: 14mm 12mm; }
  body { padding: 0 !important; font-size: 10.5pt; }
  .cmd button, .reset, summary::after, .progress { display: none !important; }
  .cmd pre { padding: 0.7rem 0.9rem !important; white-space: pre-wrap; word-break: break-all; }
  figure, .card, .tablebox, .cmd, .note, details, .stop, ol.steps > li { break-inside: avoid; }
  header.hero { padding-block: 0 1rem !important; }
  .shots { grid-template-columns: 1fr 1fr !important; }
  #docker { break-before: page; }
  h2, h3 { break-after: avoid; }
  footer { margin-top: 0.6rem !important; padding-top: 0.5rem !important; font-size: 8.5pt; }
  details + details { margin-top: 0.3rem !important; }
`
const DOCS_TO_PRINT = [
  ['manual.html', 'Manual_FleetUI_teste_BLE.pdf'],
  ['roteiro.html', 'Roteiro_teste_CIn.pdf'],
]

const browser = await chromium.launch()
for (const [src, out] of DOCS_TO_PRINT) {
  const page = await browser.newPage({ colorScheme: 'light' })
  await page.goto('file://' + path.join(DOCS, src), { waitUntil: 'load' })
  await page.evaluate(() => document.fonts.ready)
  await page.addStyleTag({ content: PRINT_CSS })
  await page.evaluate(() => {
    document.querySelectorAll('details').forEach(d => { d.open = true })
    document.querySelectorAll('input[type=checkbox]').forEach(b => { b.checked = false })
    document.querySelectorAll('li.done').forEach(li => li.classList.remove('done'))
  })
  await page.pdf({ path: path.join(DOCS, out), format: 'A4', printBackground: true, scale: 0.96,
    margin: { top: '14mm', bottom: '14mm', left: '12mm', right: '12mm' } })
  console.log('gerado', out)
  await page.close()
}
await browser.close()
