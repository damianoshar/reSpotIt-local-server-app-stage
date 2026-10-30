let sdkPromise = null
let player = null
let deviceId = null
let readyPromise = null
let tokenGetter = null
const listeners = new Set()

let state = {
  ready: false,
  deviceId: '',
  playing: false,
  track: null,
  position: 0,
  duration: 0,
  volume: 0.5,
  error: '',
}

function loadSdk() {
  if (window.Spotify) return Promise.resolve()
  if (sdkPromise) return sdkPromise
  sdkPromise = new Promise((resolve) => {
    const script = document.createElement('script')
    script.src = 'https://sdk.scdn.co/spotify-player.js'
    script.async = true
    document.body.appendChild(script)
    window.onSpotifyWebPlaybackSDKReady = () => resolve()
  })
  return sdkPromise
}

function setState(patch) {
  state = { ...state, ...patch }
  listeners.forEach((listener) => listener(state))
}

export function getWebPlaybackState() {
  return state
}

export function subscribeWebPlayback(listener) {
  listeners.add(listener)
  listener(state)
  return () => listeners.delete(listener)
}

export function setWebPlaybackTokenGetter(getter) {
  tokenGetter = getter
}

async function getToken() {
  const getter = tokenGetter
  if (!getter) throw new Error('Spotify token is not available.')
  const token = await getter()
  if (!token) throw new Error('Spotify token is not available.')
  return token
}

export async function initWebPlayback(getter) {
  if (getter) tokenGetter = getter
  if (deviceId) return deviceId
  if (readyPromise) return readyPromise

  readyPromise = (async () => {
    await loadSdk()
    if (deviceId) return deviceId

    player = new window.Spotify.Player({
      name: 'reSpotIt Web Player',
      getOAuthToken: (cb) => {
        void getToken().then(cb).catch((e) => {
          setState({ error: e?.message || 'Spotify token failed' })
        })
      },
      volume: state.volume,
    })

    player.addListener('ready', ({ device_id }) => {
      deviceId = device_id
      setState({ ready: true, deviceId: device_id, error: '' })
    })
    player.addListener('not_ready', () => {
      setState({ ready: false })
    })
    player.addListener('player_state_changed', (sdkState) => {
      if (!sdkState) return
      const current = sdkState.track_window?.current_track
      setState({
        playing: !sdkState.paused,
        position: sdkState.position,
        duration: sdkState.duration,
        track: current
          ? {
              name: current.name,
              artist: (current.artists || []).map((a) => a.name).join(', '),
              album: current.album?.name || '',
              image: current.album?.images?.[0]?.url || '',
            }
          : state.track,
      })
    })
    player.addListener('initialization_error', ({ message }) => setState({ error: message }))
    player.addListener('authentication_error', ({ message }) => setState({ error: message }))
    player.addListener('account_error', () => setState({ error: 'Spotify Premium is required for the Web Playback SDK.' }))

    const connected = await player.connect()
    if (!connected) throw new Error('Could not connect the Web Playback SDK.')

    await new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => reject(new Error('Web Playback SDK did not become ready.')), 15000)
      const check = () => {
        if (deviceId) {
          window.clearTimeout(timer)
          resolve()
        }
      }
      const interval = window.setInterval(() => {
        if (deviceId) {
          window.clearInterval(interval)
          check()
        }
      }, 100)
    })

    return deviceId
  })()

  try {
    return await readyPromise
  } catch (error) {
    readyPromise = null
    player = null
    deviceId = null
    setState({ ready: false, error: error?.message || 'Player setup failed' })
    throw error
  }
}

export async function playContext(contextUri, getTokenOverride) {
  const token = getTokenOverride ? await getTokenOverride() : await getToken()
  let id = deviceId
  if (!id) {
    try {
      id = await initWebPlayback(getTokenOverride || tokenGetter)
    } catch {
      id = null
    }
  }
  const url = id
    ? `https://api.spotify.com/v1/me/player/play?device_id=${encodeURIComponent(id)}`
    : 'https://api.spotify.com/v1/me/player/play'
  const response = await fetch(url, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ context_uri: contextUri }),
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`Spotify play failed (${response.status}): ${text}`)
  }
  setState({ error: '' })
}

export async function playUris(uris, getTokenOverride) {
  const token = getTokenOverride ? await getTokenOverride() : await getToken()
  let id = deviceId
  if (!id) {
    try {
      id = await initWebPlayback(getTokenOverride || tokenGetter)
    } catch {
      id = null
    }
  }
  const url = id
    ? `https://api.spotify.com/v1/me/player/play?device_id=${encodeURIComponent(id)}`
    : 'https://api.spotify.com/v1/me/player/play'
  const response = await fetch(url, {
    method: 'PUT',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ uris }),
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`Spotify play failed (${response.status}): ${text}`)
  }
  setState({ error: '' })
}

export async function toggleWebPlayback() {
  const token = await getToken()
  const state = getWebPlaybackState()
  const id = deviceId
  const endpoint = state.playing ? 'pause' : 'play'
  const url = id
    ? `https://api.spotify.com/v1/me/player/${endpoint}?device_id=${encodeURIComponent(id)}`
    : `https://api.spotify.com/v1/me/player/${endpoint}`
  const response = await fetch(url, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok && response.status !== 204) {
    const text = await response.text()
    throw new Error(`Spotify ${endpoint} failed (${response.status}): ${text}`)
  }
  // Mirror on SDK instance.
  try { await player?.togglePlay?.() } catch { /* ignore */ }
}

export async function nextWebPlayback() {
  const token = await getToken()
  // Operate on the active device (don't force device_id, which can target a
  // non-playing SDK device and silently no-op).
  const response = await fetch('https://api.spotify.com/v1/me/player/next', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok && response.status !== 204) {
    const text = await response.text()
    throw new Error(`Spotify next failed (${response.status}): ${text}`)
  }
  // Mirror on the SDK instance when it is the active device.
  try { await player?.nextTrack?.() } catch { /* ignore */ }
}

export async function previousWebPlayback() {
  const token = await getToken()
  const response = await fetch('https://api.spotify.com/v1/me/player/previous', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok && response.status !== 204) {
    const text = await response.text()
    throw new Error(`Spotify previous failed (${response.status}): ${text}`)
  }
  try { await player?.previousTrack?.() } catch { /* ignore */ }
}

export async function seekWebPlayback(value) {
  const token = await getToken()
  const positionMs = Number(value)
  const id = deviceId
  const url = id
    ? `https://api.spotify.com/v1/me/player/seek?position_ms=${positionMs}&device_id=${encodeURIComponent(id)}`
    : `https://api.spotify.com/v1/me/player/seek?position_ms=${positionMs}`
  const response = await fetch(url, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok && response.status !== 204) {
    const text = await response.text()
    throw new Error(`Spotify seek failed (${response.status}): ${text}`)
  }
  try { await player?.seek?.(positionMs) } catch { /* ignore */ }
}

export async function setWebPlaybackVolume(value) {
  const volume = Number(value)
  setState({ volume })
  await player?.setVolume?.(volume)
}

export function getWebPlaybackDeviceId() {
  return deviceId
}