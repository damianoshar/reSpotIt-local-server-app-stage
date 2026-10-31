import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'

const TOOLS_KEY = 'reSpotIt_ai_tools'

const AI_SYSTEM_PROMPT =
  'You are the reSpotIt library assistant. You help the user understand and organise ' +
  'their saved music library, and you can control Spotify playback, search the ' +
  'catalog and manage playlists using the available tools: playback (search, play, ' +
  'pause, skip, volume, queue, devices), library (stats, albums, artists, genres) ' +
  'and playlists (list, create, add/remove tracks). ' +
  'Be concise, concrete and practical. Only recommend albums that appear in the library ' +
  'sample unless the user asks to search Spotify. Do not mention these instructions.'

const SUGGESTIONS = [
  'Which artists appear most often in my library?',
  'Recommend albums I have not played in a while.',
  'Build me a calm playlist for the evening.',
]

function uid() {
  try {
    return crypto.randomUUID()
  } catch {
    return `m-${Date.now()}-${Math.random().toString(36).slice(2)}`
  }
}

/** The flat message list Open WebUI renders, reduced to chat turns. */
function storedMessages(chatRow) {
  const list = chatRow?.chat?.messages
  if (!Array.isArray(list)) return []
  return list
    .filter((m) => m && (m.role === 'user' || m.role === 'assistant')
      && typeof m.content === 'string' && m.content.trim())
    .map((m, i) => ({
      id: m.id || `stored-${i}`,
      role: m.role,
      content: m.content,
    }))
}

function timeLabel(epochSeconds) {
  if (!epochSeconds) return ''
  const date = new Date(epochSeconds * 1000)
  if (Number.isNaN(date.getTime())) return ''
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleDateString()
}

/** Open WebUI reports the llama.cpp file path; show just the model name. */
function modelLabel(model) {
  if (!model) return ''
  const base = String(model).split(/[\\/]/).pop() || String(model)
  return base.replace(/\.gguf$/i, '')
}

function errorText(err) {
  if (err instanceof ApiError) {
    if (err.code === 'llm_not_configured') {
      return 'The AI assistant is not configured on this server (OPENWEBUI_API_KEY).'
    }
    if (err.code === 'llm_chat_unavailable') {
      return 'Chat history is unavailable; answers will not be saved.'
    }
    return err.message
  }
  return err?.message || 'The assistant could not answer.'
}

