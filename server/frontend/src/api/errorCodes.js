/**
 * Contract error codes -> user-facing wording.
 *
 * Mirror of the TS helper in the other frontends (errorCodes.ts), with two
 * additions this app needs:
 *
 *  - the job envelope has no `code` (only a message), so a couple of
 *    well-known Spotify failures are still recognised by status/message; and
 *  - before this existed the queue toolbar string-matched on the message text
 *    ('No active', '403'), which broke the moment a backend reworded itself.
 *    Those two cases are preserved here, keyed on status instead of wording.
 */

export const REMOTE_ERROR_HINTS = {
  not_connected:    'Connect your Spotify account first.',
  no_albums:        'Select at least one album.',
  unauthorized:     'Your session expired — sign in again.',
  already_running:  'A job is already running. Wait for it to finish.',
  token_error:      'Your Spotify session expired — reconnect the account.',
  bad_gateway:      'Spotify could not be reached. Try again in a moment.',
  validation_error: 'The server rejected that request.',
  not_found:        'Not found on the server.',
  internal_error:   'The server hit an unexpected error.',
}

/** Status-based rules for failures that carry no usable code. */
const STATUS_HINTS = {
  403: 'Re-authorise Spotify (sign out and back in).',
}

function asErrorLike(err) {
  return typeof err === 'object' && err !== null ? err : null
}

/** The contract error code carried by a rejected call, if any. */
export function remoteErrorCode(err) {
  const code = asErrorLike(err)?.code
  return typeof code === 'string' && code.length > 0 ? code : undefined
}

/** True when the failure means "no Spotify account is linked". */
export function isSpotifyNotConnected(err) {
  return remoteErrorCode(err) === 'not_connected'
}

/**
 * Message to show for a failed call: canonical wording for the code when we
 * know it, otherwise the status rule, otherwise the server's own message,
 * otherwise `fallback`.
 */
export function describeRemoteError(err, fallback) {
  const e = asErrorLike(err)
  const code = remoteErrorCode(err)
  if (code && REMOTE_ERROR_HINTS[code]) return REMOTE_ERROR_HINTS[code]

  const status = e?.status
  if (typeof status === 'number' && STATUS_HINTS[status]) return STATUS_HINTS[status]

  const message = e?.message
  if (typeof message === 'string' && message.trim().length > 0) {
    // The generic job envelope reports failures as a message, not a code.
    if (/no active/i.test(message)) return 'Open Spotify on a device first.'
    return message
  }

  return fallback
}
