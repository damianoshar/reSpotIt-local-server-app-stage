import React, { useEffect, useMemo, useState } from 'react'

export function DuplicatesDialog({
  open, groups, hiddenCount = 0, loading = false, isRemote = false,
  onDismiss, onHide, onRestore, onRemovePermanent,
}) {
  const [selected, setSelected] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    const next = {}
    groups.forEach((group) => {
      group.albums.forEach((album, index) => {
        next[album.id] = index !== 0
      })
    })
    setSelected(next)
  }, [open, groups])

  const removeIds = useMemo(
    () => Object.keys(selected).filter((id) => selected[id]),
    [selected],
  )

  const canHide = !loading && !saving &&
    groups.every((group) => group.albums.some((album) => !selected[album.id])) &&
    removeIds.length > 0

  const handleHide = async () => {
    if (!canHide) return
    setSaving(true)
    try { onHide(removeIds) } finally { setSaving(false) }
  }

  const handlePermanent = async () => {
    if (!canHide || !onRemovePermanent) return
    if (!window.confirm('Permanently remove the selected duplicates from your Spotify library?')) return
    setSaving(true)
    try { await onRemovePermanent(removeIds) } finally { setSaving(false) }
  }

  if (!open) return null

  return (
    <div className="modal-overlay" role="presentation"
         style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
         onClick={onDismiss}>
      <div role="dialog" aria-modal="true"
           style={{ background: '#181818', border: '1px solid #333333', borderRadius: 8, maxWidth: 560, width: '90%', maxHeight: '80vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
           onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid #333333', display: 'flex', justifyContent: 'space-between' }}>
          <div>
            <h2 style={{ margin: 0, color: '#FFFFFF' }}>Duplicate albums</h2>
            <p style={{ margin: '6px 0 0', color: '#B3B3B3', fontSize: '0.85rem' }}>
              Review locally. Hidden duplicates are removed from the visible library only.
            </p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onDismiss}>Close</button>
        </div>

        <div style={{ padding: 20, overflowY: 'auto', flex: 1 }}>
          {hiddenCount > 0 && isRemote && (
            <p style={{ color: '#B3B3B3', fontSize: '0.85rem' }}>
              Hidden duplicates are only stored in this browser; the Python server still has all rows.
            </p>
          )}
          {loading && <p style={{ color: '#B3B3B3' }}>Scanning for duplicates...</p>}
          {!loading && groups.length === 0 && (
            <p style={{ color: '#B3B3B3' }}>No duplicate groups found ({hiddenCount} hidden).</p>
          )}
          {groups.map((group) => (
            <div key={group.key} style={{ marginBottom: 16, borderBottom: '1px solid #282828', paddingBottom: 16 }}>
              <div style={{ color: '#FFFFFF', fontWeight: 600, marginBottom: 8 }}>
                {group.title} · {group.artist}
              </div>
              {group.albums.map((album) => (
                <label key={album.id} style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 8, cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={!!selected[album.id]}
                    onChange={() => setSelected((prev) => ({ ...prev, [album.id]: !prev[album.id] }))}
                  />
                  <span style={{ minWidth: 0 }}>
                    <span style={{ color: '#FFFFFF' }}>{album.title}</span>
                    <span style={{ color: '#B3B3B3', marginLeft: 8, fontSize: '0.85rem' }}>
                      {album.year || '?'} tracks
                    </span>
                  </span>
                </label>
              ))}
            </div>
          ))}
        </div>

        <div style={{ padding: '14px 20px', borderTop: '1px solid #333333', display: 'flex', gap: 8, justifyContent: 'space-between' }}>
          <button className="btn btn-ghost btn-sm" onClick={onRestore} disabled={hiddenCount === 0}>
            Restore hidden ({hiddenCount})
          </button>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-ghost btn-sm" onClick={onDismiss}>Cancel</button>
            <button className="btn btn-primary btn-sm" onClick={handleHide} disabled={!selected || !Object.keys(selected).some((id) => selected[id])}>
              {saving ? 'Working?' : 'Hide selected'}
            </button>
            {onRemovePermanent && (
              <button className="btn btn-ghost btn-sm" style={{ color: '#E22134' }}
                      onClick={handlePermanent} disabled={!selected || !Object.keys(selected).some((id) => selected[id])}>
                {saving ? 'Working?' : 'Remove from Spotify'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
