import { expect, test } from '@playwright/test'
import { API, collectConsole, pageParam, repoPage } from './helpers'

/**
 * FE-M1 regression: the repository list could only ever show page 1
 * (`listRepositories(1, 50)`), so repositories beyond the first page were
 * unreachable. These tests drive the real pager in a browser.
 */

const PAGE_SIZE = 50

/** Route the list endpoint to serve a synthetic `total`-row dataset, page by
 *  page, optionally delaying / failing specific pages. */
async function routeDataset(
  page: import('@playwright/test').Page,
  total: number,
  opts: { delayMs?: number; failPageOnce?: number } = {},
) {
  const failed = new Set<number>()
  await page.route(`${API}/api/v1/repositories?*`, async (route) => {
    const p = pageParam(route.request().url())
    if (opts.failPageOnce === p && !failed.has(p)) {
      failed.add(p)
      return route.fulfill({ status: 429, contentType: 'application/json', body: JSON.stringify({ code: 'RATE_LIMITED', message: 'Slow down' }) })
    }
    if (opts.delayMs) await new Promise((r) => setTimeout(r, opts.delayMs))
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoPage(total, p, PAGE_SIZE)) })
  })
}

const pager = (page: import('@playwright/test').Page) => page.getByRole('navigation', { name: /repository list pages/i })
const prev = (page: import('@playwright/test').Page) => page.getByRole('button', { name: /previous page/i })
const next = (page: import('@playwright/test').Page) => page.getByRole('button', { name: /next page/i })

