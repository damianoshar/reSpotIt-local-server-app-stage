/**
 * PostCSS pipeline — Tailwind + autoprefixer.
 *
 * Without this file Vite never runs Tailwind: the `@tailwind utilities`
 * directive in src/index.css compiled to nothing, so every utility class in
 * the JSX (grid, flex, gap-*, truncate, …) was a no-op in built assets.
 * Surfaced 2026-10-18 by the owner: the playlist dashboard grid fell back to
 * stacked full-width blocks. tailwindcss/autoprefixer were already listed in
 * devDependencies — only the config was missing.
 *
 * Note: index.css puts the @tailwind directives first and the hand-written
 * component styles after, so hand-written rules keep winning ties by order
 * (same specificity).
 */
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
