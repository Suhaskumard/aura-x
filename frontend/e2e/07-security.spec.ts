import { expect, test } from '@playwright/test'
import { branches, collectConsole, json, mockApi, profileResponse, repoDetail, repoList, repoSummary, runStatus, trapDialogs } from './helpers'

const PAYLOADS = {
  script: '<script>window.__xss=1</script>',
  img: '<img src=x onerror="window.__xss=1">',
  svg: '"><svg onload="window.__xss=1">',
  js: 'javascript:alert(1)',
}
const HOSTILE = `${PAYLOADS.script}${PAYLOADS.img}${PAYLOADS.svg}`

async function assertInert(page: import('@playwright/test').Page) {
  const fired = await page.evaluate(() => (window as unknown as { __xss?: unknown }).__xss)
  expect(fired, 'no XSS payload executed').toBeUndefined()
  await expect(page.locator('img[onerror]')).toHaveCount(0)
  await expect(page.locator('svg[onload]')).toHaveCount(0)
  // no attacker <script> got parsed into the document
  const injected = await page.evaluate(() => Array.from(document.scripts).some((s) => s.textContent?.includes('__xss')))
  expect(injected, 'no attacker <script> in the DOM').toBe(false)
}

test.describe('frontend security - XSS / unsafe rendering', () => {
  test('hostile repository metadata in the list renders as inert escaped text', async ({ page }) => {
    const dialogs = trapDialogs(page)
    await mockApi(page, [
      {
        match: /\/repositories\?/,
        handler: json(
          repoList([
            repoSummary({ owner: `own${PAYLOADS.script}`, name: `nm${PAYLOADS.img}`, description: `desc ${PAYLOADS.svg}`, primary_language: `lang${PAYLOADS.img}` }),
          ]),
        ),
      },
    ])
    await page.goto('/')
    await expect(page.getByText(/desc "><svg onload=/)).toBeVisible() // shown as literal text
    await assertInert(page)
    expect(dialogs).toEqual([])
  })

  test('hostile error_code / error_message in the failure view are inert', async ({ page }) => {
    const dialogs = trapDialogs(page)
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary({ latest_status: 'FAILED' })])) },
      {
        match: /\/repositories\/repo-1$/,
        handler: json(
          repoDetail({
            latest_analysis_run: {
              id: 'run-1',
              status: 'FAILED',
              branch_name: null,
              commit_sha: null,
              error_code: `CODE${PAYLOADS.img}`,
              error_message: `boom ${HOSTILE}`,
              started_at: '2024-01-01T00:00:00Z',
              completed_at: '2024-01-01T00:01:00Z',
            },
          }),
        ),
      },
    ])
    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: /analysis failed/i })).toBeVisible()
    await expect(page.getByText(/boom <script>/)).toBeVisible()
    await assertInert(page)
    expect(dialogs).toEqual([])
  })

  test('hostile profile fields (description, language keys, deps, frameworks) are inert', async ({ page }) => {
    const dialogs = trapDialogs(page)
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary()])) },
      {
        match: /\/repositories\/repo-1\/profile$/,
        handler: json(
          profileResponse({
            description: `about ${HOSTILE}`,
            languages: { [`Py${PAYLOADS.script}`]: 100, [`Js${PAYLOADS.img}`]: 50 },
            dependencies: [`pkg${PAYLOADS.script}`, `dep${PAYLOADS.svg}`],
            test_frameworks: [`fw${PAYLOADS.img}`],
            selected_branch: `br${PAYLOADS.img}`,
            commit_sha: `${PAYLOADS.script}deadbeef`,
          }),
        ),
      },
      { match: /\/repositories\/repo-1\/branches$/, handler: json(branches([{ name: `br${PAYLOADS.img}`, is_default: true }])) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
    ])
    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
    await expect(page.getByText(/pkg<script>/)).toBeVisible()
    await assertInert(page)
    expect(dialogs).toEqual([])
  })

  test('hostile branch name in the <select> stays inert and round-trips safely in the POST', async ({ page }) => {
    let refreshBody: unknown
    const evil = `feature/${PAYLOADS.img}`
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([repoSummary()])) },
      { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse({ selected_branch: evil, default_branch: evil })) },
      { match: /\/repositories\/repo-1\/branches$/, handler: json(branches([{ name: evil, is_default: true }])) },
      {
        match: /\/repositories\/repo-1\/refresh$/,
        handler: (route) => {
          refreshBody = route.request().postDataJSON()
          return route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ repository_id: 'repo-1', provider: 'github', source_url: 'x', name: 'n', owner: 'o', selected_branch: null, commit_sha: null, status: 'QUEUED', analysis_run_id: 'run-9', error_code: null, error_message: null }) })
        },
      },
      { match: /\/analysis-runs\/run-9$/, handler: json(runStatus({ id: 'run-9', status: 'ANALYZING' })) },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
    ])
    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()
    await assertInert(page)
    await page.getByRole('button', { name: /re-analyze this branch/i }).click()
    await expect(page.getByRole('heading', { name: /analyzing repository/i })).toBeVisible()
    expect(refreshBody).toEqual({ branch: evil })
  })

  test('no tokens / secrets and no backend stack traces are exposed in the DOM or console', async ({ page }) => {
    const { errors, warnings } = collectConsole(page)
    await mockApi(page, [
      {
        match: /\/repositories\?/,
        // a backend that (wrongly) leaked internals - the frontend must not amplify it,
        // but we at least assert the frontend itself adds no secret material
        handler: json(repoList([repoSummary()])),
      },
      { match: /\/repositories\/repo-1$/, handler: json(repoDetail()) },
      { match: /\/repositories\/repo-1\/profile$/, handler: json(profileResponse()) },
      { match: /\/repositories\/repo-1\/branches$/, handler: json(branches()) },
    ])
    await page.goto('/')
    await page.getByRole('button', { name: /octocat\/Hello-World/ }).click()
    await expect(page.getByRole('heading', { name: 'Languages' })).toBeVisible()

    const html = await page.content()
    expect(html).not.toMatch(/ghp_[A-Za-z0-9]{20,}/) // GitHub PAT
    expect(html).not.toMatch(/Authorization:\s*Bearer/i)
    expect(html).not.toMatch(/Traceback \(most recent call last\)/)
    expect(html).not.toMatch(/[A-Za-z]:\\Users\\[^"'<>\s]+\.py/) // server file paths
    expect(errors, errors.join('\n')).toEqual([])
    // React key/dev warnings would show here
    expect(warnings.filter((w) => /Warning:|key/i.test(w)), warnings.join('\n')).toEqual([])
  })

  test('a malicious javascript: URL typed into the form is never turned into a link/navigation', async ({ page }) => {
    await mockApi(page, [
      { match: /\/repositories\?/, handler: json(repoList([])) },
      { match: /\/repositories\/github$/, handler: (route) => route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ code: 'INVALID_REPOSITORY_URL', message: 'nope' }) }) },
    ])
    await page.goto('/')
    await page.getByLabel(/repository url/i).fill(PAYLOADS.js)
    await page.getByRole('button', { name: /analyze repository/i }).click()
    await expect(page.getByRole('alert')).toBeVisible()
    // the value is only ever an input value, never an href
    await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0)
  })
})
