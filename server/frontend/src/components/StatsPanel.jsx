/**
 * StatsPanel — library breakdown views (top genres / top artists / year
 * histogram). Reads the aggregate keys of GET /api/v1/albums/stats; cards
 * with no data render nothing. Collapsible; state lives in App prefs.
 */
import { useState } from 'react'

function BarRow({ name, count, max }) {
  const pct = max > 0 ? Math.round((count / max) * 100) : 0
  return (
    <div className="flex items-center gap-2 py-1">
      <span className="font-mono text-xs text-ink truncate flex-1" title={name}>
        {name || '—'}
      </span>
      <div className="w-24 sm:w-32 h-2 rounded bg-border/40 overflow-hidden flex-shrink-0">
        <div className="h-full rounded bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs text-muted w-12 text-right flex-shrink-0">
        {count.toLocaleString()}
      </span>
    </div>
  )
}

function Card({ title, children }) {
  return (
    <div className="rounded-lg border border-border bg-panel px-4 py-3 min-w-0">
      <div className="font-mono text-[0.65rem] uppercase tracking-widest text-muted mb-2">
        {title}
      </div>
      {children}
    </div>
  )
}

export function StatsPanel({ stats, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)

  const genres = stats?.topGenres ?? []
  const artists = stats?.topArtists ?? []
  const years = (stats?.albumsByYear ?? []).filter(y => y && y.year > 0)
  const hasAny = genres.length > 0 || artists.length > 0 || years.length > 0

  if (!stats || !hasAny) return null

  const maxGenre = Math.max(1, ...genres.map(g => g.count ?? 0))
  const maxArtist = Math.max(1, ...artists.map(a => a.count ?? 0))
  const maxYear = Math.max(1, ...years.map(y => y.count ?? 0))

  return (
    <div className="mb-5">
      <button
        className="btn btn-ghost btn-sm mb-2"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
      >
        {open ? '▾' : '▸'} Stats breakdown
      </button>

      {open && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          <Card title={`Top genres (${genres.length})`}>
            {genres.map(g => (
              <BarRow key={g.name} name={g.name} count={g.count ?? 0} max={maxGenre} />
            ))}
          </Card>

          <Card title={`Top artists (${artists.length})`}>
            {artists.map(a => (
              <BarRow key={a.name} name={a.name} count={a.count ?? 0} max={maxArtist} />
            ))}
          </Card>

          <Card title="Albums by year">
            <div
              className="flex items-end gap-[2px] h-28 mt-1"
              role="img"
              aria-label="Albums per year histogram"
            >
              {years.map(y => (
                <div
                  key={y.year}
                  title={`${y.year}: ${y.count} album${y.count !== 1 ? 's' : ''}`}
                  className="flex-1 rounded-t bg-accent/80 min-w-[2px]"
                  style={{ height: `${Math.max(3, Math.round((y.count / maxYear) * 100))}%` }}
                />
              ))}
            </div>
            {years.length > 0 && (
              <div className="flex justify-between font-mono text-[0.65rem] text-muted mt-1">
                <span>{years[0].year}</span>
                <span>{years[years.length - 1].year}</span>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  )
}
