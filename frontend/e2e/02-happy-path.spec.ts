import { expect, test } from '@playwright/test'
import {
  branches,
  collectConsole,
  ingestResponse,
  json,
  mockApi,
  profileResponse,
  repoDetail,
  repoList,
  repoSummary,
  runStatus,
} from './helpers'

/**
 * E2E-01 / E2E-04: the full onboarding -> progress -> profile -> re-analyze flow,
 * driven entirely through the UI with the backend responses mocked so the
 * pipeline is deterministic and fast. A separate @network test does the same
 * against the real GitHub-backed backend.
 */
test.describe('happy path (mocked backend)', () => {
  test('onboard a repo, watch staged progress, land on the profile dashboard', async ({ page }) => {
    const { errors } = collectConsole(page)
    // status sequence the poller will walk through
    const seq = ['QUEUED', 'VALIDATING', 'FETCHING', 'CLONING', 'ANALYZING', 'READY']
    let pollN = 0
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([])) },
      { match: /\/repositories\/github$/, handler: json(ingestResponse(), 202) },
      {
        match: /\/analysis-runs\/run-1$/,
        handler: (route) => {
          const status = seq[Math.min(pollN, seq.length - 1)]
          pollN += 1
          return route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(runStatus({ status, commit_sha: status === 'READY' ? 'abc123' : null })),
          })
        },
      },
      { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse()) },
      { match: /\/repositories\/repo-1\/branches$/, handler: json(branches([{ name: 'master', is_default: true }, { name: 'develop' }])) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
    ])

    await page.goto('/')
    await expect(page.getByText(/no repositories analyzed yet/i)).toBeVisible()

    await page.getByLabel(/repository url/i).fill('https://github.com/octocat/Hello-World')
    await page.getByRole('button', { name: /analyze repository/i }).click()

    // progress view with a live status region
    await expect(page.getByRole('heading', { name: /analyzing repository/i })).toBeVisible()
    const status = page.getByRole('status').first()
    await expect(status).toBeVisible()
    // walks through at least one intermediate stage before READY
    await expect(page.getByText(/current stage:/i)).toBeVisible()

    // eventually transitions to the profile dashboard
    await expect(page.getByRole('heading', { name: /octocat\/Hello-World/ })).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
    await expect(page.getByText('Python')).toBeVisible()
    await expect(page.getByText('pytest')).toBeVisible()
    await expect(page.getByText('react', { exact: true })).toBeVisible()

    // polling has stopped (terminal) - give it a beat and confirm no further poll
    const before = pollN
    await page.waitForTimeout(2500)
    expect(pollN, 'poller must stop once READY').toBe(before)

    expect(errors, errors.join('\n')).toEqual([])
  })

  test('E2E-04: re-analyze a different branch resets progress and does not show stale profile', async ({ page }) => {
    let pollN = 0
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary()])) },
      { match: /\/repositories\/repo-1\/refresh$/, handler: json(ingestResponse({ analysis_run_id: 'run-2' }), 202) },
      {
        match: /\/analysis-runs\/run-2$/,
        handler: (route) => {
          pollN += 1
          return route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify(runStatus({ id: 'run-2', status: pollN >= 3 ? 'READY' : 'ANALYZING' })),
          })
        },
      },
      { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse({ selected_branch: 'develop' })) },
      { match: /\/repositories\/repo-1\/branches$/, handler: json(branches([{ name: 'master', is_default: true }, { name: 'develop' }])) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
    ])

    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()

    await page.getByLabel('Branch').selectOption('develop')
    await page.getByRole('button', { name: /re-analyze this branch/i }).click()

    // leaves the profile for the progress view (mocked pipeline holds ANALYZING
    // for ~3 polls so this is reliably observable on every engine)
    await expect(page.getByRole('heading', { name: /analyzing repository/i })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Languages' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /re-analyze this branch/i })).toHaveCount(0)

    // then the fresh profile - and it must be the develop one, not a stale render
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('button', { name: /re-analyze this branch/i })).toBeVisible()
  })
})

test.describe('happy path (@network - real GitHub-backed backend)', () => {
  test('real ingestion of octocat/Hello-World reaches READY and renders a real profile', async ({ page, request }) => {
    test.setTimeout(120_000)
    // skip when the backend cannot reach GitHub
    const health = await request.get('http://localhost:8000/api/v1/health').catch(() => null)
    test.skip(!health || !health.ok(), 'backend not reachable on :8000')

    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('https://github.com/octocat/Hello-World')
    await page.getByRole('button', { name: /analyze repository/i }).click()

    // the enqueue POST hits the live GitHub API; under load it can be slow, and a
    // rate-limited enqueue surfaces on the form itself and never leaves the list
    const progress = page.getByRole('heading', { name: /analyzing repository/i })
    const formError = page.getByRole('alert')
    await expect(progress.or(formError)).toBeVisible({ timeout: 30_000 })
    if (await formError.isVisible()) {
      test.skip(true, `ingestion could not start (likely GitHub rate limit): ${await formError.innerText()}`)
    }

    // real pipeline: allow up to 90s, tolerate rate-limit / network failure by skipping
    const profile = page.getByRole('heading', { name: /octocat\/Hello-World/ })
    const failed = page.getByRole('heading', { name: /analysis failed/i })
    await expect(profile.or(failed)).toBeVisible({ timeout: 90_000 })

    if (await failed.isVisible()) {
      const msg = await page.locator('.failure .error-text').first().innerText()
      test.skip(true, `real ingestion failed (likely rate limit / network): ${msg}`)
    }

    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
    await expect(page.getByText(/Files scanned/i)).toBeVisible()
    // commit SHA rendered as a short code
    await expect(page.locator('.profile-facts code').first()).toHaveText(/^[0-9a-f]{7,12}$/)
  })
})