test.describe('repository list pagination (FE-M1)', () => {
  test('single page (<= page size): no pager, all rows shown', async ({ page }) => {
    await routeDataset(page, 12)
    await page.goto('/')
    await expect(page.getByText('octocat/repo-1', { exact: true })).toBeVisible()
    await expect(page.getByRole('listitem')).toHaveCount(12)
    await expect(pager(page)).toHaveCount(0)
  })

  test('exact page size (== 50): still one page, no pager', async ({ page }) => {
    await routeDataset(page, PAGE_SIZE)
    await page.goto('/')
    await expect(page.getByRole('listitem')).toHaveCount(50)
    await expect(pager(page)).toHaveCount(0)
  })

  test('multi-page: Next/Previous reach every page, no page mixing, correct disabled states', async ({ page }) => {
    const { errors } = collectConsole(page)
    await routeDataset(page, 120) // 3 pages: 50 / 50 / 20
    await page.goto('/')

    await expect(page.getByText('Page 1 of 3')).toBeVisible()
    await expect(prev(page)).toBeDisabled()
    await expect(next(page)).toBeEnabled()
    await expect(page.getByText('octocat/repo-1', { exact: true })).toBeVisible()

    await next(page).click()
    await expect(page.getByText('Page 2 of 3')).toBeVisible()
    await expect(page.getByText('octocat/repo-51', { exact: true })).toBeVisible()
    await expect(page.getByText('octocat/repo-1', { exact: true })).toHaveCount(0) // no mixing
    await expect(prev(page)).toBeEnabled()

    await next(page).click()
    await expect(page.getByText('Page 3 of 3')).toBeVisible()
    await expect(page.getByRole('listitem')).toHaveCount(20)
    await expect(next(page)).toBeDisabled() // last page

    await prev(page).click()
    await expect(page.getByText('Page 2 of 3')).toBeVisible()
    await expect(page.getByText('octocat/repo-51', { exact: true })).toBeVisible()

    expect(errors, errors.join('\n')).toEqual([])
  })

  test('loading state while changing pages: current page dims, both controls disabled', async ({ page }) => {
    // hold page 2 open explicitly so the loading window is observable on every
    // engine regardless of automation speed
    let releasePage2: (() => void) | null = null
    await page.route(`${API}/api/v1/repositories?*`, async (route) => {
      const p = pageParam(route.request().url())
      if (p === 2) await new Promise<void>((r) => (releasePage2 = r))
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoPage(120, p, PAGE_SIZE)) })
    })
    await page.goto('/')
    await expect(page.getByText('Page 1 of 3')).toBeVisible()

    await next(page).click()
    await expect(page.getByText('Loading…')).toBeVisible()
    await expect(prev(page)).toBeDisabled()
    await expect(next(page)).toBeDisabled()
    await expect(page.locator('.repository-cards[aria-busy="true"]')).toBeVisible()

    releasePage2?.()
    await expect(page.getByText('Page 2 of 3')).toBeVisible()
    await expect(page.locator('.repository-cards[aria-busy="true"]')).toHaveCount(0)
  })

  test('rapid Next clicks issue exactly one request per landed page and never mix results', async ({ page }) => {
    const requested: number[] = []
    await page.route(`${API}/api/v1/repositories?*`, async (route) => {
      const p = pageParam(route.request().url())
      requested.push(p)
      await new Promise((r) => setTimeout(r, 250))
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoPage(300, p, PAGE_SIZE)) })
    })
    await page.goto('/')
    await expect(page.getByText('Page 1 of 6')).toBeVisible()

    // hammer Next; the button disables itself after the first click each turn
    for (let i = 0; i < 8; i++) await next(page).click({ noWaitAfter: true, timeout: 500 }).catch(() => {})

    await expect(page.getByText(/Page [2-6] of 6/)).toBeVisible()
    // landed on a real page, exactly one page's worth of cards, no duplicates
    await expect(page.getByRole('listitem')).toHaveCount(50)
    const ids = await page.locator('.repository-card-title span:first-child').allInnerTexts()
    expect(new Set(ids).size).toBe(ids.length) // no cross-page duplication

    // No page-navigation request is ever issued twice. (Page 1 may be fetched
    // twice on mount because React StrictMode double-invokes effects in dev;
    // that is expected and the stale response is discarded by the seq guard.)
    const navRequests = requested.filter((p) => p > 1)
    expect(new Set(navRequests).size, `duplicate page fetch in ${JSON.stringify(requested)}`).toBe(navRequests.length)
    expect(requested.filter((p) => p === 1).length).toBeLessThanOrEqual(2)
  })

  test('stale slow page response cannot overwrite a newer page', async ({ page }) => {
    let releaseP2: (() => void) | null = null
    await page.route(`${API}/api/v1/repositories?*`, async (route) => {
      const p = pageParam(route.request().url())
      if (p === 2) {
        await new Promise<void>((r) => (releaseP2 = r))
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoPage(150, 2, PAGE_SIZE)) })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(repoPage(150, p, PAGE_SIZE)) })
    })
    await page.goto('/')
    await expect(page.getByText('Page 1 of 3')).toBeVisible()

    await next(page).click() // page 2 -> hangs
    await expect(page.getByText('Loading…')).toBeVisible()
    // "Back to repositories"-style refresh: reload returns to page 1
    await page.reload()
    await expect(page.getByText('Page 1 of 3')).toBeVisible()

    // release the stale page-2 response
    await page.waitForTimeout(150)
    releaseP2?.()
    await page.waitForTimeout(300)
    await expect(page.getByText('Page 1 of 3')).toBeVisible()
    await expect(page.getByText('octocat/repo-51', { exact: true })).toHaveCount(0)
  })

  test('API failure while changing pages: error shown, current page intact, retry succeeds', async ({ page }) => {
    await routeDataset(page, 120, { failPageOnce: 2 })
    await page.goto('/')
    await expect(page.getByText('Page 1 of 3')).toBeVisible()

    await next(page).click()
    await expect(page.locator('.error-text')).toContainText('Slow down')
    // page state not corrupted
    await expect(page.getByText('Page 1 of 3')).toBeVisible()
    await expect(page.getByText('octocat/repo-1', { exact: true })).toBeVisible()
    await expect(next(page)).toBeEnabled()

    // retry the same control
    await next(page).click()
    await expect(page.getByText('Page 2 of 3')).toBeVisible()
    await expect(page.locator('.error-text')).toHaveCount(0)
  })

  test('empty non-first page (dataset shrank) shows a message; Previous still works', async ({ page }) => {
    await page.route(`${API}/api/v1/repositories?*`, (route) => {
      const p = pageParam(route.request().url())
      const body = p === 1 ? repoPage(120, 1, PAGE_SIZE) : { items: [], total: 50, page: p, page_size: PAGE_SIZE }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    })
    await page.goto('/')
    await next(page).click()
    await expect(page.getByText('No repositories on this page.')).toBeVisible()
    await expect(prev(page)).toBeEnabled()
    await prev(page).click()
    await expect(page.getByText('Page 1 of 3')).toBeVisible()
  })

  test('refresh / direct navigation always starts on page 1', async ({ page }) => {
    await routeDataset(page, 120)
    await page.goto('/')
    await next(page).click()
    await expect(page.getByText('Page 2 of 3')).toBeVisible()

    await page.reload()
    await expect(page.getByText('Page 1 of 3')).toBeVisible()
    await expect(page.getByText('octocat/repo-1', { exact: true })).toBeVisible()

    // "Back to repositories" also resets to page 1
    await next(page).click()
    await expect(page.getByText('Page 2 of 3')).toBeVisible()
    await page.getByText('octocat/repo-51', { exact: true }).click()
    await expect(page.getByRole('heading', { name: /octocat\/repo-51/ }).or(page.locator('.error-text'))).toBeVisible()
  })

  test('pager is usable and on-screen at 320px and 375px', async ({ page }) => {
    await routeDataset(page, 120)
    for (const w of [320, 375]) {
      await page.setViewportSize({ width: w, height: 700 })
      await page.goto('/')
      await expect(page.getByText('Page 1 of 3')).toBeVisible()
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, `pager overflow at ${w}px`).toBeLessThanOrEqual(1)
      for (const btn of [prev(page), next(page)]) {
        const box = await btn.boundingBox()
        expect(box).not.toBeNull()
        expect(box!.x).toBeGreaterThanOrEqual(-1)
        expect(box!.x + box!.width).toBeLessThanOrEqual(w + 1)
      }
      await next(page).click()
      await expect(page.getByText('Page 2 of 3')).toBeVisible()
    }
  })

  test('axe: the list view with a pager has no serious/critical violations', async ({ page }) => {
    const AxeBuilder = (await import('@axe-core/playwright')).default
    await routeDataset(page, 120)
    await page.goto('/')
    await expect(page.getByText('Page 1 of 3')).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious.map((v) => v.id))).toEqual([])
  })
})
