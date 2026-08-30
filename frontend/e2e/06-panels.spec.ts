import { expect, test } from '@playwright/test'
import { branches, collectConsole, json, mockApi, profileResponse, repoDetail, repoList, repoSummary } from './helpers'

async function openProfile(page: import('@playwright/test').Page, profileOver: Record<string, unknown> = {}, branchList = branches()) {
  await mockApi(page, [
    { match: /\/repositories\?/, handler: json(repoList([repoSummary()])) },
    { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse(profileOver)) },
    { match: /\/repositories\/repo-1\/branches$/, handler: json(branchList) },
    { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
  ])
  await page.goto('/')
  await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
  await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
}

test.describe('output panels - profile dashboard', () => {
  test('empty sections render their explicit empty states', async ({ page }) => {
    await openProfile(page, { languages: {}, test_frameworks: [], dependencies: [] })
    await expect(page.getByText('No languages detected.')).toBeVisible()
    await expect(page.getByText('No test frameworks detected.')).toBeVisible()
    await expect(page.getByText('No dependency manifests detected.')).toBeVisible()
    await expect(page.getByRole('heading', { name: /Dependencies \(0\)/ })).toBeVisible()
  })

  test('dependency list is capped at 24 with a "+N more" pill', async ({ page }) => {
    const deps = Array.from({ length: 60 }, (_, i) => `dep-${i}`)
    await openProfile(page, { dependencies: deps })
    await expect(page.getByRole('heading', { name: 'Dependencies (60)' })).toBeVisible()
    const pills = page.locator('.pill-list').last().locator('li')
    await expect(pills).toHaveCount(25) // 24 + "+36 more"
    await expect(page.getByText('+36 more')).toBeVisible()
    await expect(page.getByText('dep-24', { exact: true })).toHaveCount(0)
  })

  test('very large numbers are formatted (thousands separators, byte units)', async ({ page }) => {
    await openProfile(page, {
      file_inventory: { total_files: 1_234_567, total_size_bytes: 5_368_709_120, by_category: {} },
      stargazers_count: 987654,
      git_history_summary: { commit_count: 200, most_recent_commit_at: null },
    })
    // toLocaleString in the test's default (en-US) locale
    await expect(page.getByText(/1,234,567/)).toBeVisible()
    await expect(page.getByText(/5120\.0 MB|5\.0 GB/)).toBeVisible() // formatBytes only goes up to MB
  })

  test('MB-scale total size uses the MB branch of formatBytes', async ({ page }) => {
    await openProfile(page, { file_inventory: { total_files: 10, total_size_bytes: 3_500_000, by_category: {} } })
    await expect(page.getByText('3.3 MB')).toBeVisible()
  })

  test('null numeric fields fall back to an em dash, not "null" or NaN', async ({ page }) => {
    await openProfile(page, {
      visibility: null,
      stargazers_count: null,
      forks_count: null,
      commit_sha: null,
      selected_branch: null,
    })
    const facts = page.locator('.profile-facts')
    await expect(facts).not.toContainText('null')
    await expect(facts).not.toContainText('NaN')
    await expect(facts).not.toContainText('undefined')
    // Commit dd shows the dash
    await expect(page.locator('.profile-facts code')).toHaveText('—')
  })

  test('a very long unbroken dependency / language token does not cause horizontal page overflow', async ({ page }) => {
    const longTok = 'x'.repeat(400)
    await openProfile(page, {
      dependencies: [longTok],
      languages: { [`Lang${'y'.repeat(300)}`]: 1000 },
      description: 'z'.repeat(600),
    })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, 'no horizontal page overflow with 400-char tokens').toBeLessThanOrEqual(1)
  })

  test('Unicode / emoji / RTL in profile fields render as text without breaking layout', async ({ page }) => {
    await openProfile(page, {
      description: 'مرحبا 🌍 café — 日本語 — ✅',
      languages: { 'C𝕏 ✨': 5000, 'Ｆｕｌｌｗｉｄｔｈ': 2000 },
      test_frameworks: ['pytest ✅', '日本語テスト'],
      dependencies: ['@scope/pkg-🚀', 'lib—dash'],
    })
    await expect(page.getByText('café', { exact: false })).toBeVisible()
    await expect(page.getByText('C𝕏 ✨')).toBeVisible()
    await expect(page.getByText('pytest ✅')).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)
  })

  test('language percentages sum to ~100 and bar widths are within 0-100%', async ({ page }) => {
    await openProfile(page, { languages: { A: 3, B: 1, C: 1 } })
    const fills = page.locator('.language-bar-fill')
    const n = await fills.count()
    expect(n).toBe(3)
    for (let i = 0; i < n; i++) {
      const w = await fills.nth(i).evaluate((el) => (el as HTMLElement).style.width)
      const pct = parseFloat(w)
      expect(pct).toBeGreaterThanOrEqual(0)
      expect(pct).toBeLessThanOrEqual(100)
    }
  })

  test('switching from one profile to another leaves no stale content', async ({ page }) => {
    const { errors } = collectConsole(page)
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary({ id: 'repo-1', owner: 'one', name: 'ONE' }), repoSummary({ id: 'repo-2', owner: 'two', name: 'TWO' })])) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail({ id: 'repo-1', owner: 'one', name: 'ONE', latest_analysis_run: null })) },
      { match: /\/repositories\/repo-2$/, handler: json(repoDetail({ id: 'repo-2', owner: 'two', name: 'TWO', latest_analysis_run: null })) },
      { match: /repo-1\/profile$/, handler: json(profileResponse({ owner: 'one', repository_name: 'ONE', dependencies: ['only-in-one'], test_frameworks: ['jest'] })) },
      { match: /repo-2\/profile$/, handler: json(profileResponse({ owner: 'two', repository_name: 'TWO', dependencies: ['only-in-two'], test_frameworks: ['vitest'] })) },
      { match: /\/branches$/, handler: json(branches()) },
    ])
    await page.goto('/')
    await page.getByRole('button', { name: /one\/ONE/ }).click()
    await expect(page.getByText('only-in-one')).toBeVisible()
    await page.getByRole('button', { name: /back to repositories/i }).click()
    await page.getByRole('button', { name: /two\/TWO/ }).click()
    await expect(page.getByText('only-in-two')).toBeVisible()
    await expect(page.getByText('only-in-one')).toHaveCount(0)
    await expect(page.getByText('jest', { exact: true })).toHaveCount(0)
    expect(errors, errors.join('\n')).toEqual([])
  })
})
