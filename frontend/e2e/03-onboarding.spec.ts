import { expect, test } from '@playwright/test'
import { collectConsole, ingestResponse, json, jsonAfter, mockApi, repoList } from './helpers'

test.describe('onboarding form - validation & edge inputs', () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, [{ match: /\/repositories\?/, handler: json(repoList([])) }])
  })

  test('empty submit shows an inline alert and never calls the API', async ({ page }) => {
    let ingestCalls = 0
    await page.route('**/api/v1/repositories/github', (r) => {
      ingestCalls += 1
      return r.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(ingestResponse()) })
    })
    await page.goto('/')
    await page.getByRole('button', { name: /analyze repository/i }).click()
    const alert = page.getByRole('alert')
    await expect(alert).toBeVisible()
    await expect(alert).toContainText(/enter a github repository url/i)
    expect(ingestCalls).toBe(0)
  })

  test('whitespace-only URL is treated as empty', async ({ page }) => {
    let ingestCalls = 0
    await page.route('**/api/v1/repositories/github', (r) => {
      ingestCalls += 1
      return r.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(ingestResponse()) })
    })
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('     ')
    await page.getByRole('button', { name: /analyze repository/i }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    expect(ingestCalls).toBe(0)
  })

  test('a malformed / non-GitHub URL is forwarded and the backend 400 is surfaced verbatim', async ({ page }) => {
    await page.route('**/api/v1/repositories/github', (r) =>
      r.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ code: 'UNSUPPORTED_REPOSITORY_PROVIDER', message: 'Only github.com repositories are supported.' }),
      }),
    )
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('https://gitlab.com/foo/bar')
    await page.getByRole('button', { name: /analyze repository/i }).click()
    await expect(page.getByRole('alert')).toContainText('Only github.com repositories are supported.')
    // form still usable, values retained
    await expect(page.getByLabel(/repository url/i)).toHaveValue('https://gitlab.com/foo/bar')
    await expect(page.getByRole('button', { name: /analyze repository/i })).toBeEnabled()
  })

  test('a very long single-line URL does not break layout or hang the input', async ({ page }) => {
    const huge = 'https://github.com/o/' + 'x'.repeat(20_000)
    await page.route('**/api/v1/repositories/github', (r) =>
      r.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ code: 'INVALID_REPOSITORY_URL', message: 'Invalid repository URL.' }) }),
    )
    await page.goto('/')
    const start = Date.now()
    await page.getByLabel(/repository url/i).fill(huge)
    expect(Date.now() - start, 'typing a huge value should be fast').toBeLessThan(5_000)
    await page.getByRole('button', { name: /analyze repository/i }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    // page must not have gained a horizontal scrollbar
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, 'no horizontal page overflow').toBeLessThanOrEqual(1)
  })

  test('Unicode / emoji in URL and branch are sent through unchanged', async ({ page }) => {
    let body: unknown
    await page.route('**/api/v1/repositories/github', async (r) => {
      body = r.request().postDataJSON()
      return r.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ code: 'INVALID_REPOSITORY_URL', message: 'nope' }) })
    })
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('https://github.com/ówner/repö-🚀')
    await page.getByLabel(/branch \(optional\)/i).fill('feature/ünï-🌟')
    await page.getByRole('button', { name: /analyze repository/i }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    expect(body).toEqual({ repository_url: 'https://github.com/ówner/repö-🚀', branch: 'feature/ünï-🌟' })
  })

  test('rapid triple-click fires exactly one ingestion request (submit disabled while in flight)', async ({ page }) => {
    let calls = 0
    await page.route('**/api/v1/repositories/github', async (r) => {
      calls += 1
      await new Promise((res) => setTimeout(res, 600))
      return r.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(ingestResponse()) })
    })
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('https://github.com/octocat/Hello-World')
    // stable selector: the label changes to "Starting…" after the first click
    const submit = page.locator('form.onboarding-form button[type="submit"]')
    await submit.click()
    // hammer it while the request is in flight; disabled button must swallow these
    await submit.click({ force: true, timeout: 1500 }).catch(() => {})
    await submit.click({ force: true, timeout: 1500 }).catch(() => {})
    await expect(page.getByRole('heading', { name: /analyzing repository/i })).toBeVisible()
    expect(calls, 'exactly one ingestion request').toBe(1)
  })

  test('Enter in the URL field submits the form once', async ({ page }) => {
    let calls = 0
    await page.route('**/api/v1/repositories/github', (r) => {
      calls += 1
      return r.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify(ingestResponse()) })
    })
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('https://github.com/octocat/Hello-World')
    await page.getByLabel(/repository url/i).press('Enter')
    await expect(page.getByRole('heading', { name: /analyzing repository/i })).toBeVisible()
    expect(calls).toBe(1)
  })

  test('slow ingestion keeps the button disabled until it resolves, then navigates', async ({ page }) => {
    const { errors } = collectConsole(page)
    await page.route('**/api/v1/repositories/github', jsonAfter(1500, ingestResponse(), 202))
    await page.route('**/api/v1/repositories/repo-1/analysis-runs/run-1', json({ id: 'run-1', repository_id: 'repo-1', status: 'ANALYZING', branch_name: null, commit_sha: null, error_code: null, error_message: null, started_at: '2024-01-01T00:00:00Z', completed_at: null }))
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('https://github.com/octocat/Hello-World')
    await page.getByRole('button', { name: /analyze repository/i }).click()
    await expect(page.getByRole('button', { name: /starting…/i })).toBeDisabled()
    await expect(page.getByRole('heading', { name: /analyzing repository/i })).toBeVisible({ timeout: 5000 })
    expect(errors, errors.join('\n')).toEqual([])
  })
})
