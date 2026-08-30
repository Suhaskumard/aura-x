import { expect, test } from '@playwright/test'
import { branches, json, mockApi, profileResponse, repoDetail, repoList, repoSummary, runStatus } from './helpers'

/**
 * Screenshot capture for the QA report + a couple of real-backend UI paths
 * (no mocking) that the mocked specs can't prove.
 */
test.describe('visual capture', () => {
  test('key states (light)', async ({ page }, testInfo) => {
    const shot = (name: string) => page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true })

    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary(), repoSummary({ id: 'r2', owner: 'facebook', name: 'react', latest_status: 'FAILED', description: 'The library for web and native user interfaces.' })])) },
      { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse({ dependencies: Array.from({ length: 30 }, (_, i) => `pkg-${i}`) })) },
      { match: /\/repositories\/repo-1\/branches$/, handler: json(branches([{ name: 'master', is_default: true }, { name: 'develop' }])) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
      { match: /\/repositories\/github$/, handler: json(runStatus({ status: 'QUEUED' }), 202) },
    ])
    await page.goto('/')
    await expect(page.getByRole('button', { name: /octocat\/Hello-World/ })).toBeVisible()
    await shot('01-list')

    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
    await shot('02-profile')

    await page.setViewportSize({ width: 375, height: 700 })
    await shot('03-profile-mobile')
    await page.setViewportSize({ width: 1280, height: 800 })
  })

  test('real backend: an unknown repository id renders a clean error, not a crash', async ({ page, request }) => {
    const health = await request.get('http://localhost:8000/api/v1/health').catch(() => null)
    test.skip(!health || !health.ok(), 'backend not on :8000')
    // hit the profile route for a bogus id via the app by seeding the list with it
    await page.route('**/api/v1/repositories?*', (r) =>
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoList([repoSummary({ id: '00000000-0000-0000-0000-000000000000' })])) }),
    )
    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    // real backend returns 404 REPOSITORY_NOT_FOUND -> surfaced as text, still interactive
    await expect(page.locator('.error-text')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Repositories' })).toBeVisible()
  })

  test('real backend: submitting a non-GitHub URL surfaces the real 400', async ({ page, request }) => {
    const health = await request.get('http://localhost:8000/api/v1/health').catch(() => null)
    test.skip(!health || !health.ok(), 'backend not on :8000')
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('https://example.com/not/a/repo')
    await page.getByRole('button', { name: /analyze repository/i }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByRole('alert')).toContainText(/repositor|provider|url/i)
  })
})
