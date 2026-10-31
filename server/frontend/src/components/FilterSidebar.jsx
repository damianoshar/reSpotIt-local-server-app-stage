import { useState } from 'react'

const ALBUM_TYPES = [
  { value: '',            label: 'All types'   },
  { value: 'album',       label: 'Album'       },
  { value: 'single',      label: 'Single'      },
  { value: 'compilation', label: 'Compilation' },
  { value: 'ep',          label: 'EP'          },
]

const DECADES = [
  { label: '60s', from: 1960, to: 1969 },
  { label: '70s', from: 1970, to: 1979 },
  { label: '80s', from: 1980, to: 1989 },
  { label: '90s', from: 1990, to: 1999 },
  { label: '00s', from: 2000, to: 2009 },
  { label: '10s', from: 2010, to: 2019 },
  { label: '20s', from: 2020, to: 2029 },
]

function Section({ title, children }) {
  return (
    <div>
      <p className="filter-label">{title}</p>
      {children}
    </div>
  )
}

function ToggleTab({ open, activeCount, onToggle }) {
  return (
    <button
      onClick={onToggle}
      title={open ? 'Hide filters' : 'Show filters'}
      style={{
        display:        'flex',
        flexDirection:  'column',
        alignItems:     'center',
        justifyContent: 'center',
        gap:            3,
        width:          20,
        padding:        '10px 4px',
        flexShrink:     0,
        alignSelf:      'flex-start',
        background:     '#232019',
        border:         '1px solid #333333',
        borderRadius:   4,
        cursor:         'pointer',
        transition:     'background 0.15s, border-color 0.15s',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.background    = '#2e2a1a'
        e.currentTarget.style.borderColor   = '#1DB95455'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.background    = '#232019'
        e.currentTarget.style.borderColor   = '#333333'
      }}
    >
      {/* Active dot */}
      {activeCount > 0 && (
        <div style={{
          width: 5, height: 5, borderRadius: '50%',
          background: '#1DB954', boxShadow: '0 0 4px #1DB954',
          marginBottom: 2,
        }} />
      )}
      {/* Chevron — points left when open, right when closed */}
      <svg
        width="8" height="12" viewBox="0 0 8 12" fill="none"
        style={{
          transition: 'transform 0.28s ease',
          transform:  open ? 'none' : 'rotate(180deg)',
        }}
      >
        <path d="M6 1L1 6l5 5" stroke="#B3B3B3" strokeWidth="1.5"
              strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
      {/* Rotated label */}
      <span style={{
        fontFamily:   'Space Mono, monospace',
        fontSize:     '0.5rem',
        textTransform:'uppercase',
        letterSpacing:'0.1em',
        color:        '#555555',
        writingMode:  'vertical-rl',
        marginTop:    4,
        userSelect:   'none',
      }}>
        {open ? 'hide' : activeCount > 0 ? `filter ${activeCount}` : 'filter'}
      </span>
    </button>
  )
}

