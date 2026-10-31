/**
 * Server-side CSV export as a browser download.
 *
 * Export routes are JWT-gated, so the old plain anchor-href link cannot carry
 * the Authorization header. The download goes through api.exportCsv() instead
 * (fetch → blob → object-URL click), which is one place so that the Export
 * button and the auto-export-after-sync trigger download exactly the same way
 * (and record the same server-side history row).
 *
 * The blob click gives no completion signal; callers that show the export
 * history refresh it on a delay instead.
 */
import { api } from '../api/client'

export async function downloadLibraryCsv() {
  await api.exportCsv()
}
