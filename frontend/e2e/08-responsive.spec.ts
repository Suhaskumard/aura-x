import { expect, test } from '@playwright/test'
import { branches, json, mockApi, profileResponse, repoDetail, repoList, repoSummary } from './helpers'

const VIEWPORTS = [
  { w: 320, h: 640, name: 'small-mobile' },
  { w: 375, h: 667, name: 'iphone-se' },
  { w: 390, h: 844, name: 'iphone-12' },
  { w: 768, h: 1024, name: 'tablet-portrait' },
  { w: 1024, h: 768, name: 'tablet-landscape' },
  { w: 1366, h: 768, name: 'laptop' },
  { w: 1440, h: 900, name: 'desktop' },
  { w: 1920, h: 1080, name: 'wide' },
]

// a long unbroken owner/name plus a long description, the classic layout-breaker
const NASTY = repoSummary({
  owner: 'organisation-with-a-really-long-slug',
  name: 'repository-name-that-simply-will-not-wrap-on-its-own-abcdefghijklmnop',
  description: 'A'.repeat(300),
  primary_language: 'TypeScriptWithAVeryLongMadeUpNameXYZ',
})

test.describe('responsive layout', () => {
  for (const vp of VIEWPORTS) {
    test(`${vp.name} (${vp.w}px): list + profile have no horizontal overflow and controls stay reachable`, async ({ page }) => {
      await page.setViewportSize({ width: vp.w, height: vp.h })
      await mockApi(page, [
        { match: /\/repositories\?/, handler: json(repoList([NASTY, repoSummary({ id: 'repo-2', owner: 'o2', name: 'n2' })])) },
        { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse({ dependencies: Array.from({ length: 40 }, (_, i) => `dependency-package-number-${i}`), description: 'D'.repeat(240) })) },
        { match: /\/repositories\/repo-1\/branches$/, handler: json(branches([{ name: 'master', is_default: true }, { name: 'a-very-long-feature-branch-name-that-keeps-going' }])) },
        { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
      ])

      // list view
      await page.goto('/')
      await expect(page.getByRole('button', { name: /organisation-with-a-really-long-slug/ })).toBeVisible()
      let overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, `list horizontal overflow at ${vp.w}px`).toBeLessThanOrEqual(1)

      // the submit button must be within the viewport box
      const btn = page.getByRole('button', { name: /analyze repository/i })
      const box = await btn.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.x).toBeGreaterThanOrEqual(-1)
      expect(box!.x + box!.width).toBeLessThanOrEqual(vp.w + 1)

      // profile view
      await page.getByRole('button', { name: /organisation-with-a-really-long-slug/ }).click()
      await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
      overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, `profile horizontal overflow at ${vp.w}px`).toBeLessThanOrEqual(1)

      // re-analyze controls reachable
      const reBtn = page.getByRole('button', { name: /re-analyze this branch/i })
      await expect(reBtn).toBeVisible()
      const rb = await reBtn.boundingBox()
      expect(rb!.x + rb!.width).toBeLessThanOrEqual(vp.w + 1)
    })
  }

  for (const zoom of [0.8, 1, 1.5, 2]) {
    test(`page zoom ${zoom * 100}% does not introduce horizontal overflow on the profile`, async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 800 })
      await mockApi(page, [
        { match: /\/repositories\?/, handler: json(repoList([repoSummary()])) },
        { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse({ dependencies: Array.from({ length: 30 }, (_, i) => `pkg-${i}`) })) },
        { match: /\/repositories\/repo-1\/branches$/, handler: json(branches()) },
        { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
      ])
      await page.goto('/')
      await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
      await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
      await page.evaluate((z) => ((document.body.style as CSSStyleDeclaration & { zoom: string }).zoom = String(z)), zoom)
      await page.waitForTimeout(100)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, `overflow at zoom ${zoom}`).toBeLessThanOrEqual(2)
    })
  }

  test('a 400-char unbroken branch name in the progress <code> does not overflow at 375px', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 700 })
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([])) },
      { match: /\/repositories\/github$/, handler: json({ repository_id: 'r1', provider: 'github', source_url: 'x', name: 'n', owner: 'o', selected_branch: null, commit_sha: null, status: 'QUEUED', analysis_run_id: 'run-1', error_code: null, error_message: null }, 202) },
      { match: /\/analysis-runs\/run-1$/, handler: json({ id: 'run-1', repository_id: 'r1', status: 'CLONING', branch_name: 'x'.repeat(400), commit_sha: null, error_code: null, error_message: null, started_at: '2024-01-01T00:00:00Z', completed_at: null }) },
    ])
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill('https://github.com/o/n')
    await page.getByRole('button', { name: /analyze repository/i }).click()
    await expect(page.getByRole('heading', { name: /analyzing repository/i })).toBeVisible()
    await expect(page.locator('code')).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)
  })

  test('resizing from desktop to 320px mid-session keeps the layout intact', async ({ page }) => {
    await mockApi(page, [{ match: /\/repositories\?/, handler: json(repoList([NASTY])) }])
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto('/')
    await expect(page.getByRole('button', { name: /organisation-with-a-really-long-slug/ })).toBeVisible()
    for (const w of [1024, 768, 480, 375, 320]) {
      await page.setViewportSize({ width: w, height: 800 })
      await page.waitForTimeout(60)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, `overflow after resize to ${w}px`).toBeLessThanOrEqual(1)
    }
  })
})