export function FilterSidebar({ filters, onChange, artists, open, onToggle }) {
  const set = (key, val) => onChange(prev => ({ ...prev, [key]: val }))

  const activeCount = [
    filters.search, filters.artist, filters.genre, filters.album_type,
    filters.year_from, filters.year_to,
    filters.min_pop > 0   ? '1' : '',
    filters.max_pop < 100 ? '1' : '',
  ].filter(Boolean).length

  const clearAll = () => onChange({
    search: '', artist: '', genre: '', album_type: '',
    year_from: '', year_to: '', min_pop: 0, max_pop: 100,
  })

  return (
    // Outer row: [sliding panel] [toggle tab]
    // Both are normal flex children — no absolute positioning, no ghost space.
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0, flexShrink: 0 }}>

      {/* Sliding panel — width animates 0 ↔ 208, content clipped */}
      <div style={{
        width:      open ? 208 : 0,
        overflow:   'hidden',
        transition: 'width 0.28s cubic-bezier(0.4, 0, 0.2, 1)',
        flexShrink: 0,
      }}>
        <aside style={{
          width:         208,
          paddingRight:  '1.25rem',
          paddingTop:    '0.25rem',
          opacity:       open ? 1 : 0,
          transition:    'opacity 0.18s ease',
          pointerEvents: open ? 'auto' : 'none',
        }}>
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <span className="font-display text-lg font-semibold text-ink">Filters</span>
            {activeCount > 0 && (
              <button onClick={clearAll}
                className="font-mono text-[0.6rem] text-accent uppercase tracking-wider hover:text-accent-2 transition-colors">
                Clear {activeCount}
              </button>
            )}
          </div>

          <div className="space-y-4">
            <Section title="Album">
              <input className="filter-input" placeholder="Search album…"
                value={filters.search}
                onChange={e => set('search', e.target.value)} />
            </Section>

            <Section title="Artist">
              <input className="filter-input" placeholder="Search artist…"
                value={filters.artist}
                onChange={e => set('artist', e.target.value)}
                list="artist-datalist" />
              <datalist id="artist-datalist">
                {artists.map(a => <option key={a.id} value={a.name} />)}
              </datalist>
            </Section>

            <Section title="Genre">
              <input className="filter-input" placeholder="e.g. jazz, indie…"
                value={filters.genre}
                onChange={e => set('genre', e.target.value)} />
            </Section>

            <Section title="Type">
              <select className="filter-input filter-select"
                value={filters.album_type}
                onChange={e => set('album_type', e.target.value)}>
                {ALBUM_TYPES.map(t => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </Section>

            <div className="divider" />

            <Section title="Release Year">
              <div className="flex gap-2">
                <input className="filter-input text-center" type="number"
                  placeholder="From" min="1900" max="2100"
                  value={filters.year_from}
                  onChange={e => set('year_from', e.target.value ? parseInt(e.target.value) : '')} />
                <input className="filter-input text-center" type="number"
                  placeholder="To" min="1900" max="2100"
                  value={filters.year_to}
                  onChange={e => set('year_to', e.target.value ? parseInt(e.target.value) : '')} />
              </div>
              <div className="flex flex-wrap gap-1 mt-2">
                {DECADES.map(d => (
                  <button key={d.label}
                    onClick={() => onChange(prev => ({ ...prev, year_from: d.from, year_to: d.to }))}
                    className={`font-mono text-[0.6rem] px-2 py-1 rounded border transition-colors
                      ${filters.year_from === d.from && filters.year_to === d.to
                        ? 'bg-accent text-base border-accent'
                        : 'border-border text-muted hover:border-accent-dim hover:text-accent'}`}>
                    {d.label}
                  </button>
                ))}
              </div>
            </Section>

            <Section title="Popularity">
              <div className="space-y-3">
                <div>
                  <div className="flex justify-between font-mono text-[0.6rem] text-muted mb-1">
                    <span>Min</span>
                    <span className="text-secondary">{filters.min_pop}</span>
                  </div>
                  <input type="range" min="0" max="100" step="5"
                    value={filters.min_pop}
                    onChange={e => {
                      const val = Number(e.target.value)
                      set('min_pop', val)
                      if (val > filters.max_pop) set('max_pop', val)
                    }} />
                </div>
                <div>
                  <div className="flex justify-between font-mono text-[0.6rem] text-muted mb-1">
                    <span>Max</span>
                    <span className="text-secondary">{filters.max_pop}</span>
                  </div>
                  <input type="range" min="0" max="100" step="5"
                    value={filters.max_pop}
                    onChange={e => {
                      const val = Number(e.target.value)
                      set('max_pop', val)
                      if (val < filters.min_pop) set('min_pop', val)
                    }} />
                </div>
                <div className="flex justify-between font-mono text-[0.6rem] text-muted">
                  <span>0</span>
                  <span className={filters.min_pop > 0 || filters.max_pop < 100 ? 'text-accent' : ''}>
                    {filters.min_pop}–{filters.max_pop}
                  </span>
                  <span>100</span>
                </div>
              </div>
            </Section>
          </div>
        </aside>
      </div>

      {/* Toggle tab — always visible, sits flush against the panel */}
      <ToggleTab open={open} activeCount={activeCount} onToggle={onToggle} />
    </div>
  )
}