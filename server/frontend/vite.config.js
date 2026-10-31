import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, proxy all backend routes to FastAPI on port 8000.
// Supports both HTTP and HTTPS backends: set BACKEND_URL env var
// (e.g. http://127.0.0.1:8000 or https://127.0.0.1:8000).
const BACKEND = process.env.BACKEND_URL || 'https://127.0.0.1:8000'
// Keycloak is only published on 127.0.0.1 by Docker Desktop on Windows.
// Proxying it here gives the phone a LAN-reachable login endpoint.
const KEYCLOAK = process.env.KEYCLOAK_URL || 'http://127.0.0.1:8083'

// Keycloak 26 marks its login cookies `Secure; SameSite=None` unconditionally.
// Browsers reject those on a plain-http LAN origin, which breaks the login
// form with "Restart login cookie not found". This dev proxy is the TLS
// boundary stand-in, so downgrade the cookies the same way Keycloak does for
// an insecure context: no Secure flag, SameSite=Lax. Local dev only; never
// run this in front of a public deployment.
function relaxKeycloakCookies(proxy) {
  proxy.on('proxyRes', (proxyRes) => {
    const cookies = proxyRes.headers['set-cookie']
    if (!cookies) return
    proxyRes.headers['set-cookie'] = cookies.map((cookie) =>
      cookie
        .replace(/;\s*Secure/gi, '')
        .replace(/SameSite=None/gi, 'SameSite=Lax'),
    )
  })
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Docker containers call the API through the host's LAN address.
    allowedHosts: ['localhost', '127.0.0.1', '192.168.1.11', 'host.docker.internal'],
    proxy: {
      // Single rule — every backend route lives under /api/v1/*.
      '/api': { target: BACKEND, changeOrigin: true, secure: false },
      // Keycloak keeps its own /authKeycloak prefix; no rewrite needed.
      '/authKeycloak': {
        target: KEYCLOAK,
        changeOrigin: true,
        secure: false,
        configure: relaxKeycloakCookies,
      },
    },
  },
})
