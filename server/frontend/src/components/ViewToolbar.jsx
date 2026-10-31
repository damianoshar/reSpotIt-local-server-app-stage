/**
 * ViewToolbar.jsx
 * ---------------
 * View mode toggle (grid / list / compact), column slider, and sort control.
 * This replaces the old ViewControls.jsx — same props interface, new name.
 */

const ICONS = {
  grid: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
      <rect x="1" y="1" width="5" height="5" rx="1"/><rect x="9" y="1" width="5" height="5" rx="1"/>
      <rect x="1" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/>
    </svg>
  ),
  list: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
      <rect x="1" y="2" width="13" height="2" rx="1"/><rect x="1" y="6.5" width="13" height="2" rx="1"/>
      <rect x="1" y="11" width="13" height="2" rx="1"/>
    </svg>
  ),
  compact: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
      <rect x="1" y="1.5" width="13" height="1.5" rx="0.75"/><rect x="1" y="5" width="13" height="1.5" rx="0.75"/>
      <rect x="1" y="8.5" width="13" height="1.5" rx="0.75"/><rect x="1" y="12" width="13" height="1.5" rx="0.75"/>
    </svg>
  ),
}

const SORT_OPTIONS = [
  { value: 'added_at_desc',   label: 'Date added ↓'  },
  { value: 'added_at_asc',    label: 'Date added ↑'  },
  { value: 'name_asc',        label: 'Title A–Z'      },
  { value: 'name_desc',       label: 'Title Z–A'      },
  { value: 'artist_asc',      label: 'Artist A–Z'     },
  { value: 'artist_desc',     label: 'Artist Z–A'     },
  { value: 'year_desc',       label: 'Year ↓'         },
  { value: 'year_asc',        label: 'Year ↑'         },
  { value: 'popularity_desc', label: 'Popularity ↓'   },
  { value: 'popularity_asc',  label: 'Popularity ↑'   },
]

export const VIEW_MODES = ['grid', 'list', 'compact']

/**
 * Props:
 *   viewMode     'grid' | 'list' | 'compact'
 *   setViewMode  fn(mode)
 *   columns      number (2–8)
 *   setColumns   fn(number)
 *   sort         string — one of the SORT_OPTIONS values
 *   setSort      fn(value)
 */
export function ViewToolbar({ viewMode, setViewMode, columns, setColumns, sort, setSort }) {
  return (
    <div className="flex items-center gap-3 flex-wrap">

      {/* Sort */}
      <select
        value={sort}
        onChange={e => setSort(e.target.value)}
        className="filter-input filter-select !w-auto text-xs py-1.5 px-3 pr-8"
      >
        {SORT_OPTIONS.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>

      {/* Divider */}
      <div className="h-5 w-px bg-border" />

      {/* View mode toggles */}
      <div className="flex items-center border border-border rounded overflow-hidden">
        {VIEW_MODES.map(mode => (
          <button
            key={mode}
            title={mode.charAt(0).toUpperCase() + mode.slice(1) + ' view'}
            onClick={() => setViewMode(mode)}
            className={`px-2.5 py-1.5 transition-colors flex items-center gap-1.5
              ${viewMode === mode
                ? 'bg-accent text-base'
                : 'text-secondary hover:text-ink hover:bg-elevated'
              }`}
          >
            {ICONS[mode]}
            <span className="font-mono text-[0.6rem] uppercase tracking-wider hidden sm:inline">
              {mode}
            </span>
          </button>
        ))}
      </div>

      {/* Column slider — only in grid mode */}
      {viewMode === 'grid' && (
        <div className="flex items-center gap-2 ml-1">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor" className="text-muted flex-shrink-0">
            <rect x="0" y="0" width="3" height="12" rx="0.75"/>
            <rect x="4.5" y="0" width="3" height="12" rx="0.75"/>
            <rect x="9" y="0" width="3" height="12" rx="0.75"/>
          </svg>
          <input
            type="range" min="2" max="8" step="1" value={columns}
            onChange={e => setColumns(Number(e.target.value))}
            className="w-20"
            title={`${columns} columns`}
          />
          <span className="font-mono text-[0.6rem] text-muted w-4 text-center">{columns}</span>
        </div>
      )}
    </div>
  )
}