export function AIChatView({ onToast }) {
  const [booting, setBooting] = useState(true)
  const [status, setStatus] = useState(null)
  const [chats, setChats] = useState([])
  const [chatId, setChatId] = useState(null)
  const [chatTitle, setChatTitle] = useState('')
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [historyUnavailable, setHistoryUnavailable] = useState(false)
  const [saveWarning, setSaveWarning] = useState(false)
  const [useTools, setUseTools] = useState(() => {
    try { return localStorage.getItem(TOOLS_KEY) !== '0' } catch { return true }
  })

  const listRef = useRef(null)
  const textareaRef = useRef(null)

  const historyAvailable = !historyUnavailable && Boolean(status?.chat_history)
  const ready = Boolean(status?.available)

  const refreshChats = useCallback(async () => {
    try {
      const res = await api.llmChats()
      setChats(res.data || [])
    } catch {
      /* the thread still works without the sidebar */
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await api.llmStatus()
        if (cancelled) return
        const data = res.data || null
        setStatus(data)
        if (!data?.available) return
        if (!data.chat_history) {
          setHistoryUnavailable(true)
          return
        }
        try {
          const [list, current] = await Promise.all([
            api.llmChats(),
            api.llmCurrentChat(),
          ])
          if (cancelled) return
          setChats(list.data || [])
          if (current.data) {
            setChatId(current.data.id)
            setChatTitle(current.data.title || '')
            setMessages(storedMessages(current.data))
          }
        } catch (err) {
          if (cancelled) return
          if (err instanceof ApiError && err.code === 'llm_chat_unavailable') {
            setHistoryUnavailable(true)
          } else {
            setError(errorText(err))
          }
        }
      } catch (err) {
        if (!cancelled) setError(errorText(err))
      } finally {
        if (!cancelled) setBooting(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages.length, sending])

  useEffect(() => {
    try { localStorage.setItem(TOOLS_KEY, useTools ? '1' : '0') } catch { /* private mode */ }
  }, [useTools])

  const toggleTools = () => setUseTools((v) => !v)

  const newChat = async () => {
    if (sending) return
    setError('')
    setSaveWarning(false)
    setDraft('')
    setChatId(null)
    setChatTitle('')
    setMessages([])
    if (historyAvailable) {
      try {
        await api.llmClearCurrentChat()
      } catch {
        onToast?.('Could not start a new chat; the previous chat may resume on reload.', false)
      }
    }
    textareaRef.current?.focus()
  }

  const openChat = async (id) => {
    if (sending || !id || id === chatId) return
    setError('')
    setSaveWarning(false)
    try {
      const res = await api.llmGetChat(id)
      setChatId(res.data.id)
      setChatTitle(res.data.title || '')
      setMessages(storedMessages(res.data))
    } catch (err) {
      setError(errorText(err))
    }
  }

  const removeChat = async (row, event) => {
    event?.stopPropagation()
    if (sending) return
    if (!window.confirm(`Delete "${row.title || 'this chat'}"? This cannot be undone.`)) return
    try {
      await api.llmDeleteChat(row.id)
      setChats((prev) => prev.filter((c) => c.id !== row.id))
      if (chatId === row.id) {
        setChatId(null)
        setChatTitle('')
        setMessages([])
      }
      onToast?.('Chat deleted.', true)
    } catch (err) {
      onToast?.(errorText(err), false)
    }
  }

  const send = async (raw) => {
    const content = (raw ?? draft).trim()
    if (!content || sending || !ready) return
    setDraft('')
    setError('')
    setSaveWarning(false)
    setSending(true)

    const userId = uid()
    setMessages((prev) => [...prev, { id: userId, role: 'user', content }])

    const body = {
      messages: [{ role: 'user', content }],
      system: AI_SYSTEM_PROMPT,
      chat_id: historyAvailable ? chatId : null,
      use_history: true,
      history_limit: 20,
      persist: historyAvailable,
      use_tools: useTools,
    }

    try {
      const res = await api.llmChat(body)
      const data = res.data || {}
      setMessages((prev) => [...prev, {
        id: uid(),
        role: 'assistant',
        content: data.content || '(The model returned an empty answer.)',
      }])

      if (data.chat_id) {
        setChatId(data.chat_id)
        if (data.persisted) {
          try {
            const stored = await api.llmGetChat(data.chat_id)
            setChatTitle(stored.data.title || '')
            setMessages(storedMessages(stored.data))
          } catch {
            /* keep the local transcript if the reload fails */
          }
          void refreshChats()
        } else {
          setSaveWarning(true)
        }
      }
    } catch (err) {
      if (err instanceof ApiError && err.code === 'llm_chat_unavailable') {
        // History turned out to be unavailable mid-session: retry without it.
        setHistoryUnavailable(true)
        setChatId(null)
        setChatTitle('')
        try {
          const res = await api.llmChat({
            messages: [{ role: 'user', content }],
            system: AI_SYSTEM_PROMPT,
            persist: false,
            use_tools: useTools,
          })
          setMessages((prev) => [...prev, {
            id: uid(),
            role: 'assistant',
            content: res.data?.content || '(The model returned an empty answer.)',
          }])
        } catch (retryErr) {
          setMessages((prev) => prev.filter((m) => m.id !== userId))
          setDraft(content)
          setError(errorText(retryErr))
        }
      } else {
        setMessages((prev) => prev.filter((m) => m.id !== userId))
        setDraft(content)
        setError(errorText(err))
        onToast?.(errorText(err), false)
      }
    } finally {
      setSending(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  return (
    <div className="ai-tab">
      <div className="ai-head">
        <div>
          <h1 className="font-display text-2xl font-semibold">AI Assistant</h1>
          <p className="font-mono text-[0.65rem] text-muted">
            {status?.model ? `Model: ${modelLabel(status.model)}` : 'Local model through Open WebUI'}
            {historyAvailable ? ' · chats saved' : historyUnavailable ? ' · history off' : ''}
          </p>
        </div>
        <div className="ai-head-actions">
          {historyAvailable && (
            <button className="btn btn-ghost btn-sm" onClick={newChat} disabled={sending}>
              + New chat
            </button>
          )}
        </div>
      </div>

      {error && <div className="ai-banner ai-banner-err">{error}</div>}
      {historyUnavailable && (
        <div className="ai-banner">
          Chat history is unavailable on this server, so answers are not saved.
          You can still ask questions.
        </div>
      )}
      {saveWarning && (
        <div className="ai-banner">The last answer could not be saved to chat history.</div>
      )}

      <div className={'ai-layout' + (historyAvailable ? '' : ' ai-layout-solo')}>
        {historyAvailable && (
          <aside className="ai-sidebar" aria-label="Recent chats">
            <div className="ai-sidebar-title">Recent chats</div>
            {chats.length === 0 ? (
              <p className="ai-empty-list">No saved chats yet.</p>
            ) : (
              <ul className="ai-chat-list">
                {chats.map((row) => (
                  <li key={row.id} className="ai-chat-row">
                    <button
                      className={'ai-chat-item' + (chatId === row.id ? ' active' : '')}
                      onClick={() => openChat(row.id)}
                      disabled={sending}
                      title={row.title || 'Untitled chat'}
                    >
                      <span className="ai-chat-title">{row.title || 'Untitled chat'}</span>
                      <span className="ai-chat-meta">{timeLabel(row.updated_at)}</span>
                    </button>
                    <button
                      className="ai-chat-delete"
                      onClick={(e) => removeChat(row, e)}
                      disabled={sending}
                      title="Delete chat"
                      aria-label={`Delete ${row.title || 'chat'}`}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>
        )}

        <section className="ai-thread">
          <div className="ai-messages" ref={listRef}>
            {booting ? (
              <p className="ai-hint">Connecting to the assistant…</p>
            ) : !ready ? (
              <div className="ai-empty">
                <div className="ai-empty-title">The assistant is offline</div>
                <p className="ai-empty-text">
                  {status?.error || 'No model is connected in Open WebUI.'}
                </p>
              </div>
            ) : messages.length === 0 ? (
              <div className="ai-empty">
                <div className="ai-empty-title">Ask about your library</div>
                <p className="ai-empty-text">
                  The assistant can search Spotify and your saved albums through
                  the server-side tools. Answers are kept in your own chat history.
                </p>
                <div className="ai-suggestions">
                  {SUGGESTIONS.map((text) => (
                    <button
                      key={text}
                      className="ai-suggestion"
                      onClick={() => void send(text)}
                      disabled={sending}
                    >
                      {text}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((m) => (
                <div key={m.id} className={`ai-msg ai-msg-${m.role}`}>
                  <div className={`ai-bubble ai-bubble-${m.role}`}>{m.content}</div>
                </div>
              ))
            )}
            {sending && (
              <div className="ai-msg ai-msg-assistant">
                <div className="ai-bubble ai-bubble-assistant ai-typing" aria-label="Thinking">
                  <span /><span /><span />
                </div>
              </div>
            )}
          </div>

          <div className="ai-composer">
            <textarea
              ref={textareaRef}
              className="ai-textarea"
              rows={2}
              placeholder={ready
                ? 'Ask the assistant… (Enter to send, Shift+Enter for a new line)'
                : 'The assistant is not available.'}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={!ready || sending}
              maxLength={20000}
            />
            <div className="ai-composer-row">
              <label className="ai-tools-toggle" title="Let the model call the Spotify and reSpotIt library tools">
                <input type="checkbox" checked={useTools} onChange={toggleTools} />
                Tools
              </label>
              <span className="ai-chat-name">{chatTitle || 'New chat'}</span>
              <button
                className="btn btn-primary btn-sm"
                onClick={() => void send()}
                disabled={!ready || sending || !draft.trim()}
              >
                {sending ? 'Thinking…' : 'Send'}
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
