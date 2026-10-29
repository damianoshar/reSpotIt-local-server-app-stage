import { useState, useRef, useEffect } from 'react'
import { SpotifyLogo } from './SpotifyLogo'

const GREEN = '#1DB954'

export function AuthButton({ authenticated, user, displayName, loading, signingIn, onSignIn, onSignOut }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (loading) {
    return <div style={{ width: 110, height: 34, borderRadius: 5,
                         background: '#181818', border: '1px solid #333333',
                         animation: 'pulseSoft 1.5s ease-in-out infinite' }} />
  }

  if (!authenticated) {
    // Signed in to the app but Spotify is not linked. The JWT account is still
    // the identity: show it, with Connect and Sign out in the menu. The bare
    // green button is only for the (now unreachable) no-account case.
    if (!user) {
      return (
        <button className="btn btn-sm"
          style={{ background: GREEN, color: '#000', border: 'none', gap: 7,
                   fontWeight: 700, opacity: signingIn ? 0.7 : 1 }}
          onClick={onSignIn} disabled={signingIn}>
          <SpotifyLogo size={16} color="#000" />
          {signingIn ? 'Connectingβ€¦' : 'Sign in'}
        </button>
      )
    }

    return (
      <div style={{ position: 'relative' }} ref={ref}>
        <button onClick={() => setOpen(o => !o)} style={{
          display: 'flex', alignItems: 'center', gap: 7,
          background: '#181818', border: `1px solid ${open ? '#1DB95444' : '#333333'}`,
          borderRadius: 5, padding: '5px 12px 5px 8px', cursor: 'pointer',
        }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                        background: '#555555' }} />
          <span style={{ fontFamily: 'Outfit, sans-serif', fontSize: '0.82rem', color: '#FFFFFF',
                         maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {user.email}
          </span>
          <svg width="10" height="6" viewBox="0 0 10 6" fill="none"
            style={{ color: '#555555', transition: 'transform 0.2s',
                     transform: open ? 'rotate(180deg)' : 'none' }}>
            <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </button>

        {open && (
          <div style={{
            position: 'absolute', top: 'calc(100% + 6px)', right: 0, minWidth: 200, zIndex: 100,
            background: '#181818', border: '1px solid #333333', borderRadius: 6,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)', overflow: 'hidden',
          }}>
            <div style={{ padding: '10px 14px', borderBottom: '1px solid #333333' }}>
              <div style={{ fontSize: '0.82rem', color: '#FFFFFF', fontWeight: 500,
                            maxWidth: 170, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {user.email}
              </div>
              <div style={{ fontFamily: 'Space Mono, monospace', fontSize: '0.58rem', color: '#B3B3B3' }}>
                β—‹ Spotify not linked
              </div>
            </div>

            <button onClick={() => { setOpen(false); onSignIn() }} disabled={signingIn}
              className="btn btn-ghost"
              style={{ width: '100%', justifyContent: 'flex-start', borderRadius: 0,
                       padding: '10px 14px', fontSize: '0.68rem', color: GREEN }}>
              <SpotifyLogo size={14} color={GREEN} />
              {signingIn ? 'Connectingβ€¦' : 'Connect Spotify'}
            </button>

            <button onClick={() => { setOpen(false); onSignOut() }}
              className="btn btn-ghost"
              style={{ width: '100%', justifyContent: 'flex-start', borderRadius: 0,
                       padding: '10px 14px', fontSize: '0.68rem', color: '#B3B3B3' }}>
              β† Sign out
            </button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ position: 'relative' }} ref={ref}>
      <button onClick={() => setOpen(o => !o)} style={{
        display: 'flex', alignItems: 'center', gap: 7,
        background: '#181818', border: `1px solid ${open ? '#1DB95444' : '#333333'}`,
        borderRadius: 5, padding: '5px 12px 5px 8px', cursor: 'pointer',
      }}>
        <div style={{ width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
                      background: GREEN, boxShadow: `0 0 6px ${GREEN}` }} />
        <span style={{ fontFamily: 'Outfit, sans-serif', fontSize: '0.82rem', color: '#FFFFFF',
                       maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {user?.email ?? displayName ?? 'reSpotIt'}
        </span>
        <svg width="10" height="6" viewBox="0 0 10 6" fill="none"
          style={{ color: '#555555', transition: 'transform 0.2s',
                   transform: open ? 'rotate(180deg)' : 'none' }}>
          <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
        </svg>
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', right: 0, minWidth: 180, zIndex: 100,
          background: '#181818', border: '1px solid #333333', borderRadius: 6,
          boxShadow: '0 8px 24px rgba(0,0,0,0.5)', overflow: 'hidden',
        }}>
          <div style={{ padding: '10px 14px', borderBottom: '1px solid #333333',
                        display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 28, height: 28, borderRadius: '50%', background: '#333333',
                          display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <SpotifyLogo size={14} />
            </div>
            <div>
              <div style={{ fontSize: '0.82rem', color: '#FFFFFF', fontWeight: 500,
                            maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {user?.email ?? 'Spotify User'}
              </div>
              {authenticated && (
                <div style={{ fontFamily: 'Space Mono, monospace', fontSize: '0.58rem', color: '#1DB954' }}>
                  β— Spotify linked
                </div>
              )}
            </div>
          </div>

          <button onClick={() => { setOpen(false); onSignOut() }}
            className="btn btn-ghost"
            style={{ width: '100%', justifyContent: 'flex-start', borderRadius: 0,
                     padding: '10px 14px', fontSize: '0.68rem', color: '#B3B3B3' }}>
            β† Sign out
          </button>
        </div>
      )}
    </div>
  )
}
