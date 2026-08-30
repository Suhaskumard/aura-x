import { describe, expect, it } from 'vitest'
// Vite serves the stylesheet source as a string with `?raw` -- no node:fs, and
// it stays in sync with what the app actually ships.
import appCss from './App.css?raw'
import indexCss from './index.css?raw'

/**
 * Regression guards for two classes of defect found during the frontend QA pass:
 *
 *  1. WCAG 2 AA contrast: `.muted` text (tagline, card descriptions, profile
 *     fact labels, "Branch:" line, empty states) was `--text` at `opacity: 0.8`,
 *     which renders as ~#898291 on #fff == 3.7:1 (needs 4.5:1). Same story for
 *     `.repository-card-meta`, `.profile-facts dt`, `.language-pct` and `.stage`.
 *     The fix is a solid `--text-muted` token with no opacity dimming.
 *
 *  2. Horizontal overflow: a long unbroken token in a repo description /
 *     dependency / language name / branch name / commit SHA / error message
 *     forced its flex/grid container wider than the viewport. The fix adds
 *     `overflow-wrap: anywhere` + `min-width: 0` on the content containers.
 */

/** pull the body of the first `selector { ... }` block, anchored to a line start
 *  so `button` does not match inside `.link-button` */
function ruleBody(css: string, selector: string): string {
  const re = new RegExp(`(^|\\n)${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{`, 'm')
  const m = re.exec(css)
  if (!m) throw new Error(`rule not found: ${selector}`)
  const start = css.indexOf('{', m.index)
  const end = css.indexOf('}', start)
  return css.slice(start + 1, end)
}

describe('contrast regression (light theme)', () => {
  it('defines a solid --text-muted token in both themes', () => {
    expect(indexCss).toMatch(/--text-muted:\s*#[0-9a-fA-F]{6}/)
    const darkBlock = indexCss.slice(indexCss.indexOf('prefers-color-scheme: dark'))
    expect(darkBlock).toMatch(/--text-muted:\s*#[0-9a-fA-F]{6}/)
  })

  it('.muted no longer dims text with opacity', () => {
    const body = ruleBody(appCss, '.muted')
    expect(body).not.toMatch(/opacity\s*:/)
    expect(body).toMatch(/color:\s*var\(--text-muted\)/)
  })

  for (const sel of ['.repository-card-meta', '.profile-facts dt', '.language-pct', '.stage']) {
    it(`${sel} uses the solid muted token, not opacity`, () => {
      const body = ruleBody(appCss, sel)
      expect(body, `${sel} still dims text via opacity`).not.toMatch(/opacity\s*:/)
      expect(body).toMatch(/var\(--text-muted\)/)
    })
  }

  it('the primary button colour is themeable (dark ink in dark mode, not white-on-lilac)', () => {
    expect(ruleBody(appCss, 'button')).toMatch(/color:\s*var\(--on-accent\)/)
    const darkBlock = indexCss.slice(indexCss.indexOf('prefers-color-scheme: dark'))
    expect(darkBlock).toMatch(/--on-accent:\s*#[0-9a-fA-F]{3,6}/)
  })
})

describe('overflow regression', () => {
  const mustWrap = [
    { css: appCss, sel: '.muted' },
    { css: appCss, sel: '.error-text' },
    { css: appCss, sel: '.repository-card-meta' },
    { css: appCss, sel: '.profile-facts dd' },
    { css: appCss, sel: '.language-name' },
    { css: indexCss, sel: 'code' },
  ]
  for (const { css, sel } of mustWrap) {
    it(`${sel} breaks long unbroken tokens (overflow-wrap: anywhere)`, () => {
      expect(ruleBody(css, sel)).toMatch(/overflow-wrap:\s*anywhere/)
    })
  }

  it('grid/flex item children opt out of the min-content floor (min-width: 0)', () => {
    expect(ruleBody(appCss, '.repository-cards li')).toMatch(/min-width:\s*0/)
    expect(ruleBody(appCss, '.repository-card')).toMatch(/min-width:\s*0/)
    expect(ruleBody(appCss, '.language-bars li')).toMatch(/min-width:\s*0/)
  })

  it('the repository-card grid track can shrink below 280px on narrow viewports', () => {
    expect(ruleBody(appCss, '.repository-cards')).toMatch(/minmax\(min\(280px,\s*100%\)/)
  })
})
