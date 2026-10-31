/**
 * Render entry for scripts/render-check.mjs.
 *
 * Rendered with react-dom/server so the whole component tree can be exercised
 * under Node without a browser. Effects do not run during render, so this checks
 * what the app *shows given a state* — mode-dependent chrome, props reaching the
 * right components — while verify-local-mode.mjs checks the data layer.
 */
import { createElement } from 'react'
import { renderToString } from 'react-dom/server'
import App from '../src/App.jsx'
import { DataSourceModal } from '../src/components/DataSourceModal.jsx'
import { SyncPanel } from '../src/components/SyncPanel.jsx'
import { SettingsView } from '../src/components/SettingsView.jsx'

export function renderApp() {
  return renderToString(createElement(App))
}

export function renderModal(ds) {
  return renderToString(
    createElement(DataSourceModal, { ds, onClose: () => {}, onToast: () => {} }),
  )
}

/** The sync panel with a pipeline/quick-job state built by the caller. */
export function renderSyncPanel({ pipeline, imagesJob = null, loadJob = null }) {
  return renderToString(
    createElement(SyncPanel, { pipeline, imagesJob, loadJob }),
  )
}

/** The Settings tab content (Backup + Server) with a caller-supplied ds. */
export function renderSettings(ds, props = {}) {
  return renderToString(
    createElement(SettingsView, {
      ds, onToast: () => {},
      autoExport: false, onToggleAutoExport: () => {},
      imagesJob: null, loadJob: null, pipelineRunning: false,
      ...props,
    }),
  )
}
