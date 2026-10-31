/**
 * check-css-build.mjs — regression pin: the built stylesheet must actually
 * contain the Tailwind utilities the JSX relies on.
 *
 * Background (2026-10-18): postcss.config.js was missing, so Vite never ran
 * Tailwind — `@tailwind utilities` in src/index.css compiled to nothing and
 * every utility class in the JSX (grid, flex, gap-*, truncate, …) was a
 * no-op in the built CSS. The app still "looked fine" on its hand-written
 * styles, so nothing caught it. This check builds the app and fails if the
 * utilities are absent from dist/assets/*.css.
 */
import { execSync } from 'node:child_process'
import { readdirSync, readFileSync } from 'node:fs'

execSync('npm run build', { stdio: 'inherit' })

const assets = new URL('../dist/assets/', import.meta.url)
const cssFiles = readdirSync(assets).filter(f => f.endsWith('.css'))
if (cssFiles.length !== 1) {
  console.error(`expected one built stylesheet, found ${cssFiles.length}`)
  process.exit(1)
}
const css = readFileSync(new URL(cssFiles[0], assets), 'utf8')

let checks = 0
const failed = []
function check(name, ok) {
  checks += 1
  if (!ok) failed.push(name)
  console.log((ok ? 'PASS  ' : 'FAIL  ') + name)
}

check('built css carries the Tailwind grid utility (.grid{display:grid})',
      css.includes('.grid{display:grid}'))
check('built css carries the Tailwind flex utility (.flex{display:flex})',
      css.includes('.flex{display:flex}'))
check('built css is bigger than the hand-written base (utilities compiled)',
      css.length > 12000)

if (failed.length) {
  console.log(`\nCSS-BUILD FAILED - ${checks - failed.length}/${checks} checks`)
  console.log('missing:', failed.join('; '))
  console.log('hint: is frontend/postcss.config.js present and listing tailwindcss?')
  process.exit(1)
}
console.log(`\nCSS-BUILD OK - ${checks} checks (Tailwind utilities present in the built stylesheet)`)
