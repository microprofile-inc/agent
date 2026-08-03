/** 全局状态：会话列表、当前会话、消息流、供应商/模型/模式。 */

import { create } from 'zustand'
import { api, chatStream, type ChatEvent, type Provider, type SessionMeta } from '@/api/client'

export interface ToolRun {
  tool: string
  args: Record<string, unknown>
  result?: string
}

export interface Msg {
  role: 'user' | 'assistant'
  content: string
  tools: ToolRun[]
}

interface ChatState {
  sessions: SessionMeta[]
  sessionId: string | null
  messages: Msg[]
  providers: Provider[]
  provider: string
  model: string
  mode: 'think' | 'act'
  streaming: boolean

  init: () => Promise<void>
  select: (id: string) => Promise<void>
  create: () => Promise<void>
  setProvider: (p: string) => void
  setModel: (m: string) => void
  setMode: (m: 'think' | 'act') => void
  send: (text: string) => Promise<void>
}

export const useChat = create<ChatState>((set, get) => ({
  sessions: [],
  sessionId: null,
  messages: [],
  providers: [],
  provider: '',
  model: '',
  mode: 'act',
  streaming: false,

  init: async () => {
    const [{ providers }, { sessions }] = await Promise.all([
      api.providers(),
      api.sessions(),
    ])
    const p = providers[0]
    set({ providers, provider: p.name, model: p.default_model, sessions })
    if (sessions.length) await get().select(sessions[0].id)
    else await get().create()
  },

  select: async (id) => {
    const s = await api.session(id)
    set({
      sessionId: id,
      messages: s.messages.map((m) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
        tools: [],
      })),
      provider: s.state.provider,
      model: s.state.model,
      mode: s.state.mode as 'think' | 'act',
    })
  },

  create: async () => {
    const s = await api.createSession()
    const { sessions } = await api.sessions()
    set({ sessionId: s.id, messages: [], sessions })
  },

  setProvider: (p) => {
    const prov = get().providers.find((x) => x.name === p)
    set({ provider: p, model: prov?.default_model ?? '' })
  },
  setModel: (m) => set({ model: m }),
  setMode: (mode) => set({ mode }),

  send: async (text) => {
    const { sessionId, provider, model, mode } = get()
    if (!sessionId || !text.trim()) return
    set((s) => ({
      streaming: true,
      messages: [...s.messages, { role: 'user', content: text, tools: [] }],
    }))
    // 追加一条空 assistant 消息，流式填充
    set((s) => ({ messages: [...s.messages, { role: 'assistant', content: '', tools: [] }] }))

    const patch = (fn: (m: Msg) => void) =>
      set((s) => {
        const msgs = [...s.messages]
        const last = { ...msgs[msgs.length - 1], tools: [...msgs[msgs.length - 1].tools] }
        fn(last)
        msgs[msgs.length - 1] = last
        return { messages: msgs }
      })

    try {
      await chatStream(
        { session_id: sessionId, message: text, provider, model, mode },
        (ev: ChatEvent) => {
          if (ev.kind === 'text_delta') patch((m) => { m.content += ev.delta ?? '' })
          else if (ev.kind === 'tool_call')
            patch((m) => { m.tools.push({ tool: ev.tool!, args: ev.args ?? {} }) })
          else if (ev.kind === 'tool_result')
            patch((m) => {
              const t = m.tools.findLast((x) => x.result === undefined)
              if (t) t.result = ev.result
            })
        }
      )
      const { sessions } = await api.sessions()
      set({ sessions })
    } finally {
      set({ streaming: false })
    }
  },
}))
