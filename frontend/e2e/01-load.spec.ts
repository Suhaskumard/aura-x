import { expect, test } from '@playwright/test'
import { API, branches, collectConsole, json, mockApi, profileResponse, repoDetail, repoList, repoSummary } from './helpers'

test.describe('startup & page load', () => {
  test('loads clean against the real backend: no console errors, correct initial state', async ({ page }) => {
    const { errors } = collectConsole(page)
    const resp = await page.goto('/')
    expect(resp?.status()).toBe(200)

    await expect(page).toHaveTitle('AURA-X')
    await expect(page.getByRole('heading', { level: 1, name: 'AURA-X' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Repositories' })).toBeVisible()

    const url = page.getByLabel(/repository url/i)
    await expect(url).toBeVisible()
    await expect(url).toHaveValue('')
    await expect(page.getByRole('button', { name: /analyze repository/i })).toBeEnabled()

    await expect(page.getByRole('button', { name: /back to repositories/i })).toHaveCount(0)

    // the real backend list call resolved (CORS ok) -> never stuck on "Loading repositories…"
    await expect(page.getByText('Loading repositories…')).toHaveCount(0, { timeout: 10_000 })

    expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([])
  })

  test('static assets and module graph load with no failed requests', async ({ page }) => {
    const failed: string[] = []
    page.on('requestfailed', (r) => failed.push(`${r.failure()?.errorText} ${r.url()}`))
    const statuses: Record<string, number> = {}
    page.on('response', (r) => {
      const u = new URL(r.url())
      if (u.origin === 'http://localhost:5173') statuses[u.pathname] = r.status()
    })
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    expect(failed, failed.join('\n')).toEqual([])
    expect(statuses['/']).toBe(200)
    expect(statuses['/src/main.tsx']).toBe(200)
    const favicon = await page.request.get('http://localhost:5173/favicon.svg')
    expect(favicon.status()).toBe(200)
  })

  test('hard refresh returns to a clean list view (no state persistence)', async ({ page }) => {
    await mockApi(page, [{ match: /\/repositories\?/, handler: json(repoList([repoSummary()])) }])
    await page.goto('/')
    await expect(page.getByRole('button', { name: /octocat\/Hello-World/ })).toBeVisible()

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Repositories' })).toBeVisible()
    await expect(page.getByRole('button', { name: /back to repositories/i })).toHaveCount(0)
    expect(new URL(page.url()).pathname).toBe('/')

    // no persisted client state
    const storage = await page.evaluate(() => ({
      local: { ...localStorage },
      session: { ...sessionStorage },
    }))
    expect(Object.keys(storage.local)).toEqual([])
    expect(Object.keys(storage.session)).toEqual([])
  })

  test('the app does not push browser history; the in-app Back control is the only nav', async ({ page }) => {
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary()])) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail({ latest_analysis_run: null })) },
      { match: /\/profile$/, handler: json(profileResponse()) },
      { match: /\/branches$/, handler: json(branches()) },
    ])
    await page.goto('/')
    const lenBefore = await page.evaluate(() => history.length)
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: /octocat\/Hello-World/ })).toBeVisible()
    expect(await page.evaluate(() => history.length)).toBe(lenBefore)

    await page.getByRole('button', { name: /back to repositories/i }).click()
    await expect(page.getByRole('heading', { name: 'Repositories' })).toBeVisible()
    await expect(page.getByRole('button', { name: /octocat\/Hello-World/ })).toBeVisible()
  })

  test('two independent tabs (contexts) do not share state', async ({ browser }) => {
    const ctxA = await browser.newContext()
    const ctxB = await browser.newContext()
    const a = await ctxA.newPage()
    const b = await ctxB.newPage()
    await a.route(`${API}/api/v1/**`, json(repoList([repoSummary({ id: 'a', owner: 'alpha', name: 'A' })])))
    await b.route(`${API}/api/v1/**`, json(repoList([repoSummary({ id: 'b', owner: 'beta', name: 'B' })])))
    await a.goto('/')
    await b.goto('/')
    await expect(a.getByRole('button', { name: /alpha\/A/ })).toBeVisible()
    await expect(b.getByRole('button', { name: /beta\/B/ })).toBeVisible()
    await expect(a.getByRole('button', { name: /beta\/B/ })).toHaveCount(0)
    await ctxA.close()
    await ctxB.close()
  })
})
