import { AlbumCard }  from './AlbumCard'
import { AlbumTable } from './AlbumListRow'

function SkeletonCard() {
  return (
    <div className="album-card">
      <div className="album-cover skeleton" style={{ aspectRatio: '1' }} />
      <div className="album-info space-y-2">
        <div className="skeleton h-3 rounded w-3/4" />
        <div className="skeleton h-2.5 rounded w-1/2" />
        <div className="skeleton h-2 rounded w-1/4 mt-2" />
      </div>
    </div>
  )
}

function EmptyState({ hasFilters }) {
  return (
    <div className="flex flex-col items-center justify-center py-28 text-center px-4">
      <div className="text-7xl mb-6 opacity-20">◉</div>
      <h2 className="font-display text-2xl font-semibold text-ink mb-2">
        {hasFilters ? 'No albums match' : 'Your crate is empty'}
      </h2>
      <p className="text-secondary text-sm max-w-xs">
        {hasFilters
          ? 'Try adjusting or clearing the filters to see more results.'
          : 'Sync your Spotify library using the button above to fill this grid.'}
      </p>
    </div>
  )
}

export function AlbumGrid({
  albums, loading, hasFilters,
  viewMode = 'grid', columns = 5,
  selectedIds, onToggleSelect, onShowTracks,
}) {
  const isGrid    = viewMode === 'grid'
  const isList    = viewMode === 'list'
  const isCompact = viewMode === 'compact'
  const selectionActive = selectedIds?.size > 0

  const gridStyle = {
    display: 'grid',
    gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
    gap: '0.75rem',
  }

  if (isList || isCompact) {
    return (!loading && !albums.length)
      ? <EmptyState hasFilters={hasFilters} />
      : <AlbumTable
          albums={albums} compact={isCompact} loading={loading}
          selectedIds={selectedIds} onToggleSelect={onToggleSelect}
          selectionActive={selectionActive}
        />
  }

  if (loading) {
    return (
      <div style={gridStyle}>
        {Array.from({ length: columns * 4 }).map((_, i) => <SkeletonCard key={i} />)}
      </div>
    )
  }

  if (!albums.length) return <EmptyState hasFilters={hasFilters} />

  return (
    <div style={gridStyle}>
      {albums.map(album => (
        <AlbumCard
          key={album.id}
          album={album}
          isSelected={selectedIds?.has(album.spotify_id)}
          onToggleSelect={onToggleSelect}
          selectionActive={selectionActive}
          onShowTracks={onShowTracks}
        />
      ))}
    </div>
  )
}
