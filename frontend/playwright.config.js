import { defineConfig, devices } from '@playwright/test'

// Testes E2E da interface. A API é mockada com respostas gravadas do backend
// real (e2e/fixtures/), então rodam sem ROS nem Docker. O teste @live usa o
// stack de verdade e só roda com LIVE=1 (ex.: depois de `make cbsoft-up`).
const PORT = 5174

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL: process.env.LIVE ? 'http://localhost:5173' : `http://localhost:${PORT}`,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: process.env.LIVE ? undefined : {
    command: `npx vite --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
  },
})
