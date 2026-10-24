import { test, expect } from '@playwright/test'
import { mockApi } from './mockApi.js'

const runButton = page => page.getByRole('button', { name: /Executar replay/ })

async function connect(page) {
  await page.getByRole('button', { name: /Conectar robô/ }).click()
  await page.getByRole('button', { name: 'Conectar', exact: true }).click()
  await expect(page.getByText(/Conectado — Custom \(simulação local\)/)).toBeVisible()
}

test.describe('replay do percurso CBSoft', () => {
  test('abre em Reproduzir com percurso_cbsoft e exige conexão', async ({ page }) => {
    await mockApi(page)
    await page.goto('/')

    await expect(page.getByRole('button', { name: /Reproduzir/ })).toBeVisible()
    await expect(page.getByRole('combobox').filter({ hasText: 'percurso_cbsoft' })).toHaveValue('percurso_cbsoft')
    await expect(page.getByText('Conecte um robô antes de executar.')).toBeVisible()
    await expect(runButton(page)).toBeDisabled()
  })

  test('conectar habilita o botão de replay', async ({ page }) => {
    await mockApi(page)
    await page.goto('/')
    await connect(page)

    await expect(page.getByText('Conecte um robô antes de executar.')).toBeHidden()
    await expect(runButton(page)).toBeEnabled()
  })

  test('executar replay envia a configuração e mostra o resultado', async ({ page }) => {
    const calls = await mockApi(page)
    await page.goto('/')
    await connect(page)
    await runButton(page).click()

    await expect(page.getByText('Sucesso')).toBeVisible()
    await expect(page.getByText('96.265 m')).toBeVisible()
    await expect(page.getByText('0.248 m/s')).toBeVisible()

    expect(calls.runConfig).toHaveLength(1)
    const sent = calls.runConfig[0]
    expect(sent.command).toBe('replay')
    expect(sent.route).toBe('percurso_cbsoft')
    expect(sent.topics).toEqual(expect.arrayContaining(['scan', 'odom', 'amcl_pose']))
  })

  test('Parar encerra a execução no servidor, não só na tela', async ({ page }) => {
    const stops = []
    const running = { running: true, lines: ['[CMD] replay'], result: null, error: null, exit_code: null }
    await mockApi(page, {
      // Execução que não termina sozinha, como um percurso de 6 min.
      '/api/job/e2e00001': route => route.fulfill({ json: running }),
      '/api/job/e2e00001/stop': route => {
        stops.push(route.request().method())
        running.running = false
        return route.fulfill({ json: { success: true, cancel: true, collection_closed: true } })
      },
    })
    await page.goto('/')
    await connect(page)
    await runButton(page).click()

    const stop = page.getByRole('button', { name: /Parar/ })
    await expect(stop).toBeVisible()
    await stop.click()

    await expect.poll(() => stops).toEqual(['POST'])
    await expect(stop).toBeHidden()
    await expect(runButton(page)).toBeEnabled()
  })

  test('rota de outro mundo bloqueia o replay', async ({ page }) => {
    // Pontos muito além do mapa gravado (x de -43 a 11 m, y de -57 a 27 m).
    await mockApi(page, { '/api/route_poses': { poses: [[120, 120, 0], [150, 130, 0], [180, 160, 0]] } })
    await page.goto('/')
    await connect(page)

    await expect(page.getByText(/3 ponto\(s\) da rota “percurso_cbsoft” ficam fora do mapa atual/)).toBeVisible()
    await expect(runButton(page)).toBeDisabled()
  })

  test('backend fora do ar mostra o erro ao conectar', async ({ page }) => {
    await mockApi(page, { '/api/status': route => route.abort('connectionrefused') })
    await page.goto('/')
    await page.getByRole('button', { name: /Conectar robô/ }).click()
    await page.getByRole('button', { name: 'Conectar', exact: true }).click()

    await expect(page.getByRole('status').filter({ hasText: /Backend não respondeu/ })).toBeVisible()
    await expect(runButton(page)).toBeDisabled()
  })

  test('agentes de IA ficam fora da tela', async ({ page }) => {
    await mockApi(page)
    await page.goto('/')
    await expect(page.getByRole('button', { name: /Conectar robô/ })).toBeVisible()
    await expect(page.getByRole('button', { name: /Agentes IA/ })).toHaveCount(0)
  })
})

test('stack real responde e abre no percurso CBSoft @live', async ({ page }) => {
  test.skip(!process.env.LIVE, 'só com LIVE=1 e o stack no ar (make cbsoft-up)')
  await page.goto('/')
  await connect(page)
  await expect(runButton(page)).toBeEnabled()
})
