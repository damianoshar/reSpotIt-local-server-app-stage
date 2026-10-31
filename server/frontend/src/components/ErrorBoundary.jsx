/**
 * ErrorBoundary — root crash boundary.
 *
 * A render crash anywhere below shows a recovery screen instead of a blank or
 * dead app. This is the JSX twin of the identical ErrorBoundary.tsx in the
 * android-ts / windows / csharp / elixir frontends.
 *
 * No reporting backend exists anywhere in the project, so the error goes to the
 * console for diagnostics only.
 */
import React from 'react'

const styles = {
  page: {
    minHeight: '100dvh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#121212',
    color: '#fff',
    padding: 24,
  },
  inner: { maxWidth: 480, textAlign: 'center' },
  icon: { fontSize: 40, marginBottom: 16 },
  title: { fontSize: 20, margin: '0 0 8px' },
  body: { color: '#b3b3b3', fontSize: 14, margin: '0 0 8px' },
  detail: {
    color: '#b3b3b3',
    fontSize: 12,
    fontFamily: 'monospace',
    overflowWrap: 'anywhere',
    margin: '0 0 24px',
  },
  buttons: { display: 'flex', gap: 12, justifyContent: 'center' },
  primary: {
    padding: '10px 24px',
    borderRadius: 999,
    border: 'none',
    background: '#1DB954',
    color: '#000',
    fontWeight: 700,
    cursor: 'pointer',
  },
  ghost: {
    padding: '10px 24px',
    borderRadius: 999,
    border: '1px solid #535353',
    background: 'transparent',
    color: '#fff',
    cursor: 'pointer',
  },
}

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
    this.retry = () => this.setState({ error: null })
    this.reload = () => window.location.reload()
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Uncaught UI error:', error, info?.componentStack)
  }

  render() {
    const { error } = this.state
    if (error) {
      return (
        <div role="alert" style={styles.page}>
          <div style={styles.inner}>
            <div style={styles.icon}>⚠️</div>
            <h1 style={styles.title}>Something went wrong</h1>
            <p style={styles.body}>
              The app hit an unexpected error. Your library data is safe — try
              again or reload.
            </p>
            <p style={styles.detail}>{error.message}</p>
            <div style={styles.buttons}>
              <button onClick={this.retry} style={styles.primary}>Try again</button>
              <button onClick={this.reload} style={styles.ghost}>Reload</button>
            </div>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
