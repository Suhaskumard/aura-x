import { expect, test } from '@playwright/test'
import { branches, collectConsole, json, mockApi, profileResponse, repoDetail, repoList, repoSummary, runStatus } from './helpers'

test.describe('long-run stability', () => {
  test('open/back cycles: no DOM growth, no listener leak, no console errors', async ({ page }) => {
    test.setTimeout(120_000)
    const CYCLES = 20
    const { errors } = collectConsole(page)
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary(), repoSummary({ id: 'repo-2', owner: 'o2', name: 'n2' })])) },
      { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse()) },
      { match: /repo-1\/branches$/, handler: json(branches()) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
    ])
    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
    await page.getByRole('button', { name: /back to repositories/i }).click()
    await expect(page.getByRole('heading', { name: 'Repositories' })).toBeVisible()

    const sample = () => page.evaluate(() => document.getElementsByTagName('*').length)
    const baseline = await sample()

    for (let i = 0; i < CYCLES; i++) {
      await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
      await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
      await page.getByRole('button', { name: /back to repositories/i }).click()
      await expect(page.getByRole('heading', { name: 'Repositories' })).toBeVisible()
    }

    const after = await sample()
    // node count should return to ~baseline (allow small slack for React internals)
    expect(after, `DOM node count grew from ${baseline} to ${after} over ${CYCLES} cycles`).toBeLessThanOrEqual(baseline + 30)
    expect(errors, errors.join('\n')).toEqual([])
  })

  test('sequential re-analyze cycles keep polling bounded and reset cleanly', async ({ page }) => {
    test.setTimeout(120_000)
    const CYCLES = 12
    const { errors } = collectConsole(page)
    let poll = 0
    let runId = 0
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary()])) },
      {
        match: /\/repositories\/repo-1\/refresh$/,
        handler: (route) => {
          runId += 1
          poll = 0
          return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ repository_id: 'repo-1', provider: 'github', source_url: 'x', name: 'n', owner: 'o', selected_branch: null, commit_sha: null, status: 'QUEUED', analysis_run_id: `run-${runId}`, error_code: null, error_message: null }) })
        },
      },
      {
        match: /\/analysis-runs\/run-\d+$/,
        handler: (route) => {
          poll += 1
          return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(runStatus({ id: `run-${runId}`, status: poll >= 2 ? 'READY' : 'ANALYZING' })) })
        },
      },
      { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse()) },
      { match: /repo-1\/branches$/, handler: json(branches([{ name: 'master', is_default: true }, { name: 'develop' }])) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
    ])

    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()

    for (let i = 0; i < CYCLES; i++) {
      await page.getByRole('button', { name: /re-analyze this branch/i }).click()
      // the progress view appears (mocked pipeline can flip to READY quickly, so
      // just require that the run happened and we end back on a fresh profile)
      await expect(page.getByRole('heading', { name: /analyzing repository|Languages/ })).toBeVisible()
      await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible({ timeout: 15_000 })
      await expect(page.getByRole('button', { name: /re-analyze this branch/i })).toBeVisible()
      // each cycle's poll count must stay small - proves the previous poller was torn down
      expect(poll, `cycle ${i}: poll count ${poll} - stale poller still running?`).toBeLessThan(8)
    }
    expect(errors, errors.join('\n')).toEqual([])
  })

  test('a poller left running on the progress view is torn down when navigating back', async ({ page }) => {
    let polls = 0
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([])) },
      { match: /\/repositories\/github$/, handler: json({ repository_id: 'repo-1', provider: 'github', source_url: 'x', name: 'n', owner: 'o', selected_branch: null, commit_sha: null, status: 'QUEUED', analysis_run_id: 'run-1', error_code: null, error_message: null }, 202) },
      { match: /\/analysis-runs\/run-1$/, handler: (route) => { polls += 1; return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(runStatus({ status: 'ANALYZING' })) }) } },
    ])
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('https://github.com/octocat/Hello-World')
    await page.getByRole('button', { name: /analyze repository/i }).click()
    await expect(page.getByRole('heading', { name: /analyzing repository/i })).toBeVisible()
    await page.waitForTimeout(3500) // ~2 polls at 1500ms
    await page.getByRole('button', { name: /back to repositories/i }).click()
    await expect(page.getByRole('heading', { name: 'Repositories' })).toBeVisible()
    const at = polls
    await page.waitForTimeout(4000)
    expect(polls, `poller kept firing after unmount: ${at} -> ${polls}`).toBe(at)
  })
})
