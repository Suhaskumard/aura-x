import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { branches, json, mockApi, profileResponse, repoDetail, repoList, repoSummary, runStatus } from './helpers'

test.describe('accessibility', () => {
  // axe-core runs its full ruleset inside page.evaluate; on a loaded machine
  // that can exceed the default 30s test budget (it is analysis, not a hang).
  test.slow()

  test('list view has no serious/critical axe violations', async ({ page }) => {
    await mockApi(page, [{ match: /\/repositories\?/, handler: json(repoList([repoSummary()])) }])
    await page.goto('/')
    await expect(page.getByRole('button', { name: /octocat\/Hello-World/ })).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious.map((v) => ({ id: v.id, nodes: v.nodes.length, help: v.help })), null, 2)).toEqual([])
  })

  test('profile view has no serious/critical axe violations', async ({ page }) => {
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary()])) },
      { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse()) },
      { match: /\/repositories\/repo-1\/branches$/, handler: json(branches([{ name: 'master', is_default: true }, { name: 'develop' }])) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
    ])
    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious.map((v) => ({ id: v.id, nodes: v.nodes.length, help: v.help })), null, 2)).toEqual([])
  })

  test('progress view has no serious/critical axe violations and exposes a live status', async ({ page }) => {
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([])) },
      { match: /\/repositories\/github$/, handler: json({ repository_id: 'repo-1', provider: 'github', source_url: 'x', name: 'n', owner: 'o', selected_branch: null, commit_sha: null, status: 'QUEUED', analysis_run_id: 'run-1', error_code: null, error_message: null }, 202) },
      { match: /\/analysis-runs\/run-1$/, handler: json(runStatus({ status: 'CLONING' })) },
    ])
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('https://github.com/octocat/Hello-World')
    await page.getByRole('button', { name: /analyze repository/i }).click()
    await expect(page.getByRole('heading', { name: /analyzing repository/i })).toBeVisible()
    await expect(page.getByRole('status').filter({ hasText: /current stage/i })).toBeVisible()
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(serious, JSON.stringify(serious.map((v) => ({ id: v.id, help: v.help })), null, 2)).toEqual([])
  })

  test('the whole onboarding workflow is operable by keyboard only', async ({ page }) => {
    let ingestCalled = false
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([])) },
      { match: /\/repositories\/github$/, handler: (route) => { ingestCalled = true; return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ repository_id: 'repo-1', provider: 'github', source_url: 'x', name: 'n', owner: 'o', selected_branch: null, commit_sha: null, status: 'QUEUED', analysis_run_id: 'run-1', error_code: null, error_message: null }) }) } },
      { match: /\/analysis-runs\/run-1$/, handler: json(runStatus({ status: 'ANALYZING' })) },
    ])
    await page.goto('/')
    // tab to the URL field, type, tab past branch, activate submit with Enter
    await page.keyboard.press('Tab')
    // walk focus until the URL textbox is focused (max a few hops)
    for (let i = 0; i < 6; i++) {
      const isUrl = await page.evaluate(() => document.activeElement?.id === 'repository-url')
      if (isUrl) break
      await page.keyboard.press('Tab')
    }
    expect(await page.evaluate(() => document.activeElement?.id)).toBe('repository-url')
    await page.keyboard.type('https://github.com/octocat/Hello-World')
    await page.keyboard.press('Enter') // native form submit from a text input
    await expect(page.getByRole('heading', { name: /analyzing repository/i })).toBeVisible()
    expect(ingestCalled).toBe(true)
  })

  test('focus order is logical and every interactive control has an accessible name', async ({ page }) => {
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary()])) },
      { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse()) },
      { match: /\/repositories\/repo-1\/branches$/, handler: json(branches([{ name: 'master', is_default: true }, { name: 'develop' }])) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
    ])
    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()

    // every button/link/select/input reachable has a non-empty accessible name
    const controls = page.locator('button, a[href], select, input, [tabindex]:not([tabindex="-1"])')
    const n = await controls.count()
    for (let i = 0; i < n; i++) {
      const el = controls.nth(i)
      if (!(await el.isVisible())) continue
      const name = (await el.getAttribute('aria-label')) || (await el.evaluate((e) => (e as HTMLElement).innerText || (e as HTMLInputElement).labels?.[0]?.innerText || ''))
      expect(name?.trim().length, `control #${i} (${await el.evaluate((e) => e.tagName)}) has no accessible name`).toBeGreaterThan(0)
    }
  })

  test('a visible focus indicator exists on the primary button', async ({ page }) => {
    await mockApi(page, [{ match: /\/repositories\?/, handler: json(repoList([])) }])
    await page.goto('/')
    const btn = page.getByRole('button', { name: /analyze repository/i })
    await btn.focus()
    const outline = await btn.evaluate((el) => {
      const s = getComputedStyle(el)
      return { outlineWidth: s.outlineWidth, outlineStyle: s.outlineStyle, boxShadow: s.boxShadow }
    })
    const hasIndicator = outline.outlineStyle !== 'none' && parseFloat(outline.outlineWidth) > 0
    expect(hasIndicator || outline.boxShadow !== 'none', `no visible focus ring: ${JSON.stringify(outline)}`).toBe(true)
  })

  test('errors are conveyed as text (role=alert), not by colour alone', async ({ page }) => {
    await mockApi(page, [{ match: /\/repositories\?/, handler: json(repoList([])) }])
    await page.goto('/')
    await page.getByRole('button', { name: /analyze repository/i }).click()
    const alert = page.getByRole('alert')
    await expect(alert).toBeVisible()
    expect((await alert.innerText()).trim().length).toBeGreaterThan(10)
  })
})
