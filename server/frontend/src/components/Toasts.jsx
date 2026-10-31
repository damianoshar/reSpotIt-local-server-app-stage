/**
 * Toasts — stacked auto-dismissing notifications (success + error).
 */
export function Toasts({ toasts }) {
  if (!toasts.length) return null

  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {toasts.map(t => (
        <div key={t.id} className={'toast ' + (t.ok ? 'toast-ok' : 'toast-err')}>
          {t.msg}
        </div>
      ))}
    </div>
  )
}
