import { expect, test } from '@playwright/test'
import { API, branches, json, mockApi, profileResponse, repoDetail, repoList, repoSummary, runStatus } from './helpers'

/**
 * Section 11: request races and stale-response guards.
 * The app has no AbortController; it relies on a monotonic sequence ref
 * (App.selectSeqRef) and per-effect `cancelled` flags. These tests prove
 * those guards actually hold in a real browser.
 */
test.describe('race conditions & stale responses', () => {
  test('a slow earlier repo-open must not overwrite the view chosen by a later click', async ({ page }) => {
    const two = repoSummary({ id: 'repo-2', owner: 'two', name: 'TWO' })
    const one = repoSummary({ id: 'repo-1', owner: 'one', name: 'ONE' })
    let resolveSlow: (() => void) | null = null

    await page.route(`${API}/api/v1/**`, async (route) => {
      const url = route.request().url()
      if (/\/repositories\?/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoList([one, two])) })
      if (/\/repositories\/repo-1$/.test(url)) {
        await new Promise<void>((r) => (resolveSlow = r)) // hang until released
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoDetail({ id: 'repo-1', owner: 'one', name: 'ONE', latest_analysis_run: null })) })
      }
      if (/\/repositories\/repo-2$/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoDetail({ id: 'repo-2', owner: 'two', name: 'TWO', latest_analysis_run: null })) })
      if (/repo-2\/profile$/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profileResponse({ owner: 'two', repository_name: 'TWO' })) })
      if (/repo-2\/branches$/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(branches()) })
      if (/repo-1\/profile$/.test(url)) return route.fulfill({ status: 500, contentType: 'application/json', body: '{"code":"X","message":"repo-1 profile should never be fetched"}' })
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{"code":"NOT_FOUND","message":"nf"}' })
    })

    await page.goto('/')
    await page.getByRole('button', { name: /one\/ONE/ }).click() // slow, hangs
    await page.getByRole('button', { name: /two\/TWO/ }).click() // fast, wins
    await expect(page.getByRole('heading', { name: /two\/TWO/ })).toBeVisible()

    // release the stale repo-1 response
    await page.waitForTimeout(200)
    // @ts-expect-error assigned inside route handler
    resolveSlow?.()
    await page.waitForTimeout(500)

    // still on repo-2, repo-1 never took over
    await expect(page.getByRole('heading', { name: /two\/TWO/ })).toBeVisible()
    await expect(page.getByRole('heading', { name: /one\/ONE/ })).toHaveCount(0)
  })

  test('a stale repo-open ERROR does not clobber the newer view chosen by a later click', async ({ page }) => {
    let rejectOne: (() => void) | null = null
    await page.route(`${API}/api/v1/**`, async (route) => {
      const url = route.request().url()
      if (/\/repositories\?/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoList([repoSummary({ id: 'repo-1', owner: 'one', name: 'ONE' }), repoSummary({ id: 'repo-2', owner: 'two', name: 'TWO' })])) })
      if (/\/repositories\/repo-1$/.test(url)) {
        await new Promise<void>((r) => (rejectOne = r))
        return route.fulfill({ status: 404, contentType: 'application/json', body: '{"code":"REPOSITORY_NOT_FOUND","message":"repo-1 is gone"}' })
      }
      if (/\/repositories\/repo-2$/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoDetail({ id: 'repo-2', owner: 'two', name: 'TWO', latest_analysis_run: null })) })
      if (/repo-2\/profile$/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profileResponse({ owner: 'two', repository_name: 'TWO' })) })
      if (/repo-2\/branches$/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(branches()) })
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{"code":"NOT_FOUND","message":"nf"}' })
    })
    await page.goto('/')
    await page.getByRole('button', { name: /one\/ONE/ }).click() // hangs, will 404
    await page.getByRole('button', { name: /two\/TWO/ }).click() // wins
    await expect(page.getByRole('heading', { name: /two\/TWO/ })).toBeVisible()

    await page.waitForTimeout(150)
    // @ts-expect-error assigned in handler
    rejectOne?.()
    await page.waitForTimeout(400)

    // the stale 404 for repo-1 must not surface anywhere
    await expect(page.getByText('repo-1 is gone')).toHaveCount(0)
    await expect(page.locator('.error-text')).toHaveCount(0)
    await expect(page.getByRole('heading', { name: /two\/TWO/ })).toBeVisible()
  })

  test('back-to-list while the profile is still loading discards the stale profile response', async ({ page }) => {
    let releaseProfile: (() => void) | null = null
    await page.route(`${API}/api/v1/**`, async (route) => {
      const url = route.request().url()
      if (/\/repositories\?/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoList([repoSummary()])) })
      if (/\/repositories\/repo-1$/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoDetail({ latest_analysis_run: null })) })
      if (/repo-1\/branches$/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(branches()) })
      if (/repo-1\/profile$/.test(url)) {
        await new Promise<void>((r) => (releaseProfile = r))
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profileResponse({ description: 'STALE PROFILE MUST NOT RENDER' })) })
      }
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{"code":"NOT_FOUND","message":"nf"}' })
    })
    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByText('Loading repository profile…')).toBeVisible()
    await page.getByRole('button', { name: /back to repositories/i }).click()
    await expect(page.getByRole('heading', { name: 'Repositories' })).toBeVisible()

    await page.waitForTimeout(150)
    // @ts-expect-error assigned in handler
    releaseProfile?.()
    await page.waitForTimeout(400)
    await expect(page.getByText('STALE PROFILE MUST NOT RENDER')).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Repositories' })).toBeVisible()
  })

  test('changing the branch select during an in-flight re-analyze does not desync the POST', async ({ page }) => {
    let refreshBody: unknown
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary()])) },
      { match: /\/repositories\/repo-1\/branches$/, handler: json(branches([{ name: 'master', is_default: true }, { name: 'develop' }, { name: 'release' }])) },
      { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse()) },
      {
        match: /\/repositories\/repo-1\/refresh$/,
        handler: async (route) => {
          refreshBody = route.request().postDataJSON()
          await new Promise((r) => setTimeout(r, 300))
          return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ ...profileResponse().profile, analysis_run_id: 'run-2', repository_id: 'repo-1', provider: 'github', status: 'QUEUED', name: 'Hello-World', source_url: 'x', selected_branch: null, commit_sha: null, error_code: null, error_message: null }) })
        },
      },
      { match: /\/analysis-runs\/run-2$/, handler: json(runStatus({ id: 'run-2', status: 'ANALYZING' })) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
    ])
    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
    await page.getByLabel('Branch').selectOption('develop')
    await page.getByRole('button', { name: /re-analyze this branch/i }).click()
    // the select is disabled while refreshing; the POST must carry 'develop'
    await expect(page.getByRole('heading', { name: /analyzing repository/i })).toBeVisible()
    expect(refreshBody).toEqual({ branch: 'develop' })
  })

  test('a burst of alternating repo clicks settles on the last one, with no duplicate render', async ({ page }) => {
    let detailCalls = 0
    await page.route(`${API}/api/v1/**`, async (route) => {
      const url = route.request().url()
      if (/\/repositories\?/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoList([repoSummary({ id: 'repo-1', owner: 'one', name: 'ONE' }), repoSummary({ id: 'repo-2', owner: 'two', name: 'TWO' })])) })
      if (/\/repositories\/repo-[12]$/.test(url)) {
        detailCalls++
        await new Promise((r) => setTimeout(r, 700)) // long enough that every click lands before the list unmounts
        const one = /repo-1$/.test(url)
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoDetail({ id: one ? 'repo-1' : 'repo-2', owner: one ? 'one' : 'two', name: one ? 'ONE' : 'TWO', latest_analysis_run: null })) })
      }
      if (/repo-1\/profile$/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profileResponse({ owner: 'one', repository_name: 'ONE' })) })
      if (/repo-2\/profile$/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profileResponse({ owner: 'two', repository_name: 'TWO' })) })
      if (/\/branches$/.test(url)) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(branches()) })
      return route.fulfill({ status: 404, contentType: 'application/json', body: '{"code":"NOT_FOUND","message":"nf"}' })
    })
    await page.goto('/')
    await expect(page.getByRole('button', { name: /one\/ONE/ })).toBeVisible()
    // dispatch raw click events so all 16 land inside the 700ms detail window on every engine
    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('.repository-card')) as HTMLElement[]
      const one = btns.find((b) => b.textContent?.includes('one/ONE'))
      const two = btns.find((b) => b.textContent?.includes('two/TWO'))
      if (!one || !two) throw new Error('cards not found: ' + btns.map((b) => b.textContent).join(' | '))
      for (let i = 0; i < 8; i++) {
        one.click()
        two.click()
      }
    })
    await expect(page.getByRole('heading', { name: /two\/TWO/ })).toBeVisible()
    await expect(page.getByRole('heading', { name: /one\/ONE/ })).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Languages' })).toHaveCount(1)
    // several redundant detail GETs were issued but the sequence guard renders only the last
    expect(detailCalls).toBeGreaterThan(1)
  })
})
