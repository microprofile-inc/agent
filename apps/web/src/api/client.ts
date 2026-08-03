/** API 封装：REST + SSE 流式对话。 */

export interface Provider {
  name: string
  models: string[]
  default_model: string
}

export interface SessionMeta {
  id: string
  title: string
  updated_at: number
}

export interface ChatEvent {
  kind: 'text_delta' | 'tool_call' | 'tool_result' | 'done'
  delta?: string
  content?: string
  tool?: string
  args?: Record<string, unknown>
  result?: string
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export const api = {
  providers: () => req<{ providers: Provider[] }>('/api/providers'),
  sessions: () => req<{ sessions: SessionMeta[] }>('/api/sessions'),
  createSession: (title = '新会话') =>
    req<{ id: string; title: string }>('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    }),
  session: (id: string) =>
    req<{
      id: string
      title: string
      messages: { role: string; content: string }[]
      state: { provider: string; model: string; mode: string }
    }>(`/api/sessions/${id}`),
  search: (q: string) =>
    req<{ hits: (SessionMeta & { snippet: string })[] }>(
      `/api/sessions/search?q=${encodeURIComponent(q)}`
    ),
}

/** POST /api/chat，解析 SSE 流，逐事件回调。 */
export async function chatStream(
  body: {
    session_id: string
    message: string
    provider: string
    model: string
    mode: string
  },
  onEvent: (ev: ChatEvent) => void
): Promise<void> {
  const r = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok || !r.body) throw new Error(`${r.status}`)
  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        onEvent(JSON.parse(line.slice(6)) as ChatEvent)
      }
    }
  }
}
