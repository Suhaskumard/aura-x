import { expect, test } from '@playwright/test'
import {
  abort,
  branches,
  collectConsole,
  ingestResponse,
  json,
  mockApi,
  profileResponse,
  raw,
  repoDetail,
  repoList,
  repoSummary,
  runStatus,
} from './helpers'

test.describe('loading, error & recovery', () => {
  const httpCases: Array<[number, string, string]> = [
    [400, 'INVALID_REPOSITORY_URL', 'Invalid repository URL.'],
    [401, 'UNAUTHORIZED', 'Authentication required.'],
    [403, 'REPOSITORY_ACCESS_DENIED', 'Access denied.'],
    [404, 'REPOSITORY_NOT_FOUND', 'Repository not found.'],
    [409, 'ANALYSIS_NOT_READY', 'Analysis is not ready.'],
    [429, 'RATE_LIMITED', 'GitHub rate limit hit. Try again later.'],
    [500, 'INTERNAL_ERROR', 'An unexpected error occurred.'],
    [502, 'UPSTREAM_UNAVAILABLE', 'GitHub is unavailable.'],
  ]

  for (const [status, code, message] of httpCases) {
    test(`repository list surfaces a ${status} (${code}) without crashing`, async ({ page }) => {
      const { errors } = collectConsole(page)
      await mockApi(page, [{ match: /\/repositories\?/, handler: raw(JSON.stringify({ code, message }), status, 'application/json') }])
      await page.goto('/')
      await expect(page.locator('.error-text')).toContainText(message)
      // form still there, app not blank
      await expect(page.getByRole('button', { name: /analyze repository/i })).toBeVisible()
      expect(errors.filter((e) => !e.includes('Failed to load resource')), errors.join('\n')).toEqual([])
    })
  }

  test('malformed JSON body falls back to a generic message (no crash)', async ({ page }) => {
    await mockApi(page, [{ match: /\/repositories\?/, handler: raw('{not json at all', 500, 'application/json') }])
    await page.goto('/')
    await expect(page.locator('.error-text')).toContainText(/could not load repositories|request failed with status 500/i)
  })

  test('HTML body instead of JSON (e.g. a proxy 502 page) is handled', async ({ page }) => {
    await mockApi(page, [{ match: /\/repositories\?/, handler: raw('<html><body>502 Bad Gateway</body></html>', 502, 'text/html') }])
    await page.goto('/')
    await expect(page.locator('.error-text')).toContainText(/could not load repositories|request failed with status 502/i)
    // the raw HTML must not be injected into the page
    await expect(page.locator('body')).not.toContainText('Bad Gateway')
  })

  test('empty 200 body while listing does not wedge the UI', async ({ page }) => {
    await mockApi(page, [{ match: /\/repositories\?/, handler: raw('', 200, 'application/json') }])
    await page.goto('/')
    // parsing "" throws -> surfaces as an error, not an infinite spinner
    await expect(page.getByText('Loading repositories…')).toHaveCount(0, { timeout: 10_000 })
  })

  test('connection refused / aborted request shows the network error', async ({ page }) => {
    await mockApi(page, [{ match: /\/repositories\?/, handler: abort() }])
    await page.goto('/')
    await expect(page.locator('.error-text')).toContainText(/could not (load repositories|reach the backend)/i)
  })

  test('ERROR -> RETRY -> SUCCESS: list recovers after a transient failure', async ({ page }) => {
    // React 18/19 StrictMode double-invokes effects in dev, so the first mount can
    // fire the list fetch twice; key off a flag, not a call ordinal.
    let listFails = true
    await mockApi(page, [
      {
        match: /\/repositories\?/,
        handler: (route) =>
          listFails
            ? route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ code: 'INTERNAL_ERROR', message: 'boom' }) })
            : route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoList([repoSummary()])) }),
      },
    ])
    await page.goto('/')
    await expect(page.locator('.error-text')).toContainText('boom')
    await expect(page.getByRole('button', { name: /octocat\/Hello-World/ })).toHaveCount(0)

    // "retry" for the list = remount (reload / back-to-list). Flip the backend to healthy.
    listFails = false
    await page.reload()
    await expect(page.getByRole('button', { name: /octocat\/Hello-World/ })).toBeVisible()
    await expect(page.locator('.error-text')).toHaveCount(0)
  })

  test('SUCCESS -> ERROR -> SUCCESS on repository open only ever shows the latest state', async ({ page }) => {
    test.slow() // 3 full nav round-trips; WebKit automation on Windows is slow
    let openN = 0
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary()])) },
      {
        match: /\/repositories\/repo-1$/,
        handler: (route) => {
          openN += 1
          if (openN === 2) {
            return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ code: 'INTERNAL_ERROR', message: 'transient open failure' }) })
          }
          return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoDetail({ latest_analysis_run: null })) })
        },
      },
      { match: /\/profile$/, handler: json(profileResponse()) },
      { match: /\/branches$/, handler: json(branches()) },
    ])
    await page.goto('/')
    const card = page.getByRole('button', { name: /octocat\/Hello-World/ })

    // 1: success
    await card.click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
    await page.getByRole('button', { name: /back to repositories/i }).click()

    // 2: error - stays on list, shows error
    await card.click()
    await expect(page.locator('.error-text')).toContainText('transient open failure')
    await expect(page.getByRole('heading', { name: 'Repositories' })).toBeVisible()

    // 3: success again - error must be cleared
    await card.click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
    await expect(page.locator('.error-text')).toHaveCount(0)
  })

  test('polling loses the backend mid-progress, shows a retry notice, then recovers', async ({ page }) => {
    let n = 0
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([])) },
      { match: /\/repositories\/github$/, handler: json(ingestResponse(), 202) },
      {
        match: /\/analysis-runs\/run-1$/,
        handler: (route) => {
          n += 1
          if (n >= 2 && n <= 3) return route.abort('failed') // two failed polls
          return route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(runStatus({ status: n > 4 ? 'READY' : 'ANALYZING' })),
          })
        },
      },
      { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse()) },
      { match: /\/repositories\/repo-1\/branches$/, handler: json(branches()) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
    ])
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('https://github.com/octocat/Hello-World')
    await page.getByRole('button', { name: /analyze repository/i }).click()

    await expect(page.getByText(/lost contact with the backend/i)).toBeVisible({ timeout: 10_000 })
    // it keeps polling and recovers all the way to the profile
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible({ timeout: 20_000 })
  })

  test('FAILED run -> Retry -> failure again keeps the button enabled and original error visible', async ({ page }) => {
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary({ latest_status: 'FAILED' })])) },
      {
        match: /\/repositories\/repo-1$/,
        handler: json(
          repoDetail({
            latest_analysis_run: {
              id: 'run-1',
              status: 'FAILED',
              branch_name: 'master',
              commit_sha: null,
              error_code: 'CLONE_FAILED',
              error_message: 'git clone exited with code 128',
              started_at: '2024-01-01T00:00:00Z',
              completed_at: '2024-01-01T00:01:00Z',
            },
          }),
        ),
      },
      { match: /\/repositories\/repo-1\/refresh$/, handler: raw(JSON.stringify({ code: 'RATE_LIMITED', message: 'try later' }), 429, 'application/json') },
    ])
    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: /analysis failed/i })).toBeVisible()
    await expect(page.getByText('git clone exited with code 128')).toBeVisible()

    await page.getByRole('button', { name: /retry analysis/i }).click()
    await expect(page.getByText('try later')).toBeVisible()
    await expect(page.getByRole('button', { name: /retry analysis/i })).toBeEnabled()
    // original failure context still present
    await expect(page.getByText('git clone exited with code 128')).toBeVisible()
  })
})
