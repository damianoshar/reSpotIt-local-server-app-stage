/**
 * StatsBar — library-wide counts (global, not filter-scoped).
 */
export function StatsBar({ stats }) {
  if (!stats) return null

  const span = stats.oldestYear && stats.newestYear
    ? `${stats.oldestYear}–${stats.newestYear}`
    : '—'

  const items = [
    { value: (stats.totalAlbums  ?? 0).toLocaleString(), label: 'Albums'  },
    { value: (stats.totalArtists ?? 0).toLocaleString(), label: 'Artists' },
    { value: (stats.totalGenres  ?? 0).toLocaleString(), label: 'Genres'  },
    { value: span,                                        label: 'Span'    },
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-5" role="status" aria-label="Library stats">
      {items.map(it => (
        <div
          key={it.label}
          className="rounded-lg border border-border bg-panel px-4 py-3 text-center"
        >
          <div className="font-mono text-xl font-bold text-accent">{it.value}</div>
          <div className="font-mono text-[0.6rem] uppercase tracking-widest text-muted mt-1">
            {it.label}
          </div>
        </div>
      ))}
    </div>
  )
}
